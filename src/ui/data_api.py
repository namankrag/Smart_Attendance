"""Server-side client for the authenticated FastAPI attendance API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Any, Optional

import streamlit as st

from src.database.auth_session import get_auth_jwt, refresh_supabase_session


class DataApiError(RuntimeError):
    """A request to the attendance REST API failed."""


def _setting(name: str) -> Optional[str]:
    try:
        value = st.secrets.get(name)
    except Exception:
        value = None
    return value or os.environ.get(name)


def data_api_url() -> Optional[str]:
    # Compose injects the service hostname (worker), which must override
    # the localhost default used by native development.
    value = (
        os.environ.get("DATA_API_URL")
        or os.environ.get("REST_API_URL")
        or _setting("DATA_API_URL")
        or _setting("REST_API_URL")
    )
    return value.rstrip("/") if value else None


def _json_default(value: Any):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"cannot encode {type(value).__name__}")


def request_api(
    method: str,
    path: str,
    *,
    body: Any = None,
    internal: bool = False,
) -> Any:
    """Make one authenticated API call, refreshing an expired JWT once."""
    base_url = data_api_url()
    if not base_url:
        raise DataApiError("DATA_API_URL is not configured")
    url = f"{base_url}{path}"
    for attempt in range(2):
        token = get_auth_jwt()
        if not token:
            raise DataApiError("Sign in with Google before using the data API")
        headers = {"Authorization": f"Bearer {token}"}
        if internal:
            internal_token = _setting("API_INTERNAL_TOKEN")
            if not internal_token:
                raise DataApiError("API_INTERNAL_TOKEN is not configured")
            headers["X-Internal-Token"] = internal_token
        payload = None
        if body is not None:
            payload = json.dumps(body, default=_json_default).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and attempt == 0 and refresh_supabase_session():
                continue
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail")
            except Exception:
                detail = None
            raise DataApiError(str(detail or f"data API returned HTTP {exc.code}")) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DataApiError("The attendance API is unavailable") from exc
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))
    raise DataApiError("Supabase session expired; sign in again")


def call_database(module: str, operation: str, args: tuple, kwargs: dict) -> Any:
    return request_api(
        "POST",
        f"/api/v1/internal/{urllib.parse.quote(module, safe='')}/"
        f"{urllib.parse.quote(operation, safe='')}",
        body={"args": list(args), "kwargs": kwargs},
        internal=True,
    )


def lookup_subject_by_join_code(join_code: str) -> Any:
    code = urllib.parse.quote(join_code, safe="")
    return request_api("GET", f"/api/v1/subjects/by-join-code/{code}")


def join_subject_by_code(join_code: str) -> Any:
    return request_api(
        "POST", "/api/v1/students/me/enrollments", body={"join_code": join_code}
    )


def leave_subject(subject_id: str) -> Any:
    subject = urllib.parse.quote(subject_id, safe="")
    return request_api("DELETE", f"/api/v1/students/me/enrollments/{subject}")


def enroll_student_by_usn(subject_id: str, usn: str) -> Any:
    subject = urllib.parse.quote(subject_id, safe="")
    return request_api(
        "POST",
        f"/api/v1/subjects/{subject}/enrollments/by-usn",
        body={"usn": usn},
    )


def authenticate_student(identifier: str, pin: str) -> Any:
    return request_api(
        "POST",
        "/api/v1/auth/student",
        body={"identifier": identifier, "pin": pin},
        internal=True,
    )


def authenticate_teacher(username: str, password: str) -> Any:
    return request_api(
        "POST",
        "/api/v1/auth/teacher",
        body={"username": username, "password": password},
        internal=True,
    )
