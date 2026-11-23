"""``@st.fragment``-wrapped UI pieces (Phase 2.1).

Streamlit fragments rerun independently of the rest of the page, so a
job-progress poller or a table no longer forces a full-page rerun on
every poll / interaction:

* ``job_progress_fragment`` — polls ``GET /jobs/{id}`` on the worker
  every few seconds (``run_every``) and renders progress; when the job
  reaches a terminal state it stores the result in session state and
  asks the page to rerun once, so the caller can render the result
  dialog/table. Polling stops as soon as the job is done/failed.
* ``records_table_fragment`` — renders a (paginated) dataframe; table
  interactions rerun only the fragment.

Fragment rules honoured here: fragments never call
``st.set_page_config``, never open dialogs themselves, and never
``time.sleep`` — polling uses the fragment's ``run_every`` timer.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import streamlit as st

from src.ui.worker_client import WorkerClient, WorkerError

logger = logging.getLogger(__name__)

__all__ = [
    "job_progress_fragment",
    "poll_pending_jobs_fragment",
    "records_table_fragment",
    "PENDING_JOB_KEY",
    "JOB_RESULT_KEY",
]

# Session keys for the async worker flow (teacher take-attendance).
PENDING_JOB_KEY = "smartclass_pending_job"
JOB_RESULT_KEY = "smartclass_job_result"


@st.fragment(run_every="3s")
def job_progress_fragment(client: WorkerClient, job_id: str) -> None:
    """Poll one worker job and render its progress.

    Terminal states (``done`` / ``failed``): the result (or error) is
    stored under ``JOB_RESULT_KEY``, the pending entry is cleared, and
    ``st.rerun`` is called once so the calling page renders the
    result. Non-terminal: just render the progress bar; the fragment
    reruns itself on its ``run_every`` timer.
    """
    try:
        job = client.get_job(job_id)
    except WorkerError:
        st.warning("Waiting for the ML worker… (poll failed, retrying)")
        return
    status = str(job.get("status", "unknown"))
    progress = int(job.get("progress") or 0)
    st.progress(min(100, max(0, progress)), text=f"ML worker: {status} ({progress}%)")
    if status in ("done", "failed"):
        st.session_state[JOB_RESULT_KEY] = job
        st.session_state.pop(PENDING_JOB_KEY, None)
        st.rerun()
    elif status not in ("queued", "running"):
        logger.warning("ML worker returned unknown job status %r for %s", status, job_id)
        st.warning(f"ML worker returned an unexpected job status: {status}")


@st.fragment(run_every="3s")
def poll_pending_jobs_fragment(client: WorkerClient) -> None:
    """Poll every pending worker job for the current attendance run.

    Reads the pending entry (``PENDING_JOB_KEY``: ``{"job_ids",
    "subject_id", "subject_label"}``), polls each job, and renders one
    progress bar per job. When ALL jobs are terminal, their detected
    sets are merged into ``JOB_RESULT_KEY`` (with the subject context
    the page needs to render the result), the pending entry is cleared,
    and the page reruns once. A failed job marks the whole result
    failed (the page shows a generic error and the teacher can retry
    or use the legacy path).
    """
    pending = st.session_state.get(PENDING_JOB_KEY)
    if not pending:
        return
    job_ids = list(pending.get("job_ids") or [])
    if not job_ids:
        st.session_state.pop(PENDING_JOB_KEY, None)
        return
    jobs = []
    for job_id in job_ids:
        try:
            jobs.append(client.get_job(job_id))
        except WorkerError:
            st.warning("Waiting for the ML worker… (poll failed, retrying)")
            return
    done = [j for j in jobs if str(j.get("status")) in ("done", "failed")]
    total_progress = sum(int(j.get("progress") or 0) for j in jobs) // max(len(jobs), 1)
    st.progress(
        min(100, max(0, total_progress)),
        text=f"ML worker: {len(done)}/{len(jobs)} photo(s) analyzed",
    )
    if len(done) < len(jobs):
        return
    failed = [j for j in jobs if str(j.get("status")) == "failed"]
    if failed:
        st.session_state[JOB_RESULT_KEY] = {
            "status": "failed",
            "error": failed[0].get("error") or "ML worker job failed",
            "subject_id": pending.get("subject_id"),
            "subject_label": pending.get("subject_label"),
        }
    else:
        merged: Dict[str, Any] = {}
        for job in jobs:
            for sid, info in ((job.get("result") or {}).get("detected") or {}).items():
                merged[str(sid)] = info
        st.session_state[JOB_RESULT_KEY] = {
            "status": "done",
            "result": {"detected": merged},
            "subject_id": pending.get("subject_id"),
            "subject_label": pending.get("subject_label"),
        }
    st.session_state.pop(PENDING_JOB_KEY, None)
    st.rerun()


@st.fragment
def records_table_fragment(df, *, key: str = "records_table") -> None:
    """Render a dataframe inside a fragment so table interactions
    (sorting, scrolling) rerun only the fragment, not the whole page."""
    st.dataframe(df, width="stretch", key=key)
