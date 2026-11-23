"""Postgres job queue (Phase 2.2).

The worker queue is Postgres itself — no Redis dependency by default.
Workers claim jobs with ``FOR UPDATE SKIP LOCKED`` so several worker
replicas can run safely: a claimed row is locked by exactly one
worker, and contenders skip it instead of blocking.

Table: ``inference_jobs`` (migrations/004_phase1_pgvector.sql):
``id uuid, type ('face'|'voice'), status ('queued'|'running'|'done'|
'failed'), progress 0-100, result_json jsonb, error text, created_at,
expires_at``. Streamlit only inserts a row and polls; only the worker
claims and completes jobs.

This module is transport-free: functions take a DB-API connection
(``conn.cursor()`` protocol) so they are unit-testable with a fake
connection and usable with any Postgres driver (psycopg / pg8000).
No SQL is built from user input — job ids are bound parameters.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

__all__ = [
    "CLAIM_JOB_SQL",
    "UPDATE_PROGRESS_SQL",
    "COMPLETE_JOB_SQL",
    "FAIL_JOB_SQL",
    "claim_next_job",
    "mark_progress",
    "complete_job",
    "fail_job",
]

# Claim the oldest queued job, locking it so no other worker takes it.
# FOR UPDATE SKIP LOCKED: contenders skip locked rows instead of
# waiting — this is what makes multi-replica workers safe without Redis.
CLAIM_JOB_SQL = """
UPDATE inference_jobs SET status = 'running'
WHERE id = (
  SELECT id FROM inference_jobs
  WHERE status = 'queued'
  ORDER BY created_at ASC
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING id, type, status, progress, result_json, error, created_at, expires_at
"""

UPDATE_PROGRESS_SQL = (
    "UPDATE inference_jobs SET progress = %s WHERE id = %s"
)

COMPLETE_JOB_SQL = (
    "UPDATE inference_jobs SET status = 'done', progress = 100, "
    "result_json = %s WHERE id = %s"
)

FAIL_JOB_SQL = (
    "UPDATE inference_jobs SET status = 'failed', error = %s WHERE id = %s"
)


def _row_to_dict(row: Any, cursor: Any) -> Dict[str, Any]:
    cols = [d[0] for d in cursor.description] if cursor.description else []
    if isinstance(row, dict):
        return dict(row)
    return {c: v for c, v in zip(cols, row, strict=False)}


def claim_next_job(conn: Any) -> Optional[Dict[str, Any]]:
    """Atomically claim the oldest queued job, or ``None`` if the queue
    is empty. The returned dict is the claimed row (status 'running').

    Callers must commit the connection afterwards (the UPDATE + lock
    live in the caller's transaction). On DB error the exception
    propagates — a failed claim must never be mistaken for an empty queue.
    """
    cur = conn.cursor()
    try:
        cur.execute(CLAIM_JOB_SQL)
        row = cur.fetchone()
        if row is None:
            return None
        return _row_to_dict(row, cur)
    finally:
        cur.close()


def mark_progress(conn: Any, job_id: str, progress: int) -> None:
    """Set ``progress`` (0-100, clamped) on a running job."""
    progress = max(0, min(100, int(progress)))
    cur = conn.cursor()
    try:
        cur.execute(UPDATE_PROGRESS_SQL, (progress, job_id))
    finally:
        cur.close()


def complete_job(conn: Any, job_id: str, result: Dict[str, Any]) -> None:
    """Mark a job ``done`` with its JSON result."""
    cur = conn.cursor()
    try:
        cur.execute(COMPLETE_JOB_SQL, (json.dumps(result), job_id))
    finally:
        cur.close()


def fail_job(conn: Any, job_id: str, error: str) -> None:
    """Mark a job ``failed`` with a (generic, non-sensitive) error string.

    Never store stack traces or secrets in ``error`` — the UI may show
    it to the teacher.
    """
    cur = conn.cursor()
    try:
        cur.execute(FAIL_JOB_SQL, (str(error)[:500], job_id))
    finally:
        cur.close()
