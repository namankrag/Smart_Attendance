"""Database call facade that uses FastAPI when DATA_API_URL is configured."""

from __future__ import annotations

from functools import wraps
from typing import Any

from src.database import db as _local_db
from src.database import privacy as _local_privacy
from src.database import vector as _local_vector
from src.ui.data_api import (
    call_database as _call_database,
    authenticate_student as _authenticate_student,
    authenticate_teacher as _authenticate_teacher,
    data_api_url,
    enroll_student_by_usn as _enroll_student_by_usn,
    join_subject_by_code as _join_subject_by_code,
    leave_subject as _leave_subject,
    lookup_subject_by_join_code as _lookup_subject_by_join_code,
)

_MODULES = {
    "db": _local_db,
    "privacy": _local_privacy,
    "vector": _local_vector,
}
_FUNCTIONS = {
    name: module_name
    for module_name, module in _MODULES.items()
    for name in module.__all__
    if callable(getattr(module, name, None))
}
__all__ = [
    *[name for module in _MODULES.values() for name in module.__all__],
    "lookup_subject_by_join_code",
    "join_subject_by_code",
    "leave_subject",
    "authenticate_student",
    "authenticate_teacher",
    "enroll_student_by_usn",
]

_REMOTE_WRAPPERS = {}
_LOCAL_ONLY = {"check_pass", "hash_pass", "cosine_similarity"}


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(name)
    module_name = _FUNCTIONS.get(name)
    if module_name is None:
        for module in _MODULES.values():
            if name in getattr(module, "__all__", ()):
                return getattr(module, name)
        raise AttributeError(name)
    if name not in _REMOTE_WRAPPERS:
        local = getattr(_MODULES[module_name], name)

        @wraps(local)
        def call(*args: Any, **kwargs: Any):
            if not data_api_url() or name in _LOCAL_ONLY:
                return local(*args, **kwargs)
            result = _call_database(module_name, name, args, kwargs)
            if name == "iter_attendance_csv":
                return iter(result or [])
            return result

        _REMOTE_WRAPPERS[name] = call
    return _REMOTE_WRAPPERS[name]


def lookup_subject_by_join_code(join_code: str):
    if data_api_url():
        return _lookup_subject_by_join_code(join_code)
    return _local_db.get_subject_by_join_code(join_code)


def join_subject_by_code(join_code: str):
    if data_api_url():
        return _join_subject_by_code(join_code)
    return _local_db.enroll_student_by_join_code(join_code)


def leave_subject(subject_id: str):
    if data_api_url():
        return _leave_subject(subject_id)
    import streamlit as st

    return _local_db.unenroll_student_to_subject(
        st.session_state.student_data["student_id"], subject_id
    )


def enroll_student_by_usn(subject_id: str, usn: str):
    if data_api_url():
        return _enroll_student_by_usn(subject_id, usn)
    student = _local_db.get_student_for_login(usn)
    if not student:
        return None
    return _local_db.enroll_student_to_subject(student["student_id"], subject_id)


def authenticate_student(identifier: str, pin: str):
    return _authenticate_student(identifier, pin)


def authenticate_teacher(username: str, password: str):
    return _authenticate_teacher(username, password)
