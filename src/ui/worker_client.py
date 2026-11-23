"""Streamlit-side client for the Phase 2 FastAPI ML worker.

The Streamlit UI never runs ML itself (no torch / dlib / onnxruntime /
pyannote in the UI image — see ``Dockerfile.ui``). It submits a job to
the worker (``POST /jobs``) and polls ``GET /jobs/{id}`` from an
``@st.fragment`` (``src/ui/fragments.py``), so polling reruns only the
fragment, not the whole page.

Configuration: ``ML_WORKER_URL`` — from ``st.secrets["ML_WORKER_URL"]``
when present, else the ``ML_WORKER_URL`` environment variable, else
``None`` (worker disabled → the caller falls back to the legacy
in-process pipeline). No credentials are sent: the worker trusts only
requests from the UI host's network (see ``worker/README.md``); the
Supabase ``service_role`` key lives in the worker only, never here.

Transport is stdlib ``urllib`` with explicit timeouts (no extra
dependency, no ``httpx`` client to configure). ``http_post`` /
``http_get`` callables can be injected for tests.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

__all__ = ["WorkerClient", "get_worker_client", "WORKER_JOB_TYPES"]

# Must match the ``type`` CHECK in migrations/004_phase1_pgvector.sql
# (inference_jobs.type) and the worker's validation.
WORKER_JOB_TYPES = ("face", "voice")

DEFAULT_TIMEOUT_SECONDS = 10.0
POLL_TIMEOUT_SECONDS = 5.0


# NOTE (S310): the URL comes from the deployment-configured worker base_url,
# never from user input; worker URLs are http(s) only in practice.
def _default_post(url: str, payload: bytes, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")  # noqa: S310
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _default_get(url: str, timeout: float) -> dict:
    req = urllib.request.Request(url, method="GET")  # noqa: S310
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


class WorkerClient:
    """Minimal client for the ML worker's job API.

    ``base_url`` like ``http://ml-worker:8000`` (no trailing slash).
    All methods return plain dicts and raise ``WorkerError`` on
    transport / HTTP / malformed-response failures — the UI turns those
    into a generic message, never a stack trace.
    """

    def __init__(self, base_url: str, *,
                 http_post: Optional[Callable] = None,
                 http_get: Optional[Callable] = None,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http_post = http_post or _default_post
        self._http_get = http_get or _default_get

    # -- health ---------------------------------------------------------
    def health(self) -> dict:
        """``GET /healthz`` — liveness (process up?)."""
        return self._http_get(f"{self.base_url}/healthz", self.timeout)

    def ready(self) -> dict:
        """``GET /readyz`` — readiness (models loaded, DB reachable?)."""
        return self._http_get(f"{self.base_url}/readyz", self.timeout)

    # -- jobs -----------------------------------------------------------
    def submit_job(self, job_type: str, *, subject_id: Optional[str] = None,
                   candidate_ids: Optional[List[str]] = None,
                   payload_b64: Optional[str] = None,
                   metadata: Optional[dict] = None) -> dict:
        """``POST /jobs`` — returns the created job (``{"id", "status", ...}``).

        ``payload_b64`` is base64 image/audio bytes. Raw photos/audio
        are sent to the worker in memory only; the worker never writes
        them to disk (see ``worker/README.md``).
        """
        if job_type not in WORKER_JOB_TYPES:
            raise ValueError(f"unknown job type: {job_type!r} (want {WORKER_JOB_TYPES})")
        body = {
            "type": job_type,
            "subject_id": subject_id,
            "candidate_ids": candidate_ids or [],
            "payload_b64": payload_b64,
            "metadata": metadata or {},
        }
        try:
            return self._http_post(
                f"{self.base_url}/jobs",
                json.dumps(body).encode("utf-8"),
                {"Content-Type": "application/json"},
                self.timeout,
            )
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.warning("ML worker submit failed: %s", exc)
            raise WorkerError(f"ML worker unreachable at {self.base_url}") from exc

    def get_job(self, job_id: str) -> dict:
        """``GET /jobs/{id}`` — ``{"id","status","progress","result","error"}``."""
        try:
            return self._http_get(
                f"{self.base_url}/jobs/{job_id}", POLL_TIMEOUT_SECONDS
            )
        except (urllib.error.URLError, OSError, ValueError) as exc:
            logger.warning("ML worker poll failed for job %s: %s", job_id, exc)
            raise WorkerError("ML worker unreachable while polling job") from exc


class WorkerError(Exception):
    """Worker unreachable / bad response. UI shows a generic message."""


def get_worker_client() -> Optional[WorkerClient]:
    """Build a client from config, or ``None`` when the worker is not
    configured (caller falls back to the legacy in-process pipeline).

    Reads ``st.secrets["ML_WORKER_URL"]`` first, then the
    ``ML_WORKER_URL`` environment variable. Importing streamlit here is
    safe (the UI always has it); the function degrades to env-only
    when secrets are unavailable.
    """
    url: Optional[str] = None
    try:
        import streamlit as st  # local import: keeps this module importable in tests
        try:
            url = st.secrets.get("ML_WORKER_URL")  # type: ignore[attr-defined]
        except Exception:
            url = None
    except Exception:
        url = None
    url = url or os.environ.get("ML_WORKER_URL")
    if not url:
        return None
    return WorkerClient(str(url))
