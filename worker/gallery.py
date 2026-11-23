"""Roster template loading for the worker (Phase 2.2).

The worker — and ONLY the worker — may use the Supabase
``service_role`` key (from the worker environment) to read templates.
The Streamlit UI never sees this key (SPEC Phase 0 item 8) and reads
only through RLS with the user's JWT.

Templates are read from the Phase 1 ``face_embeddings`` /
``voice_embeddings`` tables (512-d face, 192-d voice, normalised) with
explicit column lists — never ``SELECT *``. Only the enrolled roster
of the job's subject is loaded, never the whole table.
"""

from __future__ import annotations

import logging
from typing import Dict, List

import numpy as np

logger = logging.getLogger(__name__)

__all__ = ["GalleryLoader"]


class GalleryLoader:
    """Loads enrolled-roster templates via the worker's service_role client.

    Phase 3: every template read is audited. ``on_template_access``
    is an optional callback ``fn(event: dict)`` invoked on each
    gallery load with identifiers + counts only (subject_id,
    template kind, number of students loaded — NEVER a vector).
    The worker app wires it to an audit_log insert (see
    ``worker/app.py``); when no callback is given the load is still
    recorded in the structured log. A failing callback never breaks
    the load.
    """

    def __init__(self, config, client=None, on_template_access=None):
        self.config = config
        self._client = client
        self._on_template_access = on_template_access

    def _audit(self, template_kind: str, subject_id: str, count: int) -> None:
        event = {
            "template_kind": template_kind,
            "access": "gallery_load",
            "subject_id": subject_id,
            "students_loaded": count,
        }
        if callable(self._on_template_access):
            try:
                self._on_template_access(event)
            except Exception:
                logger.exception("template-access audit callback failed")
        else:
            logger.info("template access: %s", event)

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if not self.config.supabase_url or not self.config.supabase_service_role_key:
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set in the "
                "worker environment; the worker cannot load galleries. "
                "These keys live in the worker host only — never in Streamlit."
            )
        try:
            from supabase import create_client
        except ImportError as exc:
            raise RuntimeError("supabase client is not installed in the worker image") from exc
        self._client = create_client(
            self.config.supabase_url, self.config.supabase_service_role_key)
        return self._client

    def _enrolled_ids(self, subject_id: str) -> List[str]:
        client = self._ensure_client()
        resp = client.table("subject_students").select("student_id").eq(
            "subject_id", subject_id).execute()
        return [str(r["student_id"]) for r in (resp.data or [])]

    def load_face_gallery(self, subject_id: str) -> Dict[str, List[np.ndarray]]:
        """{student_id: [512-d normalised embeddings]} for the roster."""
        client = self._ensure_client()
        ids = self._enrolled_ids(subject_id)
        gallery: Dict[str, List[np.ndarray]] = {}
        if not ids:
            return gallery
        resp = client.table("face_embeddings").select(
            "student_id, vector").in_("student_id", ids).execute()
        for row in resp.data or []:
            vec = np.asarray(row.get("vector"), dtype=np.float32).ravel()
            if vec.shape[0] != 512:
                logger.warning("face embedding for %s is %d-d, skipping",
                               row.get("student_id"), vec.shape[0])
                continue
            gallery.setdefault(str(row["student_id"]), []).append(vec)
        self._audit("face", subject_id, len(gallery))
        return gallery

    def load_voice_gallery(self, subject_id: str) -> Dict[str, List[np.ndarray]]:
        """{student_id: [192-d normalised embeddings]} for the roster."""
        client = self._ensure_client()
        ids = self._enrolled_ids(subject_id)
        gallery: Dict[str, List[np.ndarray]] = {}
        if not ids:
            return gallery
        resp = client.table("voice_embeddings").select(
            "student_id, vector").in_("student_id", ids).execute()
        for row in resp.data or []:
            vec = np.asarray(row.get("vector"), dtype=np.float32).ravel()
            if vec.shape[0] != 192:
                logger.warning("voice embedding for %s is %d-d, skipping",
                               row.get("student_id"), vec.shape[0])
                continue
            gallery.setdefault(str(row["student_id"]), []).append(vec)
        self._audit("voice", subject_id, len(gallery))
        return gallery
