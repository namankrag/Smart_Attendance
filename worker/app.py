"""FastAPI ML worker app (Phase 2.2).

Endpoints
---------
* ``GET /healthz`` — liveness: the process is up.
* ``GET /readyz`` — readiness: model files present AND the job store
  reachable. Returns 503 otherwise (compose healthchecks use this).
* ``POST /jobs`` — submit a ``face`` or ``voice`` job (JSON:
  ``type``, ``subject_id``, ``candidate_ids``, ``payload_b64``,
  ``metadata``). Returns 202 with the job. The payload is held in
  memory only and deleted after processing — never written to disk.
* ``GET /jobs/{id}`` — poll status / progress / result / error.
* ``POST /challenges/face`` / ``POST /challenges/voice`` — issue a
  randomised, short-lived, single-use active challenge (PAD / voice).
* ``POST /verify/face-1to1`` / ``POST /verify/voice-1to1`` — 1:1
  verification with liveness / anti-spoofing (fail closed).

The app never downloads models at runtime and never touches the
Streamlit session. ``service_role`` (gallery loading) lives here in
the worker environment only — never in the UI.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import logging
import os
from typing import Any, Dict, Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

__all__ = ["create_app"]

# Public job view: what the UI is allowed to see. Internal fields
# (subject/candidate lists are fine to echo; payloads never are).
_PUBLIC_FIELDS = ("id", "type", "status", "progress", "result_json", "error")


def _public_job(job: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: job.get(k) for k in _PUBLIC_FIELDS if k in job}
    # The UI polls `result`, not `result_json`.
    if "result_json" in out:
        out["result"] = out.pop("result_json")
    return out


def _decode_b64(payload_b64: Optional[str], max_bytes: int) -> bytes:
    if not payload_b64:
        raise ValueError("payload_b64 is required")
    try:
        raw = base64.b64decode(payload_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("payload_b64 is not valid base64") from exc
    if len(raw) > max_bytes:
        raise ValueError(f"payload exceeds {max_bytes} bytes")
    return raw


def create_app(config=None, store=None, ctx: Optional[Dict[str, Any]] = None):
    """Build the FastAPI app. ``config``/``store``/``ctx`` are injectable
    for tests; production defaults come from the environment."""
    from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
    from worker.config import get_config
    from worker.face_onnx import ModelUnavailableError, ONNXFacePipeline
    from worker.gallery import GalleryLoader
    from worker.pad import LivenessVerifier
    from worker.runner import decode_wav_bytes, process_one_job
    from worker.stores import MemoryJobStore, PostgresJobStore
    from worker.voice_onnx import ECAPAEmbedder, Diarizer, VoiceVerifier

    cfg = config or get_config()
    app = FastAPI(title="Smart Attendance ML worker")
    app.state.payloads: Dict[str, bytes] = {}

    if store is None:
        if cfg.database_url:
            import psycopg
            store = PostgresJobStore(
                lambda: psycopg.connect(cfg.database_url, autocommit=False))
        else:
            store = MemoryJobStore()
    app.state.store = store

    # Lazy pipeline singletons (models load on first use, fail loudly).
    _ctx: Dict[str, Any] = dict(ctx or {})
    _ctx.setdefault("config", cfg)

    def _get(name, factory):
        if name not in _ctx:
            _ctx[name] = factory()
        return _ctx[name]

    def _audit_template_access(event: Dict[str, Any]) -> None:
        """Phase 3: write one template-access audit row to audit_log.

        DPDP Act Sec. 8(5) (reasonable security safeguards, incl.
        logging/monitoring) and GDPR Art. 9 accountability: every
        template read/match is recorded. The event carries identifiers
        + counts only — never a vector, photo or audio (enforced by
        the callers in worker/gallery.py and worker/runner.py).
        With the Postgres store, the row goes to audit_log via the
        store's connection factory; with the in-memory store (dev /
        tests) there is no database, so the event goes to the
        structured log instead. Never raises: audit failure must not
        break inference.
        """
        conn_factory = getattr(store, "_conn_factory", None)
        if not callable(conn_factory):
            logger.info("template access: %s", event)
            return
        table = ("face_embeddings" if event.get("template_kind") == "face"
                 else "voice_embeddings")
        matched = event.get("matched_student_ids") or []
        record_id = matched[0] if matched else None
        try:
            conn = conn_factory()
            try:
                cur = conn.cursor()
                try:
                    cur.execute(
                        "INSERT INTO audit_log "
                        "(actor_id, action, table_name, record_id, details) "
                        "VALUES (%s, 'template_access', %s, %s, %s::jsonb)",
                        (None, table, record_id, json.dumps(event)),
                    )
                finally:
                    cur.close()
                conn.commit()
            finally:
                conn.close()
        except Exception:
            logger.exception("template-access audit insert failed")

    def _gallery_loader():
        return _get("gallery_loader",
                    lambda: GalleryLoader(cfg, on_template_access=_audit_template_access))

    def _face_pipeline():
        return _get("face_pipeline", lambda: ONNXFacePipeline(cfg))

    def _diarizer():
        return _get("diarizer", lambda: Diarizer(cfg))

    def _embedder():
        return _get("embedder", lambda: ECAPAEmbedder())

    def _liveness():
        return _get("liveness", lambda: LivenessVerifier(cfg))

    def _voice_verifier():
        return _get("voice_verifier", lambda: VoiceVerifier(cfg))

    def _run_ctx() -> Dict[str, Any]:
        return {
            "config": cfg,
            "gallery_loader": _gallery_loader(),
            "face_pipeline": _face_pipeline(),
            "diarizer": _diarizer(),
            "embedder": _embedder(),
            "audit_template_access": _audit_template_access,
        }

    def _take_payload(job_id: str) -> Optional[bytes]:
        payload = app.state.payloads.pop(job_id, None)
        if payload is not None:
            return payload
        take = getattr(store, "take_payload", None)
        return take(job_id) if callable(take) else None

    # -- health ---------------------------------------------------------
    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        missing = [p for p in (cfg.scrfd_path, cfg.face_rec_path,
                               cfg.pad_path, cfg.aasist_path)
                   if not os.path.isfile(p)]
        if missing:
            raise HTTPException(
                status_code=503,
                detail=f"model weights missing (bake them into the image): {missing}")
        try:
            if not store.ping():
                raise HTTPException(status_code=503, detail="job store unreachable")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"job store unreachable: {exc}") from exc
        return {"status": "ready"}

    # -- jobs -----------------------------------------------------------
    @app.post("/jobs", status_code=202)
    async def submit_job(request: Request, background_tasks: BackgroundTasks):
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid JSON body") from exc
        job_type = str(body.get("type") or "")
        if job_type not in ("face", "voice"):
            raise HTTPException(
                status_code=400, detail="type must be 'face' or 'voice'")
        try:
            payload = _decode_b64(body.get("payload_b64"), cfg.max_payload_bytes)
        except ValueError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        job = store.create_job(
            job_type, subject_id=body.get("subject_id"),
            candidate_ids=body.get("candidate_ids") or [],
            metadata=body.get("metadata") or {})
        job_id = str(job["id"])
        # Payloads live in memory only. MemoryJobStore keeps them; the
        # Postgres store does not persist raw media, so the app holds
        # them (single-replica limitation, documented in README).
        try:
            store.put_payload(job_id, payload)
        except (NotImplementedError, AttributeError):
            app.state.payloads[job_id] = payload
        # The background task claims via the store; _take_payload above
        # is used by process_one_job through a store shim — see below.
        background_tasks.add_task(_process_job_task, job_id)
        return _public_job(job)

    async def _process_job_task(job_id: str):
        # process_one_job calls store.take_payload; for the Postgres
        # store the payload lives in app.state.payloads, so wrap the
        # store with a payload-aware shim for this one call.
        shim = _PayloadShim(store, lambda jid: _take_payload(jid))
        try:
            process_one_job(shim, _run_ctx())
        except Exception:
            logger.exception("background job processing failed for %s", job_id)

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str):
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return _public_job(job)

    # -- challenges + 1:1 verification ----------------------------------
    @app.post("/challenges/face")
    def issue_face_challenge():
        chal = _liveness().issue_challenge()
        return {"id": chal.id, "kind": chal.kind, "expires_at": chal.expires_at}

    @app.post("/challenges/voice")
    def issue_voice_challenge():
        chal = _voice_verifier().issue_challenge()
        return {"id": chal.id, "phrase": chal.phrase, "expires_at": chal.expires_at}

    @app.post("/verify/face-1to1")
    async def verify_face_1to1(request: Request):
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid JSON body") from exc
        try:
            raw = _decode_b64(body.get("image_b64"), cfg.max_payload_bytes)
            img = np.asarray(Image.open(io.BytesIO(raw)).convert("RGB"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        gallery = [np.asarray(v, dtype=np.float32)
                   for v in (body.get("gallery_embeddings") or [])]
        if not gallery:
            raise HTTPException(status_code=400, detail="gallery_embeddings is required")
        try:
            pipeline = _face_pipeline()
            detections = pipeline.detect_faces(img)
            if len(detections) != 1:
                return {"matched": False, "is_live": False,
                        "reason": "expected exactly one face",
                        "num_faces": len(detections)}
            from worker.face_onnx import align_face
            crop = align_face(img, detections[0].landmarks)
            frames = {
                "eye_before": body.get("eye_before"),
                "eye_after": body.get("eye_after"),
                "nose_before": body.get("nose_before"),
                "nose_after": body.get("nose_after"),
                "face_width": body.get("face_width"),
            }
            live = _liveness().verify(crop, str(body.get("challenge_id") or ""), frames)
            if not live["is_live"]:
                return {"matched": False, "is_live": False,
                        "reason": live["reason"], "pad_score": live.get("pad_score")}
            result = pipeline.verify_1to1(img, gallery)
            result["is_live"] = True
            result["pad_score"] = live.get("pad_score")
            return result
        except ModelUnavailableError as exc:
            # Fail closed: no model → reject, with a clear reason.
            logger.error("face 1:1 verification unavailable: %s", exc)
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/verify/voice-1to1")
    async def verify_voice_1to1(request: Request):
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid JSON body") from exc
        try:
            raw = _decode_b64(body.get("audio_b64"), cfg.max_payload_bytes)
            wav = decode_wav_bytes(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        gallery = [np.asarray(v, dtype=np.float32)
                   for v in (body.get("gallery_embeddings") or [])]
        if not gallery:
            raise HTTPException(status_code=400, detail="gallery_embeddings is required")
        result = _voice_verifier().verify_1to1(
            wav, str(body.get("challenge_id") or ""), gallery)
        return result

    return app


class _PayloadShim:
    """Wraps a job store so process_one_job can take payloads that live
    in the app's in-memory dict (Postgres store path)."""

    def __init__(self, store, take_payload_fn):
        self._store = store
        self._take = take_payload_fn

    def __getattr__(self, name):
        return getattr(self._store, name)

    def take_payload(self, job_id: str):
        payload = self._take(job_id)
        if payload is not None:
            return payload
        take = getattr(self._store, "take_payload", None)
        return take(job_id) if callable(take) else None
