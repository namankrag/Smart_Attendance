"""Teacher take-attendance worker jobs (Phase 2 split of ``teacher_screen``).

* ``submit_face_jobs`` — submit staged group photos to the ML worker
  (one ``face`` job per photo) instead of running detection in the
  Streamlit process.
* ``present_attendance_result`` — build the present/absent result rows
  from detected ids and open the result dialog (moved verbatim from
  ``take_attendance`` so both the worker path and the legacy path
  share it).
* ``render_completed_worker_job`` — when the poller fragment reports
  finished jobs, load the roster once more and render the result.

Fallback rule: any worker failure (unreachable, submit error, job
failed) falls back to the legacy in-process pipeline in
``teacher_screen`` — the teacher still gets attendance, and the
fallback is logged. The worker path is preferred when configured,
never required.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime
from typing import Any, Dict, List

import pandas as pd
import streamlit as st

from src.components.dialog_attend_result import attend_result
from src.ui.fragments import JOB_RESULT_KEY
from src.ui.worker_client import WorkerClient

try:
    from src.database.db import get_enrolled_students
except ImportError:  # pragma: no cover
    get_enrolled_students = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

ENROLLED_PAGE_SIZE = 500

__all__ = [
    "submit_face_jobs",
    "present_attendance_result",
    "render_completed_worker_job",
]


def _paginated(fn, *args, limit: int, offset: int = 0, **kwargs):
    """Call a db function with limit/offset; fall back to the unpaginated
    signature only if the db layer has not landed the paginated form yet."""
    try:
        return fn(*args, limit=limit, offset=offset, **kwargs)
    except TypeError:
        logger.warning("%s has no limit/offset parameters yet", getattr(fn, "__name__", fn))
        return fn(*args, **kwargs)


def _student_from_enrollment_node(node: Dict[str, Any]) -> Dict[str, Any]:
    """Enrolled-student rows may be nested (``{"students": {...}}``) or flat."""
    nested = node.get("students")
    if isinstance(nested, dict):
        return nested
    return node


def submit_face_jobs(client: WorkerClient, staged_bytes: Dict[str, bytes],
                     subject_id: str, candidate_ids: List[str]) -> List[str]:
    """Submit one ``face`` job per staged photo. Returns job ids.

    Raises :class:`WorkerError` when the worker cannot be reached —
    the caller falls back to the legacy in-process pipeline.
    """
    job_ids: List[str] = []
    for sha256, img_bytes in staged_bytes.items():
        job = client.submit_job(
            "face",
            subject_id=subject_id,
            candidate_ids=candidate_ids,
            payload_b64=base64.b64encode(img_bytes).decode("ascii"),
            metadata={"sha256": sha256},
        )
        job_ids.append(str(job["id"]))
    return job_ids


def present_attendance_result(enrolled_stud: List[Dict[str, Any]],
                              all_detected_ids: Dict[Any, List[str]],
                              selected_sub_id: str, selected_label: str) -> None:
    """Build present/absent rows from detected ids and open the result dialog.

    ``all_detected_ids`` maps student id -> list of sources
    (e.g. ``["Photo 1"]`` or ``["ML worker"]``).
    """
    res_rows, attend_logs = [], []
    current_timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    for node in enrolled_stud:
        stud = _student_from_enrollment_node(node)
        if not stud:
            continue
        sid = stud["student_id"]
        sources = all_detected_ids.get(sid, []) or all_detected_ids.get(str(sid), [])
        is_present = len(sources) > 0

        res_rows.append({
            "Name": stud["name"],
            "ID": sid,
            "Source": ", ".join(sources) if is_present else "-",
            "Status": "✅ Present" if is_present else "❌ Absent"
        })
        attend_logs.append({
            "student_id": sid,
            "subject_id": selected_sub_id,
            "timestamp": current_timestamp,
            "is_present": is_present
        })
    attend_result(pd.DataFrame(res_rows), attend_logs, subject_name=selected_label)


def render_completed_worker_job(selected_sub_id: str, selected_label: str) -> bool:
    """Render a finished worker job's result (if one is pending).

    Returns True when a result was rendered (or an error shown).
    The completed result is popped from session state exactly once.
    """
    result = st.session_state.pop(JOB_RESULT_KEY, None)
    if not result:
        return False
    if result.get("status") == "failed" or result.get("error"):
        logger.warning("ML worker job failed: %s", result.get("error"))
        st.error("The ML worker could not analyze the photos. Please try again.")
        return True
    detected = (result.get("result") or {}).get("detected") or {}
    if get_enrolled_students is None:
        logger.error("get_enrolled_students is unavailable")
        st.error("Could not load enrolled students. Please try again.")
        return True
    try:
        enrolled_stud = _paginated(
            get_enrolled_students, selected_sub_id,
            limit=ENROLLED_PAGE_SIZE, offset=0)
    except Exception:
        logger.exception("Failed to load enrolled students")
        st.error("Could not load enrolled students. Please try again.")
        return True
    if not enrolled_stud:
        st.warning("⚠️ No students enrolled in this course!")
        return True
    detected_sources = {sid: ["ML worker"] for sid in detected}
    present_attendance_result(enrolled_stud, detected_sources,
                              selected_sub_id, selected_label)
    return True
