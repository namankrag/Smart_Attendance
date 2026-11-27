"""Authenticated REST API for student, teacher, subject and attendance data."""

from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from supabase import create_client

from src.database import db, privacy, vector
from src.database.config import (
    ClientOptions,
    get_client_timeout_seconds,
    reset_request_supabase_client,
    set_request_supabase_client,
)
from src.database.auth import verify_credential

logger = logging.getLogger(__name__)

_RATE_LIMIT_OPERATIONS = {
    "check_login_allowed",
    "check_rate_limit",
    "is_locked_out",
    "record_login_attempt",
}
_SERVICE_ROLE_OPERATIONS = _RATE_LIMIT_OPERATIONS | {"check_teacher_exists"}
_DATABASE_MODULES = {"db": db, "privacy": privacy, "vector": vector}


def _create_supabase_client(url: str, key: str):
    if ClientOptions is None:
        return create_client(url, key)
    timeout = get_client_timeout_seconds()
    options = ClientOptions(
        postgrest_client_timeout=timeout,
        storage_client_timeout=timeout,
    )
    return create_client(url, key, options=options)


class DatabaseCall(BaseModel):
    args: list[Any] = Field(default_factory=list)
    kwargs: dict[str, Any] = Field(default_factory=dict)


class SubjectCreate(BaseModel):
    subject_code: str = Field(min_length=3, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    section: str = Field(min_length=1, max_length=30)


class EnrollmentCreate(BaseModel):
    student_id: str


class EnrollmentByUsn(BaseModel):
    usn: str = Field(min_length=1, max_length=100)


class JoinByCode(BaseModel):
    join_code: str = Field(min_length=1, max_length=100)


class StudentLogin(BaseModel):
    identifier: str = Field(min_length=1, max_length=100)
    pin: str = Field(min_length=4, max_length=6)


class TeacherLogin(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class AttendanceRecord(BaseModel):
    student_id: str
    is_present: bool
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class AttendanceSessionCreate(BaseModel):
    method: Literal["face", "voice", "manual", "pin"]
    records: list[AttendanceRecord] = Field(max_length=1000)


class AttendanceUpdate(BaseModel):
    is_present: bool


def _user_id(request: Request) -> str:
    return request.state.supabase_user_id


async def _with_user_client(request: Request, operation):
    def call():
        token = set_request_supabase_client(request.state.supabase_client)
        try:
            return operation()
        finally:
            reset_request_supabase_client(token)

    return await run_in_threadpool(call)


async def _call_module(request: Request, module_name: str, name: str, *args, **kwargs):
    module = _DATABASE_MODULES.get(module_name)
    fn = getattr(module, name, None) if module is not None else None
    if not callable(fn):
        raise HTTPException(status_code=404, detail="database operation not found")

    client = request.state.supabase_client
    if module_name == "db" and name in _SERVICE_ROLE_OPERATIONS:
        key = request.app.state.worker_config.supabase_service_role_key
        if not key:
            raise HTTPException(status_code=503, detail="login rate limit store is not configured")
        client = _create_supabase_client(request.app.state.worker_config.supabase_url, key)
    if module_name == "vector" and name in {"match_faces", "find_duplicate_face_owner"}:
        key = request.app.state.worker_config.supabase_service_role_key
        if not key:
            raise HTTPException(status_code=503, detail="face matching is not configured")
        client = _create_supabase_client(request.app.state.worker_config.supabase_url, key)
        subject_id = (
            args[0] if name == "match_faces" and args else kwargs.get("subject_id")
        )
        if subject_id is not None:
            teacher_id = await _profile_id(request, "teachers", "teacher_id")
            subject = await _db(request, "get_subject_by_id", str(subject_id))
            if not subject or str(subject.get("teacher_id")) != teacher_id:
                raise HTTPException(status_code=403, detail="not authorized for this subject")

    if module_name == "db" and name in {"create_student", "create_teacher"}:
        kwargs["auth_user_id"] = _user_id(request)

    def call():
        token = set_request_supabase_client(client)
        try:
            result = fn(*args, **kwargs)
            if name == "iter_attendance_csv":
                return list(result)
            return result
        finally:
            reset_request_supabase_client(token)

    try:
        return await run_in_threadpool(call)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="not authorized for this record") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("REST database operation failed: %s", name)
        raise HTTPException(status_code=500, detail="request could not be completed") from exc


async def _db(request: Request, name: str, *args, **kwargs):
    return await _call_module(request, "db", name, *args, **kwargs)


async def _profile_id(request: Request, table: str, id_column: str) -> str:
    def query():
        return (
            request.state.supabase_client.table(table)
            .select(id_column)
            .eq("auth_user_id", _user_id(request))
            .limit(1)
            .execute()
        )

    response = await _with_user_client(request, query)
    rows = response.data or []
    if not rows:
        raise HTTPException(
            status_code=403,
            detail=f"no {table[:-1]} profile is linked to this account",
        )
    return str(rows[0][id_column])


def install_rest_api(app: FastAPI, worker_config) -> None:
    """Register `/api/v1` routes and verify Supabase JWTs per request."""
    app.state.worker_config = worker_config
    router = APIRouter(prefix="/api/v1", tags=["attendance data"])

    @app.middleware("http")
    async def authenticate_data_api(request: Request, call_next):
        if not request.url.path.startswith("/api/v1/"):
            return await call_next(request)

        if "/internal/" in request.url.path or "/auth/" in request.url.path:
            expected = os.environ.get("API_INTERNAL_TOKEN", "")
            supplied = request.headers.get("x-internal-token", "")
            if not expected:
                return JSONResponse(
                    {"detail": "internal API token is not configured"}, status_code=503
                )
            if not supplied or not hmac.compare_digest(
                supplied.encode("utf-8"), expected.encode("utf-8")
            ):
                return JSONResponse({"detail": "invalid internal API token"}, status_code=401)

        auth = request.headers.get("authorization", "")
        scheme, _, jwt = auth.partition(" ")
        if scheme.lower() != "bearer" or not jwt.strip():
            return JSONResponse({"detail": "Supabase bearer token required"}, status_code=401)

        url = worker_config.supabase_url or os.environ.get("SUPABASE_URL", "")
        anon_key = (
            os.environ.get("SUPABASE_ANON_KEY")
            or os.environ.get("SUPABASE_KEY", "")
        )
        if not url or not anon_key:
            return JSONResponse(
                {"detail": "Supabase API credentials are not configured"},
                status_code=503,
            )

        client = _create_supabase_client(url, anon_key)
        try:
            result = await run_in_threadpool(client.auth.get_user, jwt.strip())
            user = getattr(result, "user", None)
            user_id = getattr(user, "id", None)
            if not user_id:
                raise ValueError("missing user id")
        except Exception:
            return JSONResponse({"detail": "invalid or expired Supabase token"}, status_code=401)

        client.postgrest.auth(jwt.strip())
        request.state.supabase_client = client
        request.state.supabase_user_id = str(user_id)
        return await call_next(request)

    def admin_client():
        key = worker_config.supabase_service_role_key
        if not key:
            raise HTTPException(status_code=503, detail="credential service is not configured")
        return _create_supabase_client(worker_config.supabase_url, key)

    def bind_profile(client, table: str, id_column: str, row: dict, user_id: str) -> None:
        profile = (
            client.table(table)
            .select("auth_user_id")
            .eq(id_column, row[id_column])
            .limit(1)
            .execute()
        )
        linked_user_id = (profile.data or [{}])[0].get("auth_user_id")
        if linked_user_id and str(linked_user_id) != user_id:
            raise HTTPException(status_code=401, detail="invalid credentials")
        if linked_user_id:
            return
        response = (
            client.table(table)
            .update({"auth_user_id": user_id})
            .eq(id_column, row[id_column])
            .is_("auth_user_id", "null")
            .execute()
        )
        if not response.data:
            latest = (
                client.table(table)
                .select("auth_user_id")
                .eq(id_column, row[id_column])
                .limit(1)
                .execute()
            )
            linked_user_id = (latest.data or [{}])[0].get("auth_user_id")
            if not linked_user_id or str(linked_user_id) != user_id:
                raise HTTPException(status_code=401, detail="invalid credentials")

    @router.post("/auth/student")
    async def authenticate_student(body: StudentLogin, request: Request):
        identifier = body.identifier.strip()
        client = admin_client()

        def authenticate():
            token = set_request_supabase_client(client)
            try:
                allowed, _ = db.check_login_allowed(identifier, "pin", client=client)
                if not allowed:
                    raise HTTPException(status_code=429, detail="too many failed attempts")
                student = db.get_student_for_login(identifier)
                if not student or not student.get("pin_hash"):
                    db.record_login_attempt(identifier, "pin", False, client=client)
                    raise HTTPException(status_code=401, detail="invalid credentials")
                ok, needs_rehash = verify_credential(body.pin, student["pin_hash"])
                db.record_login_attempt(identifier, "pin", ok, client=client)
                if not ok:
                    raise HTTPException(status_code=401, detail="invalid credentials")
                bind_profile(client, "students", "student_id", student, _user_id(request))
                if needs_rehash:
                    db.update_student_pin_hash(
                        str(student["student_id"]), db.hash_pin(body.pin)
                    )
                return {
                    "student_id": str(student["student_id"]),
                    "usn": student.get("usn"),
                    "name": student.get("name"),
                }
            finally:
                reset_request_supabase_client(token)

        return await run_in_threadpool(authenticate)

    @router.post("/auth/teacher")
    async def authenticate_teacher(body: TeacherLogin, request: Request):
        username = body.username.strip().lower()
        client = admin_client()

        def authenticate():
            token = set_request_supabase_client(client)
            try:
                allowed, _ = db.check_login_allowed(username, "teacher", client=client)
                if not allowed:
                    raise HTTPException(status_code=429, detail="too many failed attempts")
                result = db.teacher_login_with_rehash(username, body.password)
                if not result:
                    db.record_login_attempt(username, "teacher", False, client=client)
                    raise HTTPException(status_code=401, detail="invalid credentials")
                teacher, needs_rehash = result
                db.record_login_attempt(username, "teacher", True, client=client)
                bind_profile(client, "teachers", "teacher_id", teacher, _user_id(request))
                if needs_rehash:
                    db.update_teacher_password_hash(
                        str(teacher["teacher_id"]), db.hash_password(body.password)
                    )
                return {
                    "teacher_id": str(teacher["teacher_id"]),
                    "username": teacher.get("username"),
                    "name": teacher.get("name"),
                }
            finally:
                reset_request_supabase_client(token)

        return await run_in_threadpool(authenticate)

    @router.post("/internal/{module_name}/{operation}", include_in_schema=False)
    async def call_existing_database_function(
        module_name: str, operation: str, body: DatabaseCall, request: Request
    ):
        module = _DATABASE_MODULES.get(module_name)
        if (
            module is None
            or operation not in getattr(module, "__all__", ())
            or operation.startswith("_")
        ):
            raise HTTPException(status_code=404, detail="database operation not found")
        if not callable(getattr(module, operation, None)):
            raise HTTPException(status_code=404, detail="database operation not found")
        result = await _call_module(
            request, module_name, operation, *body.args, **body.kwargs
        )
        return result

    @router.get("/students/me")
    async def student_profile(request: Request):
        def query():
            response = (
                request.state.supabase_client.table("students")
                .select("student_id, usn, name")
                .eq("auth_user_id", _user_id(request))
                .limit(1)
                .execute()
            )
            return response.data or []

        rows = await _with_user_client(request, query)
        if not rows:
            raise HTTPException(status_code=404, detail="student profile not found")
        return rows[0]

    @router.get("/students/me/subjects")
    async def student_subjects(
        request: Request,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        student_id = await _profile_id(request, "students", "student_id")
        return await _db(request, "get_student_subjects", student_id, limit, offset)

    @router.get("/students/me/attendance")
    async def student_attendance(
        request: Request,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        student_id = await _profile_id(request, "students", "student_id")
        return await _db(request, "get_student_attendance", student_id, limit, offset)

    @router.post("/students/me/enrollments", status_code=201)
    async def join_subject(body: JoinByCode, request: Request):
        student_id = await _profile_id(request, "students", "student_id")

        def join():
            response = request.state.supabase_client.rpc(
                "enroll_student_by_join_code", {"p_join_code": body.join_code.strip()}
            ).execute()
            return response.data

        try:
            return await _with_user_client(request, join)
        except Exception as exc:
            if "P0002" in str(exc) or "join code not found" in str(exc).lower():
                raise HTTPException(status_code=404, detail="join code not found") from exc
            logger.exception("Student join by code failed")
            raise HTTPException(status_code=500, detail="request could not be completed") from exc

    @router.delete("/students/me/enrollments/{subject_id}")
    async def leave_subject(subject_id: str, request: Request):
        await _profile_id(request, "students", "student_id")

        def leave():
            response = request.state.supabase_client.rpc(
                "unenroll_student_self", {"p_subject_id": subject_id}
            ).execute()
            return response.data

        try:
            return await _with_user_client(request, leave)
        except Exception as exc:
            raise HTTPException(status_code=404, detail="enrollment not found") from exc

    @router.get("/teachers/me/subjects")
    async def teacher_subjects(
        request: Request,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        teacher_id = await _profile_id(request, "teachers", "teacher_id")
        return await _db(request, "get_teacher_subjects", teacher_id, limit, offset)

    @router.get("/teachers/me/attendance")
    async def teacher_attendance(
        request: Request,
        subject_id: Optional[str] = None,
        is_present: Optional[bool] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        teacher_id = await _profile_id(request, "teachers", "teacher_id")
        return await _db(
            request,
            "get_attendance_records",
            teacher_id,
            subject_id=subject_id,
            is_present=is_present,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        )

    @router.post("/subjects", status_code=201)
    async def create_subject(body: SubjectCreate, request: Request):
        teacher_id = await _profile_id(request, "teachers", "teacher_id")
        rows = await _db(
            request,
            "create_subject",
            body.subject_code,
            body.name,
            body.section,
            teacher_id,
        )
        return rows[0] if rows else {}

    @router.get("/subjects/by-join-code/{join_code}")
    async def preview_subject_by_join_code(join_code: str, request: Request):
        key = request.app.state.worker_config.supabase_service_role_key
        if not key:
            raise HTTPException(
                status_code=503,
                detail="subject invitation lookup is not configured",
            )

        def lookup():
            response = (
                _create_supabase_client(request.app.state.worker_config.supabase_url, key)
                .table("subjects")
                .select("subject_id, subject_code, name, section, teacher_id")
                .eq("join_code", join_code.strip())
                .limit(1)
                .execute()
            )
            return response.data or []

        rows = await run_in_threadpool(lookup)
        if not rows:
            raise HTTPException(status_code=404, detail="join code not found")
        return rows[0]

    @router.get("/subjects/{subject_id}")
    async def get_subject(subject_id: str, request: Request):
        subject = await _db(request, "get_subject_by_id", subject_id)
        if not subject:
            raise HTTPException(status_code=404, detail="subject not found")
        subject.pop("join_code", None)
        return subject

    @router.get("/subjects/{subject_id}/students")
    async def subject_students(
        subject_id: str,
        request: Request,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ):
        rows = await _db(request, "get_enrolled_students", subject_id, limit, offset)
        for row in rows:
            student = row.get("students")
            if isinstance(student, dict):
                student.pop("face_embedding", None)
                student.pop("voice_embedding", None)
        return rows

    @router.post("/subjects/{subject_id}/enrollments", status_code=201)
    async def enroll_student(subject_id: str, body: EnrollmentCreate, request: Request):
        await _profile_id(request, "teachers", "teacher_id")
        return await _db(request, "enroll_student_to_subject", body.student_id, subject_id)

    @router.post("/subjects/{subject_id}/enrollments/by-usn", status_code=201)
    async def enroll_student_by_usn(subject_id: str, body: EnrollmentByUsn, request: Request):
        await _profile_id(request, "teachers", "teacher_id")

        def enroll():
            response = request.state.supabase_client.rpc(
                "enroll_student_by_usn",
                {"p_subject_id": subject_id, "p_usn": body.usn.strip()},
            ).execute()
            return response.data

        try:
            return await _with_user_client(request, enroll)
        except Exception as exc:
            message = str(exc).lower()
            if "p0002" in message or "student not found" in message:
                raise HTTPException(status_code=404, detail="student not found") from exc
            if "42501" in message or "not authorized" in message:
                raise HTTPException(
                    status_code=403, detail="not authorized for this subject"
                ) from exc
            logger.exception("Teacher roster enrollment by USN failed")
            raise HTTPException(status_code=500, detail="request could not be completed") from exc

    @router.delete("/subjects/{subject_id}/enrollments/{student_id}")
    async def unenroll_student(subject_id: str, student_id: str, request: Request):
        await _profile_id(request, "teachers", "teacher_id")
        return await _db(request, "unenroll_student_to_subject", student_id, subject_id)

    @router.post("/subjects/{subject_id}/sessions", status_code=201)
    async def create_attendance_session(
        subject_id: str, body: AttendanceSessionCreate, request: Request
    ):
        teacher_id = await _profile_id(request, "teachers", "teacher_id")
        if len({row.student_id for row in body.records}) != len(body.records):
            raise HTTPException(status_code=422, detail="student_id values must be unique")
        enrolled = await _db(request, "get_enrolled_students", subject_id, limit=1000, offset=0)
        enrolled_ids = {row.get("student_id") for row in enrolled}
        if not all(row.student_id in enrolled_ids for row in body.records):
            raise HTTPException(
                status_code=403,
                detail="attendance records must be for enrolled students",
            )
        session = await _db(request, "create_session", subject_id, teacher_id, body.method)
        timestamp = session.get("started_at") or datetime.now(timezone.utc).isoformat()
        logs = [
            {
                "student_id": row.student_id,
                "subject_id": subject_id,
                "timestamp": timestamp,
                "is_present": row.is_present,
                "method": body.method,
                "confidence": row.confidence,
            }
            for row in body.records
        ]
        await _db(request, "create_attendance_upsert", logs, session["session_id"])
        return session

    @router.patch("/attendance/{log_id}")
    async def update_attendance(log_id: int, body: AttendanceUpdate, request: Request):
        teacher_id = await _profile_id(request, "teachers", "teacher_id")
        return await _db(
            request,
            "update_attendance_status",
            log_id,
            body.is_present,
            teacher_id=teacher_id,
        )

    @router.delete("/subjects/{subject_id}")
    async def delete_subject(subject_id: str, request: Request):
        teacher_id = await _profile_id(request, "teachers", "teacher_id")
        return await _db(
            request,
            "delete_subject_transactional",
            subject_id,
            teacher_id=teacher_id,
        )

    app.include_router(router)
