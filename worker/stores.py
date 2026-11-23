"""Job stores for the ML worker (Phase 2.2).

Two implementations of the same interface:

* ``PostgresJobStore`` — the real queue: rows in ``inference_jobs``
  (migrations/004_phase1_pgvector.sql), claimed with
  ``FOR UPDATE SKIP LOCKED`` (``worker/queue.py``). Used when
  ``DATABASE_URL`` is configured.
* ``MemoryJobStore`` — in-process dict, used when no database is
  configured (local dev / tests only). Jobs and payloads live only in
  memory and vanish with the process; do not use it for production.

Payloads (raw photo/audio bytes) are held in memory only, keyed by
job id, and deleted as soon as the job finishes — the worker never
writes raw media to disk (SPEC constraints).
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from worker import queue as queue_sql

__all__ = ["MemoryJobStore", "PostgresJobStore"]

JOB_TYPES = ("face", "voice")
TERMINAL = ("done", "failed")


class MemoryJobStore:
    """In-memory job + payload store (dev / tests only)."""

    def __init__(self):
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self.payloads: Dict[str, bytes] = {}

    def ping(self) -> bool:
        return True

    def create_job(self, job_type: str, *, subject_id=None,
                   candidate_ids=None, metadata=None) -> Dict[str, Any]:
        if job_type not in JOB_TYPES:
            raise ValueError(f"unknown job type: {job_type!r}")
        job_id = str(uuid.uuid4())
        job = {
            "id": job_id, "type": job_type, "status": "queued", "progress": 0,
            "result_json": {}, "error": None,
            "subject_id": subject_id, "candidate_ids": list(candidate_ids or []),
            "metadata": dict(metadata or {}),
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "expires_at": None,
        }
        self.jobs[job_id] = job
        return dict(job)

    def put_payload(self, job_id: str, payload: bytes) -> None:
        if job_id not in self.jobs:
            raise KeyError(job_id)
        self.payloads[job_id] = payload

    def take_payload(self, job_id: str) -> Optional[bytes]:
        """Take (and delete) the payload — raw media is never kept after use."""
        return self.payloads.pop(job_id, None)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self.jobs.get(job_id)
        return dict(job) if job is not None else None

    def claim_next(self) -> Optional[Dict[str, Any]]:
        for job in sorted(self.jobs.values(), key=lambda j: j["created_at"]):
            if job["status"] == "queued":
                job["status"] = "running"
                return dict(job)
        return None

    def mark_progress(self, job_id: str, progress: int) -> None:
        if job_id in self.jobs:
            self.jobs[job_id]["progress"] = max(0, min(100, int(progress)))

    def complete_job(self, job_id: str, result: Dict[str, Any]) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].update(
                {"status": "done", "progress": 100, "result_json": result})

    def fail_job(self, job_id: str, error: str) -> None:
        if job_id in self.jobs:
            self.jobs[job_id].update({"status": "failed", "error": str(error)[:500]})


class PostgresJobStore:
    """Postgres-backed job store (production).

    ``conn_factory`` returns a fresh DB-API connection per call; each
    method commits (claims included — the lock is held only for the
    claim statement itself, then the row is 'running' so no other
    worker takes it).
    """

    def __init__(self, conn_factory):
        self._conn_factory = conn_factory

    def ping(self) -> bool:
        conn = self._conn_factory()
        try:
            cur = conn.cursor()
            try:
                cur.execute("SELECT 1")
                return cur.fetchone() is not None
            finally:
                cur.close()
        finally:
            conn.close()

    def create_job(self, job_type: str, *, subject_id=None,
                   candidate_ids=None, metadata=None) -> Dict[str, Any]:
        if job_type not in JOB_TYPES:
            raise ValueError(f"unknown job type: {job_type!r}")
        conn = self._conn_factory()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO inference_jobs (type, status, progress, result_json) "
                    "VALUES (%s, 'queued', 0, '{}'::jsonb) RETURNING id",
                    (job_type,),
                )
                row = cur.fetchone()
                job_id = row[0] if isinstance(row, (list, tuple)) else row["id"]
            finally:
                cur.close()
            conn.commit()
        finally:
            conn.close()
        return {"id": str(job_id), "type": job_type, "status": "queued",
                "progress": 0, "result_json": {}, "error": None,
                "subject_id": subject_id,
                "candidate_ids": list(candidate_ids or []),
                "metadata": dict(metadata or {})}

    def put_payload(self, job_id: str, payload: bytes) -> None:
        # Postgres store does not persist payloads: the submitting
        # process keeps them in memory (see worker/app.py). Persisting
        # raw photos/audio in the DB would violate the "never keep raw
        # media" constraint. Multi-replica deployments must front the
        # worker with shared ephemeral storage; single-replica keeps
        # the in-memory payload dict in app.py.
        raise NotImplementedError(
            "PostgresJobStore does not persist payloads; use the app-level "
            "in-memory payload cache (single replica) or shared ephemeral "
            "storage (multi-replica).")

    def take_payload(self, job_id: str) -> Optional[bytes]:
        return None

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        conn = self._conn_factory()
        try:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT id, type, status, progress, result_json, error, "
                    "created_at, expires_at FROM inference_jobs WHERE id = %s",
                    (job_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                cols = [d[0] for d in cur.description]
                return (
                    dict(zip(cols, row, strict=False))
                    if not isinstance(row, dict)
                    else dict(row)
                )
            finally:
                cur.close()
        finally:
            conn.close()

    def claim_next(self) -> Optional[Dict[str, Any]]:
        conn = self._conn_factory()
        try:
            job = queue_sql.claim_next_job(conn)
            conn.commit()
            return job
        finally:
            conn.close()

    def mark_progress(self, job_id: str, progress: int) -> None:
        conn = self._conn_factory()
        try:
            queue_sql.mark_progress(conn, job_id, progress)
            conn.commit()
        finally:
            conn.close()

    def complete_job(self, job_id: str, result: Dict[str, Any]) -> None:
        conn = self._conn_factory()
        try:
            queue_sql.complete_job(conn, job_id, result)
            conn.commit()
        finally:
            conn.close()

    def fail_job(self, job_id: str, error: str) -> None:
        conn = self._conn_factory()
        try:
            queue_sql.fail_job(conn, job_id, error)
            conn.commit()
        finally:
            conn.close()
