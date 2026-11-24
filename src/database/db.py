"""Database access layer for Smart Attendance (Phase 0 rewrite).

Security invariants (each enforced below, with a cited source in comments):
- Student, teacher, subject and session IDs are UUID strings. The existing
  ``attendance_logs.id`` primary key is a BIGINT; log IDs are never used as
  authorization. Ownership is enforced by checks in this module, not by ID
  secrecy.
- No ``SELECT *`` anywhere in this module. Every query names its columns,
  so a credential hash (``teachers.password`` / ``students.pin_hash``) is
  only fetched by the one login function that needs it, and is never
  returned to callers (``teacher_login`` strips ``password`` before
  returning; ``get_student_for_login`` is the only student fetch that
  includes ``pin_hash``, and screens must use it instead of
  ``get_all_students`` -- see that function's docstring).
- Reads are paginated (``limit``/``offset`` + ``.range()``) and capped at
  1000 rows; nothing in this module loads a whole table. Counts come from
  the database (``count`` / embedded ``(count)``), never from loading rows.
- Reads use ``db_retry_read`` (bounded, transient-only). Writes use
  ``db_retry_write`` (no retry -- see ``src/database/config.py``).
- Writes that mutate another user's data verify ownership first and raise
  ``PermissionError`` otherwise. RLS in the database is the backstop; these
  checks are the application layer and must never be removed because "RLS
  covers it".
- PINs / passwords are hashed with Argon2id via ``src/database/auth.py``
  (OWASP Password Storage Cheat Sheet:
  https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
  ``hash_pass`` / ``check_pass`` below are deprecated wrappers kept only
  for the old screens; new code must use ``auth.py`` directly.
- Login throttling lives in ``src/database/rate_limit.py`` (single source
  of truth) and is re-exported here; see its docstring for the OWASP
  Authentication Cheat Sheet policy:
  https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html

Assumed Phase 0 migrated schema (migration agent owns the DDL; if a table
or column below does not exist, Supabase raises and the error propagates
-- this module never silently falls back):
- ``students(student_id UUID PK, usn TEXT UNIQUE, name, pin_hash,
  face_embedding, voice_embedding)``
- ``teachers(teacher_id UUID PK, username UNIQUE, password, name)``
- ``subjects(subject_id UUID PK, subject_code, name, section, teacher_id FK)``
- ``subject_students(id, student_id FK, subject_id FK)``
- ``attendance_sessions(session_id UUID PK, subject_id FK, teacher_id FK,
  method, created_at)``
- ``attendance_logs(id BIGINT PK, session_id FK, student_id FK, subject_id FK,
  timestamp, is_present)`` with
  ``UNIQUE (session_id, student_id)`` (required by
  :func:`create_attendance_upsert`'s ``on_conflict``).
- ``login_attempts(identifier, kind, success, attempted_at)`` (rate_limit).
"""

from __future__ import annotations

import math
import re
import secrets
import warnings
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import UUID

from src.database.auth import (
    hash_password,
    hash_pin,
    verify_credential,
)
from src.database.timeutil import parse_iso_timestamp
from src.database.config import (
    check_pin_schema_guard,
    db_retry_read,
    db_retry_write,
    supabase,
)
from src.database.rate_limit import (
    check_login_allowed,
    check_rate_limit,
    is_locked_out,
    record_login_attempt,
)
from src.database.roster import validate_usn

__all__ = [
    "hash_pass",
    "check_pass",
    "check_teacher_exists",
    "create_teacher",
    "teacher_login",
    "get_student_for_login",
    "get_student_by_usn",
    "get_student_by_id",
    "get_all_students",
    "create_student",
    "add_student_face_embedding",
    "cosine_similarity",
    "create_subject",
    "get_teacher_subjects",
    "enroll_student_to_subject",
    "unenroll_student_to_subject",
    "get_student_subjects",
    "get_student_attendance",
    "create_attendance",
    "create_attendance_upsert",
    "create_session",
    "get_attendance_for_teacher",
    "get_session_details",
    "update_attendance_status",
    "delete_subject",
    "check_pin_schema_guard",
    "get_subject_by_join_code",
    "get_subject_join_code",
    "is_student_enrolled",
    "get_enrolled_students",
    "get_subject_session_summary",
    "delete_subject_transactional",
    "record_login_attempt",
    "check_login_allowed",
    "check_rate_limit",
    "is_locked_out",
    # --- Phase 1 additions -------------------------------------------------
    "update_student_pin_hash",
    "update_teacher_password_hash",
    "teacher_login_with_rehash",
    "update_voice_embedding",
    "get_subject_by_id",
    "get_attendance_records",
    "count_attendance_for_teacher",
    "get_session_counts",
    "get_attendance_percentage",
    "iter_attendance_csv",
]

# --- Pagination / gallery constants -----------------------------------------
MAX_PAGE_SIZE = 1000
DEFAULT_PAGE_SIZE = 100
MAX_FACE_EMBEDDINGS = 5
FACE_EMBEDDING_DIM = 128
# Provisional: a new face template must be this similar (cosine) to an
# existing verified template of the same student, otherwise it is rejected
# as plausibly the wrong person. 0.85 is a *starting* value, NOT a calibrated
# operating point: it must be calibrated in Phase 2 against the deployed
# embedding model / camera conditions per ISO/IEC 19795-1 (biometric
# performance testing) before it is trusted in production, and re-checked
# whenever the embedding model changes.
# https://www.iso.org/standard/41424.html
FACE_SIMILARITY_THRESHOLD = 0.85
TEACHER_PASSWORD_MIN_LENGTH = 6
SESSION_METHODS = ("face", "voice", "manual", "pin")

# Columns fetched for a student login attempt -- the ONLY student query
# that includes pin_hash. Never add pin_hash to any other student select.
_LOGIN_COLUMNS = "student_id, usn, name, pin_hash, face_embedding, voice_embedding"
_STUDENT_PROFILE_COLUMNS = "student_id, usn, name, face_embedding, voice_embedding"


def _validate_pagination(limit: int, offset: int) -> Tuple[int, int]:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if limit > MAX_PAGE_SIZE:
        raise ValueError(f"limit must be <= {MAX_PAGE_SIZE}")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    return limit, offset


def _require_id(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty UUID string")
    return value.strip()


def _require_attendance_log_id(value: Any) -> str | int:
    """Accept the live BIGINT log key and UUID/string keys from old installs."""
    if isinstance(value, bool):
        raise ValueError("log_id must be a positive integer or non-empty string")
    if isinstance(value, int):
        if value < 1:
            raise ValueError("log_id must be a positive integer")
        return value
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError("log_id must be a positive integer or non-empty string")


# ==========================================
# Deprecated credential wrappers
# ==========================================


def hash_pass(pwd: str) -> str:
    """DEPRECATED: use :func:`src.database.auth.hash_password` directly.

    Behaviour change vs the old implementation: the old wrapper stripped
    the password and used bcrypt (72-byte silent truncation). The new
    implementation hashes with Argon2id, does not strip, and SHA-256
    pre-hashes passwords longer than 72 UTF-8 bytes -- see auth.py.
    """
    warnings.warn(
        "hash_pass is deprecated; use src.database.auth.hash_password",
        DeprecationWarning,
        stacklevel=2,
    )
    return hash_password(pwd)


def check_pass(pwd: str, hashed: str) -> bool:
    """DEPRECATED: use :func:`src.database.auth.verify_credential` directly.

    Returns only the boolean; the ``needs_rehash`` half of
    ``verify_credential`` is discarded, so callers that care about
    migrating legacy bcrypt hashes must switch to ``verify_credential``.
    """
    warnings.warn(
        "check_pass is deprecated; use src.database.auth.verify_credential",
        DeprecationWarning,
        stacklevel=2,
    )
    ok, _ = verify_credential(pwd, hashed)
    return ok


# ==========================================
# Teacher Authentication & Profiles
# ==========================================


@db_retry_read()
def check_teacher_exists(username: str) -> bool:
    username = username.strip().lower()
    response = (
        supabase.table("teachers").select("username").eq("username", username).limit(1).execute()
    )
    return bool(response.data)


@db_retry_write
def create_teacher(username: str, password: str, name: str) -> List[Dict[str, Any]]:
    username = username.strip().lower()
    name = name.strip()
    if not username:
        raise ValueError("username cannot be empty")
    if not name:
        raise ValueError("name cannot be empty")
    # OWASP Authentication Cheat Sheet: enforce a minimum password length.
    # https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
    if not isinstance(password, str) or len(password) < TEACHER_PASSWORD_MIN_LENGTH:
        raise ValueError(f"password must be at least {TEACHER_PASSWORD_MIN_LENGTH} characters")
    data = {
        "username": username,
        # Argon2id (OWASP Password Storage Cheat Sheet) -- never store or
        # log the plaintext password.
        # https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
        "password": hash_password(password),
        "name": name,
    }
    response = supabase.table("teachers").insert(data).execute()
    return response.data or []


@db_retry_read()
def teacher_login(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Verify a teacher login. Returns the teacher WITHOUT the password hash.

    Only the columns needed for login are selected (no SELECT *), and the
    stored hash is stripped from the returned dict: a credential hash must
    never be handed to UI code / session state.
    """
    username = username.strip().lower()
    response = (
        supabase.table("teachers")
        .select("teacher_id, username, password, name")
        .eq("username", username)
        .limit(1)
        .execute()
    )
    if not response.data:
        return None
    teacher = dict(response.data[0])
    stored = teacher.pop("password", "")
    ok, _needs_rehash = verify_credential(password, stored)
    if not ok:
        return None
    # NOTE: when needs_rehash is True the caller (login flow) should
    # re-hash with hash_password and update the row -- transparent
    # migration of legacy bcrypt hashes to Argon2id. Not done here because
    # this is a read path; the write belongs to the login flow, which also
    # owns rate limiting (see rate_limit.py).
    return teacher


# ==========================================
# Student Profiles & Biometrics
# ==========================================


@db_retry_read()
def get_student_for_login(student_id_or_usn: str) -> Optional[Dict[str, Any]]:
    """Fetch the single student row needed to verify a PIN login.

    This is the ONLY student fetch that returns ``pin_hash``. It selects
    exactly ``student_id, usn, name, pin_hash, face_embedding,
    voice_embedding`` -- no other columns, no SELECT *. Accepts either a
    UUID ``student_id`` or a ``usn`` (USN is tried first). Provisional
    ``LEGACY-<id>`` USNs also accept spaces around the hyphen. Callers must
    verify the PIN with ``auth.verify_credential`` and enforce rate
    limiting via ``rate_limit.check_login_allowed`` / ``record_login_attempt``;
    a row returned here is NOT an authenticated session.
    """
    if not isinstance(student_id_or_usn, str) or not student_id_or_usn.strip():
        return None
    value = student_id_or_usn.strip()
    legacy_match = re.fullmatch(r"LEGACY\s*-\s*(\d+)", value, flags=re.IGNORECASE)
    if legacy_match:
        value = f"LEGACY-{legacy_match.group(1)}"
    try:
        usn = validate_usn(value)
    except ValueError:
        usn = None
    if usn is not None:
        response = (
            supabase.table("students").select(_LOGIN_COLUMNS).eq("usn", usn).limit(1).execute()
        )
        if response.data:
            return response.data[0]
    try:
        student_id = str(UUID(value))
    except ValueError:
        return None
    response = (
        supabase.table("students")
        .select(_LOGIN_COLUMNS)
        .eq("student_id", student_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


@db_retry_read()
def get_student_by_usn(usn: str) -> Optional[Dict[str, Any]]:
    """Fetch a student by USN. Explicit columns; does NOT return pin_hash."""
    usn = validate_usn(usn)
    response = (
        supabase.table("students")
        .select(_STUDENT_PROFILE_COLUMNS)
        .eq("usn", usn)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


@db_retry_read()
def get_student_by_id(student_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a student by UUID. Explicit columns; does NOT return pin_hash."""
    student_id = _require_id(student_id, "student_id")
    response = (
        supabase.table("students")
        .select(_STUDENT_PROFILE_COLUMNS)
        .eq("student_id", student_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


@db_retry_read()
def get_all_students(
    limit: int = DEFAULT_PAGE_SIZE, offset: int = 0, page_size: int = DEFAULT_PAGE_SIZE
) -> List[Dict[str, Any]]:
    """Return ONE page of students (explicit columns, never pin_hash).

    WARNING -- NEVER use this for login. It does not return ``pin_hash``,
    and it returns at most one page. The old implementation loaded the
    whole table (and old screens used it to find a student and check their
    PIN in the client) -- that pattern is removed: use
    :func:`get_student_for_login` for login and page through this function
    (``offset += len(page)`` until a short page) for bulk work such as
    building a face classifier. ``limit`` is the max rows for this call,
    ``page_size`` caps the page (both must be <= 1000).
    """
    limit, offset = _validate_pagination(limit, offset)
    if not isinstance(page_size, int) or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
    effective = min(limit, page_size)
    response = (
        supabase.table("students")
        .select(_STUDENT_PROFILE_COLUMNS)
        .range(offset, offset + effective - 1)
        .execute()
    )
    return response.data or []


@db_retry_write
def create_student(
    name: str,
    face_embedding: Optional[Any] = None,
    voice_embedding: Optional[Any] = None,
    *,
    pin: str,
    usn: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Register a student. ``pin`` is REQUIRED (keyword-only).

    The PIN is validated (4-6 digits, :func:`auth.validate_pin`) and
    Argon2id-hashed (:func:`auth.hash_pin`). There is deliberately NO
    silent fallback: if the insert fails -- including because the
    ``pin_hash`` column is missing -- the error propagates and no student
    is created without a PIN. The old fallback that retried the insert
    with ``pin_hash`` dropped (creating PIN-less accounts that could log
    in with no credential) is removed; see also
    ``config.check_pin_schema_guard``.
    """
    name = name.strip() if isinstance(name, str) else ""
    if not name:
        raise ValueError("name cannot be empty")
    pin_hash = hash_pin(pin)  # raises ValueError for an invalid/missing PIN
    data: Dict[str, Any] = {
        "name": name,
        "face_embedding": face_embedding,
        "voice_embedding": voice_embedding,
        "pin_hash": pin_hash,
    }
    if usn is not None:
        data["usn"] = validate_usn(usn)
    response = supabase.table("students").insert(data).execute()
    return response.data or []


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two equal-length vectors, in [-1, 1].

    A zero-norm vector has no direction, so its similarity to anything is
    defined as 0.0 here (rather than raising) -- a zero embedding can never
    count as a match. Defined in this module (not imported from pipelines)
    to avoid a ``pipelines -> database -> pipelines`` circular import.
    """
    if len(a) != len(b) or len(a) == 0:
        raise ValueError("embeddings must be non-empty and of equal length")
    dot = sum(float(x) * float(y) for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(float(x) * float(x) for x in a))
    norm_b = math.sqrt(sum(float(y) * float(y) for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _normalise_gallery(stored: Any) -> List[List[float]]:
    """Parse a stored ``face_embedding`` (one 128-vector or a list of them)."""
    gallery: List[List[float]] = []
    if not stored:
        return gallery
    if isinstance(stored, list) and stored and isinstance(stored[0], (int, float)):
        if len(stored) == FACE_EMBEDDING_DIM:
            gallery.append([float(x) for x in stored])
        return gallery
    if isinstance(stored, list):
        for item in stored:
            if isinstance(item, list) and len(item) == FACE_EMBEDDING_DIM:
                gallery.append([float(x) for x in item])
    return gallery


def _validate_embedding(new_embedding: Any) -> List[float]:
    if not isinstance(new_embedding, list) or len(new_embedding) != FACE_EMBEDDING_DIM:
        raise ValueError(f"New face embedding must be a {FACE_EMBEDDING_DIM}-dimensional vector")
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in new_embedding):
        raise ValueError("Face embedding must contain only numbers")
    if not all(math.isfinite(float(x)) for x in new_embedding):
        raise ValueError("Face embedding must contain only finite numbers")
    return [float(x) for x in new_embedding]


@db_retry_write
def add_student_face_embedding(
    student_id: str,
    new_embedding: List[float],
    *,
    reauthenticated: bool = False,
    max_embeddings: int = MAX_FACE_EMBEDDINGS,
) -> Optional[List[Dict[str, Any]]]:
    """Append a face template to a student, only after re-authentication.

    - ``reauthenticated`` MUST be True: adding a biometric template is a
      sensitive action and requires a fresh authentication (PIN + face, or
      equivalent) immediately before the call. ``PermissionError`` otherwise.
      The old code let any logged-in session add templates unchecked.
    - The new template must have cosine similarity >=
      ``FACE_SIMILARITY_THRESHOLD`` (0.85, provisional -- see the constant's
      comment / ISO/IEC 19795-1) to at least one existing verified template,
      otherwise it is rejected as plausibly the wrong person. A student
      with no existing templates (fresh enrolment) is exempt from the check.
    - The ORIGINAL enrolment template (gallery index 0) is NEVER evicted:
      it is the verified anchor. When the gallery would exceed
      ``max_embeddings``, the oldest *non-original* template is dropped
      first, so the gallery keeps the original plus the most recent ones.
    """
    student_id = _require_id(student_id, "student_id")
    if not reauthenticated:
        # OWASP Authentication Cheat Sheet: sensitive actions require
        # re-authentication; a stale session alone is not enough.
        # https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
        raise PermissionError("Adding a face embedding requires fresh re-authentication")
    new_vec = _validate_embedding(new_embedding)
    if not isinstance(max_embeddings, int) or max_embeddings < 1:
        raise ValueError("max_embeddings must be a positive integer")

    response = (
        supabase.table("students")
        .select("face_embedding")
        .eq("student_id", student_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        return None
    gallery = _normalise_gallery(response.data[0].get("face_embedding"))

    if gallery:
        best = max(cosine_similarity(new_vec, existing) for existing in gallery)
        if best < FACE_SIMILARITY_THRESHOLD:
            raise ValueError(
                "New face embedding too dissimilar to the student's verified "
                f"templates (max cosine similarity {best:.3f} < "
                f"{FACE_SIMILARITY_THRESHOLD}); refusing to add it"
            )

    gallery.append(new_vec)
    # Cap, preserving index 0 (original enrolment) always: drop the oldest
    # non-original template(s) first.
    while len(gallery) > max_embeddings:
        del gallery[1]

    update_resp = (
        supabase.table("students")
        .update({"face_embedding": gallery})
        .eq("student_id", student_id)
        .execute()
    )
    return update_resp.data


# ==========================================
# Subject & Classroom Management
# ==========================================


@db_retry_write
def create_subject(
    sub_code: str, name: str, sec: str, teacher_id: str, *, join_code: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Create a subject with a SEPARATE join_code (audit 32).

    ``join_code`` is distinct from ``subject_code`` so sections can share
    a subject code. If not supplied, a URL-safe random code is generated
    (secrets.token_urlsafe — unguessable, unlike the old globally-unique
    subject_code used as the join key).
    """
    sub_code = sub_code.strip().upper()
    name = name.strip()
    sec = sec.strip().upper()
    teacher_id = _require_id(teacher_id, "teacher_id")
    if not sub_code or not name or not sec:
        raise ValueError("subject code, name and section cannot be empty")
    if join_code is None:
        join_code = secrets.token_urlsafe(9)
    data = {
        "subject_code": sub_code,
        "name": name,
        "section": sec,
        "teacher_id": teacher_id,
        "join_code": join_code,
    }
    response = supabase.table("subjects").insert(data).execute()
    return response.data or []


@db_retry_read()
def get_subject_by_join_code(join_code: str) -> Optional[Dict[str, Any]]:
    """Fetch a subject by its (separate, URL-safe) join_code, not subject_code."""
    if not isinstance(join_code, str) or not join_code.strip():
        return None
    response = (
        supabase.table("subjects")
        .select("subject_id, subject_code, name, section, teacher_id, join_code")
        .eq("join_code", join_code.strip())
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


@db_retry_read()
def get_subject_join_code(subject_id: str) -> Optional[str]:
    """Return a subject's join_code, looking it up by UUID (or, as a
    fallback, by subject_code for pre-migration callers)."""
    if not isinstance(subject_id, str) or not subject_id.strip():
        return None
    value = subject_id.strip()
    for column in ("subject_id", "subject_code"):
        response = (
            supabase.table("subjects").select("join_code").eq(column, value).limit(1).execute()
        )
        if response.data and response.data[0].get("join_code"):
            return response.data[0]["join_code"]
    return None


@db_retry_read()
def is_student_enrolled(student_id: str, subject_id: str) -> bool:
    """True iff the student is enrolled in the subject."""
    student_id = _require_id(student_id, "student_id")
    subject_id = _require_id(subject_id, "subject_id")
    response = (
        supabase.table("subject_students")
        .select("student_id")
        .eq("student_id", student_id)
        .eq("subject_id", subject_id)
        .limit(1)
        .execute()
    )
    return bool(response.data)


@db_retry_read()
def get_enrolled_students(
    subject_id: str, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
) -> List[Dict[str, Any]]:
    """One page of enrolments for a subject, with the student record
    embedded (explicit columns; no pin_hash). Live
    ``subject_students`` has no ``id`` column — do not select it."""
    subject_id = _require_id(subject_id, "subject_id")
    limit, offset = _validate_pagination(limit, offset)
    response = (
        supabase.table("subject_students")
        .select(
            "student_id, subject_id, enrolled_at, "
            "students(student_id, usn, name, face_embedding, voice_embedding)"
        )
        .eq("subject_id", subject_id)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return response.data or []


@db_retry_read()
def get_subject_session_summary(subject_id: str) -> Dict[str, Any]:
    """Session counts for one subject from ``attendance_sessions``.

    Returns {"total_classes": int, "session_timestamps": [str, ...]}.
    Used by get_student_subjects so the student dashboard is not left
    with total_classes=0 after the Phase 0 pagination rewrite.
    """
    subject_id = _require_id(subject_id, "subject_id")
    response = (
        supabase.table("attendance_sessions")
        .select("session_id, started_at")
        .eq("subject_id", subject_id)
        .order("started_at")
        .limit(MAX_PAGE_SIZE)
        .execute()
    )
    rows = response.data or []
    return {
        "total_classes": len(rows),
        "session_timestamps": [r.get("started_at") for r in rows if r.get("started_at")],
    }


@db_retry_read()
def get_teacher_subjects(
    teacher_id: str, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
) -> List[Dict[str, Any]]:
    """Return ONE page of subjects owned by a teacher, with counts from SQL.

    ``total_students`` / ``total_classes`` come from embedded ``(count)``
    aggregates, not from loading enrolment / log rows. ``total_classes``
    counts rows in ``attendance_sessions`` (Phase 0 migration table); it is
    not derived from ``attendance_logs`` timestamps any more.
    """
    teacher_id = _require_id(teacher_id, "teacher_id")
    limit, offset = _validate_pagination(limit, offset)
    response = (
        supabase.table("subjects")
        .select(
            "subject_id, subject_code, name, section, teacher_id, join_code, "
            "subject_students(count), attendance_sessions(count)"
        )
        .eq("teacher_id", teacher_id)
        .range(offset, offset + limit - 1)
        .execute()
    )
    subjects = response.data or []
    for sub in subjects:
        enrol = sub.get("subject_students") or []
        sub["total_students"] = enrol[0].get("count", 0) if enrol else 0
        sessions = sub.get("attendance_sessions") or []
        sub["total_classes"] = sessions[0].get("count", 0) if sessions else 0
        sub.pop("subject_students", None)
        sub.pop("attendance_sessions", None)
    return subjects


@db_retry_write
def enroll_student_to_subject(student_id: str, subject_id: str) -> List[Dict[str, Any]]:
    """Idempotently enroll a student in a subject (no synthetic history)."""
    student_id = _require_id(student_id, "student_id")
    subject_id = _require_id(subject_id, "subject_id")
    data = {"student_id": student_id, "subject_id": subject_id}
    existing = (
        supabase.table("subject_students")
        .select("student_id")
        .eq("student_id", student_id)
        .eq("subject_id", subject_id)
        .execute()
    )
    if existing.data:
        return existing.data
    response = supabase.table("subject_students").insert(data).execute()
    return response.data or []


@db_retry_write
def unenroll_student_to_subject(student_id: str, subject_id: str) -> Dict[str, Any]:
    """Unenroll a student from a subject by removing their enrollment record."""
    student_id = _require_id(student_id, "student_id")
    subject_id = _require_id(subject_id, "subject_id")
    try:
        enroll_response = (
            supabase.table("subject_students")
            .delete()
            .eq("student_id", student_id)
            .eq("subject_id", subject_id)
            .execute()
        )
        return {
            "success": True,
            "enrollment_deleted": len(enroll_response.data or []),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)}


@db_retry_read()
def get_student_subjects(
    student_id: str, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
) -> List[Dict[str, Any]]:
    """Return ONE page of a student's enrolments with subject details.

    NOTE (breaking change vs the old version): ``total_classes`` /
    ``session_timestamps`` are no longer computed here -- computing them
    required loading every attendance log for every subject. Callers that
    need session counts must query ``attendance_sessions`` (count) for the
    subject instead.
    """
    student_id = _require_id(student_id, "student_id")
    limit, offset = _validate_pagination(limit, offset)
    response = (
        supabase.table("subject_students")
        .select(
            "subject_id, enrolled_at, subjects(subject_id, subject_code, name, section, teacher_id)"
        )
        .eq("student_id", student_id)
        .range(offset, offset + limit - 1)
        .execute()
    )
    enrollments = response.data or []
    # Restore total_classes / session_timestamps without loading attendance
    # logs: count sessions in SQL (attendance_sessions). Bounded: one
    # small query per enrolled subject on the current page.
    for item in enrollments:
        sub = item.get("subjects") or {}
        sid = sub.get("subject_id")
        if not sid:
            continue
        try:
            summary = get_subject_session_summary(sid)
        except Exception:
            summary = {"total_classes": 0, "session_timestamps": []}
        sub["total_classes"] = summary["total_classes"]
        sub["session_timestamps"] = summary["session_timestamps"]
    return enrollments


# ==========================================
# Attendance Operations
# ==========================================


@db_retry_read()
def get_student_attendance(
    student_id: str, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
) -> List[Dict[str, Any]]:
    """Return ONE page of attendance records for a student (explicit columns)."""
    student_id = _require_id(student_id, "student_id")
    limit, offset = _validate_pagination(limit, offset)
    response = (
        supabase.table("attendance_logs")
        .select(
            "id, session_id, student_id, subject_id, timestamp, is_present, "
            "subjects(subject_id, subject_code, name), attendance_sessions(started_at)"
        )
        .eq("student_id", student_id)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return response.data or []


@db_retry_write
def create_attendance(logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Batch-insert attendance records for a classroom session.

    WARNING: plain insert -- re-running the same session creates duplicate
    rows. Prefer :func:`create_attendance_upsert`, which is idempotent on
    ``(session_id, student_id)``. Kept for backwards compatibility.
    """
    if not logs:
        return []
    response = supabase.table("attendance_logs").insert(logs).execute()
    return response.data or []


@db_retry_write
def create_attendance_upsert(logs: List[Dict[str, Any]], session_id: str) -> List[Dict[str, Any]]:
    """Idempotently write a session's attendance logs.

    Uses ``upsert(..., on_conflict="session_id,student_id")`` backed by the
    Phase 0 migration's ``UNIQUE (session_id, student_id)`` constraint on
    ``attendance_logs``: re-submitting the same session updates the rows
    instead of duplicating them. Every log is stamped with ``session_id``
    (overriding any caller-supplied value, so logs cannot be filed under
    the wrong session). Each log must carry ``student_id`` and
    ``subject_id``.
    """
    session_id = _require_id(session_id, "session_id")
    if not logs:
        return []
    prepared: List[Dict[str, Any]] = []
    for log in logs:
        if not isinstance(log, dict):
            raise ValueError("each attendance log must be a dict")
        if not log.get("student_id") or not log.get("subject_id"):
            raise ValueError("each attendance log needs student_id and subject_id")
        row = dict(log)
        row["session_id"] = session_id
        prepared.append(row)
    response = (
        supabase.table("attendance_logs")
        .upsert(prepared, on_conflict="session_id,student_id")
        .execute()
    )
    return response.data or []


@db_retry_write
def create_session(subject_id: str, teacher_id: str, method: str) -> Dict[str, Any]:
    """Create an attendance session row and return it (with its UUID).

    The teacher must own the subject (``PermissionError`` otherwise), so a
    teacher cannot open sessions for another teacher's subject. ``method``
    must be one of ``face`` / ``voice`` / ``manual`` / ``pin``. The
    returned dict is the inserted ``attendance_sessions`` row; its
    ``session_id`` is passed to :func:`create_attendance_upsert`.
    """
    subject_id = _require_id(subject_id, "subject_id")
    teacher_id = _require_id(teacher_id, "teacher_id")
    if method not in SESSION_METHODS:
        raise ValueError(f"method must be one of {', '.join(SESSION_METHODS)}")
    _verify_subject_owner(subject_id, teacher_id)
    data = {"subject_id": subject_id, "teacher_id": teacher_id, "method": method}
    response = supabase.table("attendance_sessions").insert(data).execute()
    rows = response.data or []
    if not rows:
        raise RuntimeError("create_session: insert returned no row")
    return rows[0]


@db_retry_read()
def get_attendance_for_teacher(
    teacher_id: str, limit: int = DEFAULT_PAGE_SIZE, offset: int = 0
) -> List[Dict[str, Any]]:
    """Return ONE page of attendance records for subjects owned by a teacher.

    A single paginated query: the embedded ``subjects!inner`` join filters
    server-side to this teacher's subjects, so no subject list and no full
    log table is ever loaded client-side (the old version fetched all of
    both). Records keep their embedded ``subjects`` dict.
    """
    teacher_id = _require_id(teacher_id, "teacher_id")
    limit, offset = _validate_pagination(limit, offset)
    response = (
        supabase.table("attendance_logs")
        .select(
            "id, session_id, student_id, subject_id, timestamp, is_present, "
            "subjects!inner(subject_id, name, subject_code, teacher_id)"
        )
        .eq("subjects.teacher_id", teacher_id)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return response.data or []


# --- Ownership helpers -------------------------------------------------------
# Authorisation is enforced here, in the application layer, as well as by
# RLS in the database (defence in depth -- neither layer alone is trusted).


@db_retry_read()
def _verify_subject_owner(subject_id: str, teacher_id: str) -> None:
    """Raise PermissionError unless ``teacher_id`` owns ``subject_id``."""
    teacher_id = _require_id(teacher_id, "teacher_id")
    subject_id = _require_id(subject_id, "subject_id")
    response = (
        supabase.table("subjects")
        .select("subject_id, teacher_id")
        .eq("subject_id", subject_id)
        .eq("teacher_id", teacher_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        raise PermissionError("Subject does not exist or does not belong to this teacher")


@db_retry_read()
def _subject_id_for_log(log_id: str | int) -> str:
    """Return the subject_id of an attendance log, or raise ValueError."""
    log_id = _require_attendance_log_id(log_id)
    response = (
        supabase.table("attendance_logs")
        .select("id, session_id, subject_id")
        .eq("id", log_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        raise ValueError(f"attendance log not found: {log_id}")
    return response.data[0].get("subject_id")


@db_retry_read()
def get_session_details(
    subject_id: str, timestamp: str, *, teacher_id: str
) -> List[Dict[str, Any]]:
    """Attendance records for one session, with student names.

    ``teacher_id`` is REQUIRED (keyword-only): the subject must belong to
    that teacher, else ``PermissionError``. Explicit columns only.
    """
    subject_id = _require_id(subject_id, "subject_id")
    teacher_id = _require_id(teacher_id, "teacher_id")
    if not timestamp:
        raise ValueError("timestamp cannot be empty")
    _verify_subject_owner(subject_id, teacher_id)
    response = (
        supabase.table("attendance_logs")
        .select(
            "id, session_id, student_id, subject_id, timestamp, is_present, "
            "students(student_id, usn, name)"
        )
        .eq("subject_id", subject_id)
        .eq("timestamp", timestamp)
        .execute()
    )
    return response.data or []


@db_retry_write
def update_attendance_status(
    log_id: str | int, is_present: bool, *, teacher_id: str
) -> List[Dict[str, Any]]:
    """Update one attendance log -- only if its subject belongs to the teacher.

    ``teacher_id`` is REQUIRED (keyword-only). Raises ``PermissionError``
    for a log in another teacher's subject, ``ValueError`` if the log does
    not exist. The old version updated any log by ID with no check.
    """
    teacher_id = _require_id(teacher_id, "teacher_id")
    subject_id = _subject_id_for_log(log_id)
    _verify_subject_owner(subject_id, teacher_id)
    response = (
        supabase.table("attendance_logs")
        .update({"is_present": bool(is_present)})
        .eq("id", log_id)
        .execute()
    )
    return response.data or []


@db_retry_write
def delete_subject(subject_id: str, *, teacher_id: str) -> None:
    """Delete a subject and its relations -- only if the teacher owns it.

    ``teacher_id`` is REQUIRED (keyword-only); ``PermissionError`` otherwise.
    The deletes below run in dependency order, but they are NOT the
    transactional protection: atomicity must come from the Phase 0 SQL
    migration (``ON DELETE CASCADE`` foreign keys / a transactional RPC),
    because three sequential app-level deletes can partially fail and
    leave orphaned rows. This function requires ownership first so a
    failed / partial delete can never be triggered against another
    teacher's subject in the first place.
    """
    subject_id = _require_id(subject_id, "subject_id")
    teacher_id = _require_id(teacher_id, "teacher_id")
    _verify_subject_owner(subject_id, teacher_id)
    supabase.table("attendance_logs").delete().eq("subject_id", subject_id).execute()
    supabase.table("attendance_sessions").delete().eq("subject_id", subject_id).execute()
    supabase.table("subject_students").delete().eq("subject_id", subject_id).execute()
    supabase.table("subjects").delete().eq("subject_id", subject_id).execute()


def delete_subject_transactional(subject_id: str, *, teacher_id: str) -> Dict[str, Any]:
    """Delete a subject atomically via the ``delete_subject_tx`` RPC.

    Phase 3 (SPEC Phase 3 item 4 / audit 51): the old
    :func:`delete_subject` runs four sequential deletes, which can
    partially fail and leave orphaned rows. This function calls the
    ``delete_subject_tx(p_subject_id, p_teacher_id)`` Postgres
    function (migration 005_phase3_privacy.sql), which verifies
    ownership inside the database and deletes attendance logs,
    sessions, enrolments and the subject in ONE transaction —
    all-or-nothing. ``delete_subject`` is kept for backwards
    compatibility (and for databases where 005 has not been applied
    yet); new code — including the delete confirmation dialog — must
    use this function. Raises ``PermissionError`` when the teacher
    does not own the subject, ``RuntimeError`` when the RPC itself
    is unavailable (e.g. migration 005 not applied yet — run it
    before relying on this path). No retry: a write executes once.
    """
    subject_id = _require_id(subject_id, "subject_id")
    teacher_id = _require_id(teacher_id, "teacher_id")
    # Application-layer ownership check first (defence in depth —
    # the RPC re-checks inside the DB; neither layer alone is trusted).
    _verify_subject_owner(subject_id, teacher_id)
    try:
        response = supabase.rpc(
            "delete_subject_tx",
            {"p_subject_id": subject_id, "p_teacher_id": teacher_id},
        ).execute()
    except Exception as exc:
        raise RuntimeError(
            "delete_subject_tx RPC failed (has migration "
            "005_phase3_privacy.sql been applied?): " + str(exc)
        ) from exc
    data = response.data
    if isinstance(data, dict):
        return data
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return {"subject_id": subject_id}


# ==========================================
# Phase 1 — credential rehash write-back, voice helper, SQL counts, CSV
# ==========================================
# Transparent Argon2id migration (OWASP Password Storage Cheat Sheet:
# verify legacy hashes, then upgrade them on the next successful login):
# https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
# verify_credential() reports needs_rehash=True for legacy bcrypt and for
# Argon2id hashes whose parameters no longer match the current OWASP
# parameters; the login flows call the update_* helpers below in the
# same login flow, so the upgrade happens exactly once per account and
# never blocks the user.


def _require_argon2_hash(value: Any, label: str) -> str:
    """A hash written back by the rehash flow must be a fresh Argon2id hash.

    Accepting a bcrypt hash here would silently re-store the legacy
    format the migration exists to remove; accepting an arbitrary string
    could store a plaintext credential. Fail loudly instead.
    """
    if not isinstance(value, str) or not value.startswith("$argon2id$"):
        raise ValueError(f"{label} must be an Argon2id hash ($argon2id$...)")
    return value


@db_retry_write
def update_student_pin_hash(student_id: str, new_hash: str) -> List[Dict[str, Any]]:
    """Replace a student's stored PIN hash (transparent rehash write-back).

    Called by the PIN login flow after a successful ``verify_credential``
    that reported ``needs_rehash=True``. The caller must have already
    verified the PIN — this function performs no credential check of its
    own, it only writes the new hash.
    """
    student_id = _require_id(student_id, "student_id")
    new_hash = _require_argon2_hash(new_hash, "new pin_hash")
    response = (
        supabase.table("students")
        .update({"pin_hash": new_hash})
        .eq("student_id", student_id)
        .execute()
    )
    return response.data or []


@db_retry_write
def update_teacher_password_hash(teacher_id: str, new_hash: str) -> List[Dict[str, Any]]:
    """Replace a teacher's stored password hash (transparent rehash write-back).

    Called by the teacher login flow after a successful verification that
    reported ``needs_rehash=True``. Same contract as
    :func:`update_student_pin_hash`.
    """
    teacher_id = _require_id(teacher_id, "teacher_id")
    new_hash = _require_argon2_hash(new_hash, "new password hash")
    response = (
        supabase.table("teachers")
        .update({"password": new_hash})
        .eq("teacher_id", teacher_id)
        .execute()
    )
    return response.data or []


@db_retry_read()
def teacher_login_with_rehash(
    username: str, password: str
) -> Optional[Tuple[Dict[str, Any], bool]]:
    """Teacher login that also reports whether the stored hash needs rehashing.

    Returns ``(teacher_without_hash, needs_rehash)`` on success, ``None``
    on failure. :func:`teacher_login` is kept for backwards compatibility
    (it discards the rehash flag); new login flows must use this function
    and call :func:`update_teacher_password_hash` with
    ``hash_password(password)`` when ``needs_rehash`` is True.
    """
    username = username.strip().lower()
    response = (
        supabase.table("teachers")
        .select("teacher_id, username, password, name")
        .eq("username", username)
        .limit(1)
        .execute()
    )
    if not response.data:
        return None
    teacher = dict(response.data[0])
    stored = teacher.pop("password", "")
    ok, needs_rehash = verify_credential(password, stored)
    if not ok:
        return None
    return teacher, bool(needs_rehash)


@db_retry_write
def update_voice_embedding(student_id: str, voice_embedding: List[float]) -> List[Dict[str, Any]]:
    """Replace a student's stored voice embedding (voice re-enrolment).

    This writes the legacy ``students.voice_embedding`` column used by
    the Phase 0/1 voice dialog (Resemblyzer 256-d). The 192-d ECAPA-TDNN
    embeddings of Phase 2 live in the separate ``voice_embeddings``
    pgvector table (migration 004) and are written by the Phase 2
    worker, not here. The embedding must be a non-empty list of finite
    numbers; the caller must have re-authenticated the student (PIN)
    before calling — see ``dialog_voice_attend.voice_reenroll_dialog``.
    """
    student_id = _require_id(student_id, "student_id")
    if (
        not isinstance(voice_embedding, list)
        or not voice_embedding
        or not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))
            for x in voice_embedding
        )
    ):
        raise ValueError("voice_embedding must be a non-empty list of finite numbers")
    response = (
        supabase.table("students")
        .update({"voice_embedding": [float(x) for x in voice_embedding]})
        .eq("student_id", student_id)
        .execute()
    )
    return response.data or []


@db_retry_read()
def get_subject_by_id(subject_id: str) -> Optional[Dict[str, Any]]:
    """Fetch one subject by UUID (explicit columns; no enrolment data)."""
    subject_id = _require_id(subject_id, "subject_id")
    response = (
        supabase.table("subjects")
        .select("subject_id, subject_code, name, section, teacher_id, join_code")
        .eq("subject_id", subject_id)
        .limit(1)
        .execute()
    )
    return response.data[0] if response.data else None


# --- Phase 1: paginated / filtered Attendance Records + SQL counts ---------
# Session counts and attendance percentages come from the SQL views
# (v_session_counts / v_attendance_percentages, migration 004), never
# from loading rows into Python (Phase 0 audit 9, 23). Absences count
# only sessions on/after enrollments.enrolled_at — that rule lives in
# the view definition, not here.


@db_retry_read()
def get_attendance_records(
    teacher_id: str,
    *,
    subject_id: Optional[str] = None,
    is_present: Optional[bool] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """One page of attendance records for a teacher's subjects, filtered.

    Filters are applied server-side (PostgREST ``eq`` / ``gte`` / ``lte``
    on the embedded ``subjects!inner`` join): ``subject_id`` restricts
    to one subject, ``is_present`` to present/absent only, ``start`` /
    ``end`` to an ISO timestamp window (unparseable bounds raise
    ``ValueError`` — a caller bug, not a filter to silently drop).
    Results are newest-first. Explicit columns only; the embedded
    ``subjects`` dict keeps name / subject_code.
    """
    teacher_id = _require_id(teacher_id, "teacher_id")
    limit, offset = _validate_pagination(limit, offset)
    if subject_id is not None:
        subject_id = _require_id(subject_id, "subject_id")
    if is_present is not None and not isinstance(is_present, bool):
        raise ValueError("is_present must be a bool or None")
    if start is not None and parse_iso_timestamp(start) is None:
        raise ValueError("start must be an ISO-8601 timestamp")
    if end is not None and parse_iso_timestamp(end) is None:
        raise ValueError("end must be an ISO-8601 timestamp")

    query = (
        supabase.table("attendance_logs")
        .select(
            "id, session_id, student_id, subject_id, timestamp, is_present, "
            "subjects!inner(subject_id, name, subject_code, teacher_id), "
            "students(student_id, usn, name)"
        )
        .eq("subjects.teacher_id", teacher_id)
        .order("timestamp", desc=True)
    )
    if subject_id is not None:
        query = query.eq("subject_id", subject_id)
    if is_present is not None:
        query = query.eq("is_present", is_present)
    if start is not None:
        query = query.gte("timestamp", start)
    if end is not None:
        query = query.lte("timestamp", end)
    response = query.range(offset, offset + limit - 1).execute()
    return response.data or []


@db_retry_read()
def count_attendance_for_teacher(
    teacher_id: str,
    *,
    subject_id: Optional[str] = None,
    is_present: Optional[bool] = None,
) -> int:
    """Row count for :func:`get_attendance_records` without loading rows.

    Uses PostgREST ``count="exact"`` so the Records page can page
    through ``N`` records while fetching one page at a time.
    """
    teacher_id = _require_id(teacher_id, "teacher_id")
    if subject_id is not None:
        subject_id = _require_id(subject_id, "subject_id")
    query = (
        supabase.table("attendance_logs")
        .select("id, subjects!inner(subject_id, teacher_id)", count="exact")
        .eq("subjects.teacher_id", teacher_id)
    )
    if subject_id is not None:
        query = query.eq("subject_id", subject_id)
    if is_present is not None:
        query = query.eq("is_present", bool(is_present))
    response = query.execute()
    count = getattr(response, "count", None)
    if isinstance(count, int):
        return count
    return len(response.data or [])


@db_retry_read()
def get_session_counts(subject_id: str) -> Dict[str, Any]:
    """Session counts for one subject from the SQL view ``v_session_counts``.

    Returns ``{"total_classes": int, "first_session_at": str|None,
    "last_session_at": str|None}``; zero classes when the subject has
    no sessions yet. The count is computed in SQL, not by loading
    ``attendance_sessions`` rows.
    """
    subject_id = _require_id(subject_id, "subject_id")
    response = (
        supabase.table("v_session_counts")
        .select("subject_id, total_classes, first_session_at, last_session_at")
        .eq("subject_id", subject_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        return {
            "total_classes": 0,
            "first_session_at": None,
            "last_session_at": None,
        }
    row = response.data[0]
    return {
        "total_classes": int(row.get("total_classes") or 0),
        "first_session_at": row.get("first_session_at"),
        "last_session_at": row.get("last_session_at"),
    }


@db_retry_read()
def get_attendance_percentage(student_id: str, subject_id: str) -> Dict[str, Any]:
    """Attendance percentage for one student in one subject, from SQL.

    Reads the ``v_attendance_percentages`` view (migration 004), which
    counts only sessions on/after the student's ``enrolled_at``.
    Returns ``{"total_classes": int, "present_classes": int,
    "attendance_pct": float|None}`` (``None`` when there are no sessions
    yet — "no data", not 0%).
    """
    student_id = _require_id(student_id, "student_id")
    subject_id = _require_id(subject_id, "subject_id")
    response = (
        supabase.table("v_attendance_percentages")
        .select("student_id, subject_id, total_classes, present_classes, attendance_pct")
        .eq("student_id", student_id)
        .eq("subject_id", subject_id)
        .limit(1)
        .execute()
    )
    if not response.data:
        return {"total_classes": 0, "present_classes": 0, "attendance_pct": None}
    row = response.data[0]
    pct = row.get("attendance_pct")
    return {
        "total_classes": int(row.get("total_classes") or 0),
        "present_classes": int(row.get("present_classes") or 0),
        "attendance_pct": None if pct is None else float(pct),
    }


def iter_attendance_csv(
    teacher_id: str,
    *,
    subject_id: Optional[str] = None,
    page_size: int = 200,
) -> Any:
    """Stream attendance records for a teacher as CSV text, page by page.

    A generator: each ``yield`` is one CSV chunk (header first, then
    one chunk per page of ``page_size`` rows), so exporting thousands of
    rows never holds the whole export in memory. Rows are fetched with
    :func:`get_attendance_records` (paginated, server-side filtered).
    The ``csv`` module quotes fields, so student/subject names containing
    commas, quotes or newlines cannot break the file or inject formulas
    as raw text — values are data, never markup. ``page_size`` is capped
    at ``MAX_PAGE_SIZE``.
    """
    import csv
    import io

    teacher_id = _require_id(teacher_id, "teacher_id")
    if not isinstance(page_size, int) or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
    fieldnames = [
        "timestamp",
        "subject_code",
        "subject_name",
        "student_usn",
        "student_name",
        "is_present",
    ]
    header_buf = io.StringIO()
    csv.DictWriter(header_buf, fieldnames=fieldnames).writeheader()
    yield header_buf.getvalue()

    offset = 0
    while True:
        page = get_attendance_records(
            teacher_id, subject_id=subject_id, limit=page_size, offset=offset
        )
        if not page:
            break
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames)
        for row in page:
            subject = row.get("subjects") or {}
            student = row.get("students") or {}
            writer.writerow(
                {
                    "timestamp": row.get("timestamp") or "",
                    "subject_code": subject.get("subject_code") or "",
                    "subject_name": subject.get("name") or "",
                    "student_usn": student.get("usn") or "",
                    "student_name": student.get("name") or "",
                    "is_present": bool(row.get("is_present", False)),
                }
            )
        yield buf.getvalue()
        offset += len(page)
        if len(page) < page_size:
            break
