"""Student auth + session helpers (Phase 2 split of ``student_screen``).

Moved verbatim from ``src/screen/student_screen.py`` (Phase 2.1):
session helpers, PIN/face-login helpers, and the shared login
constants. ``student_screen`` re-exports everything here, so existing
imports keep working. Login is 1:1 only and fail-closed — see the
original module docstring, which still applies.
"""
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
from PIL import Image

from src.database.timeutil import parse_iso_timestamp

try:
    from src.database.db import (
        get_student_for_login,
        check_login_allowed,
        record_login_attempt,
    )
except ImportError:  # pragma: no cover - db agent has not landed yet
    get_student_for_login = None  # type: ignore[assignment]
    check_login_allowed = None  # type: ignore[assignment]
    record_login_attempt = None  # type: ignore[assignment]

try:
    from src.database.auth import verify_credential, validate_pin, hash_pin
except ImportError:  # pragma: no cover - auth module has not landed yet
    verify_credential = None  # type: ignore[assignment]
    validate_pin = None  # type: ignore[assignment]
    hash_pin = None  # type: ignore[assignment]

try:
    from src.database.db import update_student_pin_hash
except ImportError:  # pragma: no cover
    update_student_pin_hash = None  # type: ignore[assignment]

try:
    from src.pipelines.face_pipeline import predict_one_to_one
except ImportError:  # pragma: no cover
    predict_one_to_one = None  # type: ignore[assignment]

try:
    from src.pipelines.face_pipeline import verify_face_1to1
except ImportError:  # pragma: no cover
    verify_face_1to1 = None  # type: ignore[assignment]

try:
    from src.pipelines.face_pipeline import find_duplicate_face_owner
except ImportError:  # pragma: no cover
    try:
        from src.database.db import find_duplicate_face_owner  # type: ignore[assignment]
    except ImportError:
        find_duplicate_face_owner = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Honest liveness claim (Phase 0 item 12). Do not restore the old
# "strictly rejected" wording: it overstates what the heuristic checks do.
LIVENESS_NOTE = (
    "Liveness checks are heuristic only; printed-photo/replay blocking is "
    "not guaranteed until Phase 2 PAD is deployed and evaluated."
)
GENERIC_LOGIN_ERROR = "Invalid credentials."
GENERIC_LOCKOUT_ERROR = "Too many failed attempts. Please try again later."
REG_VALIDATED_FRAME_KEY = "smartclass_reg_validated_frame"
FACE_UPDATE_REAUTH_KEY = "smartclass_face_update_reauthenticated"



# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------
def _public_student_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return only the fields the session may hold.

    Never ``pin_hash``, ``face_embedding`` or ``voice_embedding``.
    """
    return {
        "student_id": str(record["student_id"]),
        "usn": record.get("usn"),
        "name": record.get("name"),
    }


def _set_student_session(record: Dict[str, Any]) -> None:
    st.session_state.camera_active = False
    st.session_state.is_logged_in = True
    st.session_state.user_role = "student"
    st.session_state.student_data = _public_student_record(record)


def clear_student_session() -> None:
    """Clear every student-namespaced session key on logout."""
    for key in list(st.session_state.keys()):
        if (
            key in {
                "student_data",
                "login_type",
                "camera_active",
                "is_logged_in",
                "user_role",
                "show_student_reg",
            }
            or key.startswith("smartclass_")
            or key.startswith("reg_")
            or key.startswith("login_pin_")
            or key.startswith("login_face")
            or key.startswith("modal_face_update")
        ):
            st.session_state.pop(key, None)
    st.session_state["login_type"] = None
    st.session_state["is_logged_in"] = False
    # Phase 1: end the Google session too, when Streamlit supports it.
    logout = getattr(st, "logout", None)
    if callable(logout):
        logout()


# ---------------------------------------------------------------------------
# Auth helpers (fail closed when a Phase 0 collaborator is missing)
# ---------------------------------------------------------------------------
def _login_allowed(identifier: str, kind: str) -> Tuple[bool, Optional[Any]]:
    if check_login_allowed is None:
        logger.error("check_login_allowed is unavailable; refusing login")
        return False, None
    try:
        result = check_login_allowed(identifier, kind=kind)
    except TypeError:
        result = check_login_allowed(identifier)
    if isinstance(result, tuple):
        return bool(result[0]), (result[1] if len(result) > 1 else None)
    if isinstance(result, dict):
        return bool(result.get("allowed", False)), result.get("retry_after_seconds")
    return bool(result), None


def _record_login_attempt(identifier: str, success: bool, kind: str) -> None:
    if record_login_attempt is None:
        logger.warning("record_login_attempt is unavailable; attempt not recorded")
        return
    record_login_attempt(identifier, kind=kind, success=success)


def _validate_pin(pin: str) -> Tuple[bool, Optional[str]]:
    """Validate a PIN as 4-6 digits.

    ``src.database.auth.validate_pin`` is authoritative when present; the
    local check below is only the same format rule, not a credential check.
    """
    if validate_pin is not None:
        try:
            result = validate_pin(pin)
        except ValueError as exc:
            return False, str(exc)
        if isinstance(result, tuple):
            return bool(result[0]), (result[1] if len(result) > 1 else None)
        if isinstance(result, dict):
            return bool(result.get("valid", False)), result.get("error")
        return bool(result), None if result else "PIN must be 4-6 digits."
    return (True, None) if re.fullmatch(r"\d{4,6}", pin or "") else (
        False,
        "PIN must be 4-6 digits.",
    )


def _verify_pin(pin: str, pin_hash: str) -> Tuple[bool, bool]:
    """Verify a PIN. Returns (ok, needs_rehash). Fails closed if missing."""
    if verify_credential is None:
        logger.error("verify_credential is unavailable; refusing PIN login")
        return False, False
    result = verify_credential(pin, pin_hash)
    if isinstance(result, tuple):
        return bool(result[0]), bool(result[1]) if len(result) > 1 else False
    if isinstance(result, dict):
        return bool(result.get("ok", False)), bool(result.get("needs_rehash", False))
    return bool(result), False


def _lookup_student_for_login(identifier: str) -> Optional[Dict[str, Any]]:
    if get_student_for_login is None:
        logger.error("get_student_for_login is unavailable; refusing login")
        return None
    return get_student_for_login(identifier)


def _verify_face_1to1(
    img: Image.Image, student: Dict[str, Any]
) -> Tuple[bool, Optional[int]]:
    """Verify ``img`` against ONLY ``student``'s template.

    Assumed pipeline contract (pipeline agent to confirm):
    ``predict_one_to_one(image, student_id, distance_threshold=...,
    num_jitters=..., is_single_face=...)`` returning a bool, a
    ``(matched, num_faces)`` tuple, or a dict with a ``matched`` /
    ``is_match`` / ``verified`` key. ``verify_face_1to1`` is the alternate
    name for the same check and is tried only if ``predict_one_to_one``
    is unavailable. Never falls back to 1:N ``predict_attendance``.
    """
    student_id = student.get("student_id")
    fn = predict_one_to_one if predict_one_to_one is not None else verify_face_1to1
    if fn is None:
        logger.error("No 1:1 face verification function is available; refusing face login")
        return False, None
    kwargs = {
        "distance_threshold": 0.38,
        "num_jitters": 2,
        "is_single_face": True,
    }
    # Reuse the profile already fetched for this login attempt. This keeps
    # verification scoped to the exact claimed row and avoids a second DB read.
    if "face_embedding" in student:
        kwargs["gallery_embeddings"] = student.get("face_embedding")
    try:
        result = fn(img, student_id, **kwargs)
    except TypeError:
        result = fn(img, student_id)
    if isinstance(result, bool):
        return result, None
    if isinstance(result, tuple) and result:
        matched = bool(result[0])
        num_faces = result[1] if len(result) > 1 and isinstance(result[1], int) else None
        return matched, num_faces
    if isinstance(result, dict):
        matched = bool(
            result.get("matched", result.get("is_match", result.get("verified", False)))
        )
        num_faces = result.get("num_faces")
        return matched, num_faces if isinstance(num_faces, int) else None
    return bool(result), None


def _find_duplicate_owner(face_embedding: List[float]) -> Optional[Dict[str, Any]]:
    """Return the existing student owning this face, or None.

    Assumed contract: ``find_duplicate_face_owner(embedding)`` returns
    None, a student dict (``student_id`` / ``usn`` / ``name``), a
    ``(student_id, ...)`` tuple, or a bare student id.
    """
    if find_duplicate_face_owner is None:
        logger.warning("find_duplicate_face_owner is unavailable; duplicate-face check skipped")
        return None
    result = find_duplicate_face_owner(face_embedding)
    if result is None:
        return None
    if isinstance(result, dict):
        return result
    if isinstance(result, (tuple, list)) and result:
        return {"student_id": result[0]}
    return {"student_id": result}


def _parse_ts(value: Any) -> Optional[datetime]:
    """Parse an ISO timestamp; ``None`` for anything unparseable.

    Delegates to the shared Phase 1 helper
    (``src.database.timeutil.parse_iso_timestamp``) — one parser for
    the whole app, never raising on bad input (audit 30).
    """
    return parse_iso_timestamp(value)


