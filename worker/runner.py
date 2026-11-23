"""Job execution (Phase 2.2-2.5).

``process_one_job`` claims one job from the store, runs the right
pipeline, and completes/fails the job. Payload bytes are taken out of
the store up front and deleted in a ``finally`` — raw photos/audio are
never kept after inference (SPEC constraints) and never written to
disk; everything happens in memory.

Face jobs: decode image bytes → ONNX pipeline ``match_group`` against
the enrolled roster's gallery. Voice jobs: decode WAV bytes → pyannote
diarization → per-segment ECAPA embedding → best-match student per
speaker segment. PAD / AASIST / challenge checks run inside the 1:1
verifiers (``worker/pad.py``, ``worker/voice_onnx.py``), not here:
group attendance is 1:N matching, while liveness/spoof gates apply to
1:1 login/registration, which go through the verifier endpoints'
logic in the app layer.
"""

from __future__ import annotations

import io
import logging
import wave
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

__all__ = ["process_one_job", "run_face_job", "run_voice_job", "decode_wav_bytes"]


def _audit_template_access(ctx: Dict[str, Any], event: Dict[str, Any]) -> None:
    """Phase 3: audit one template read/match (identifiers + counts only).

    Calls ``ctx["audit_template_access"]`` when the worker app wired
    one (it inserts an audit_log row); otherwise the event goes to
    the structured log. Never raises and never carries a vector, a
    photo or audio — the event is counts and student ids only.
    """
    try:
        callback = ctx.get("audit_template_access")
        if callable(callback):
            callback(event)
        else:
            logger.info("template access: %s", event)
    except Exception:
        logger.exception("template-access audit failed (match result kept)")


def decode_wav_bytes(data: bytes) -> np.ndarray:
    """Decode PCM WAV bytes to mono float32 samples at their native rate.

    Only plain PCM WAV is accepted here (what the UI records). Anything
    else raises ``ValueError`` and fails the job with a clear error —
    never a silent empty result.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            n_channels = wf.getnchannels()
            width = wf.getsampwidth()
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
    except Exception as exc:
        raise ValueError(f"audio payload is not decodable PCM WAV: {exc}") from exc
    if width == 2:
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif width == 1:
        audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"unsupported WAV sample width: {width}")
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)
    if rate != 16000:
        # The worker expects 16 kHz mono (ECAPA/pyannote input). Rather
        # than silently resampling with a possibly-wrong filter, fail
        # loudly: the UI must send 16 kHz (it downsamples on record).
        raise ValueError(f"audio sample rate is {rate} Hz, expected 16000 Hz")
    return audio.astype(np.float32)


def run_face_job(payload: bytes, subject_id: Optional[str],
                 candidate_ids: List[str], gallery_loader,
                 face_pipeline, ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run a group-photo face job. Returns a JSON-serialisable result."""
    try:
        img = np.asarray(Image.open(io.BytesIO(payload)).convert("RGB"))
    except Exception as exc:
        raise ValueError(f"image payload is not decodable: {exc}") from exc
    if subject_id:
        gallery = gallery_loader.load_face_gallery(subject_id)
    else:
        gallery = {}
    # Restrict to the caller's candidate roster when given.
    if candidate_ids:
        wanted = {str(c) for c in candidate_ids}
        gallery = {k: v for k, v in gallery.items() if k in wanted}
    result = face_pipeline.match_group(img, gallery)
    detected = {
        sid: {"cosine": float(v["cosine"]), "margin": float(v["margin"]),
              "face_index": int(v["face_index"])}
        for sid, v in result["detected"].items()
    }
    # Phase 3 template-access audit: who was matched, not how — no
    # vectors, scores are per-student match facts already returned to
    # the caller; the audit row keeps ids + counts only.
    _audit_template_access(ctx or {}, {
        "template_kind": "face",
        "access": "match",
        "subject_id": subject_id,
        "students_compared": len(gallery),
        "students_matched": len(detected),
        "matched_student_ids": sorted(detected),
    })
    return {
        "detected": detected,
        "num_faces": int(result["num_faces"]),
        "low_quality_face_indices": [int(i) for i in result["low_quality_face_indices"]],
    }


def run_voice_job(payload: bytes, subject_id: Optional[str],
                  candidate_ids: List[str], gallery_loader,
                  diarizer, embedder, cosine_threshold: float,
                  ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run a classroom-audio voice job.

    Diarize first (pyannote), then embed each segment (ECAPA-TDNN)
    and match it against the roster gallery. Overlapping speech is
    handled by the diarizer, not by energy splitting (audit 35).
    """
    from worker.voice_onnx import cosine_similarity

    wav = decode_wav_bytes(payload)
    if subject_id:
        gallery = gallery_loader.load_voice_gallery(subject_id)
    else:
        gallery = {}
    if candidate_ids:
        wanted = {str(c) for c in candidate_ids}
        gallery = {k: v for k, v in gallery.items() if k in wanted}
    segments = diarizer.diarize(wav)
    identified: Dict[str, float] = {}
    sample_rate = 16000
    for seg in segments:
        start = int(float(seg["start"]) * sample_rate)
        end = int(float(seg["end"]) * sample_rate)
        clip = wav[start:end]
        if len(clip) < int(0.4 * sample_rate):
            continue  # skip noise blips shorter than 0.4 s
        query = embedder.embed(clip)
        best_sid, best_score = None, -1.0
        for sid, vecs in gallery.items():
            for vec in vecs:
                score = cosine_similarity(query, vec)
                if score > best_score:
                    best_sid, best_score = sid, float(score)
        if best_sid is not None and best_score >= cosine_threshold:
            if best_sid not in identified or best_score > identified[best_sid]:
                identified[best_sid] = best_score
    # Phase 3 template-access audit: ids + counts only, no vectors/audio.
    _audit_template_access(ctx or {}, {
        "template_kind": "voice",
        "access": "match",
        "subject_id": subject_id,
        "students_compared": len(gallery),
        "students_matched": len(identified),
        "matched_student_ids": sorted(identified),
    })
    return {"identified": identified, "num_segments": len(segments)}


def process_one_job(store, ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Claim and run a single job. Returns the completed job dict, or
    ``None`` when the queue is empty. Failures are recorded on the job
    (``failed`` + generic error) and never raise to the caller — the
    worker loop must keep draining the queue.
    """
    job = store.claim_next()
    if job is None:
        return None
    job_id = str(job["id"])
    payload = None
    try:
        payload = store.take_payload(job_id)
        if payload is None:
            raise ValueError("job payload is missing (expired or never uploaded)")
        store.mark_progress(job_id, 10)
        if job["type"] == "face":
            result = run_face_job(
                payload, job.get("subject_id"), list(job.get("candidate_ids") or []),
                ctx["gallery_loader"], ctx["face_pipeline"], ctx=ctx)
        elif job["type"] == "voice":
            result = run_voice_job(
                payload, job.get("subject_id"), list(job.get("candidate_ids") or []),
                ctx["gallery_loader"], ctx["diarizer"], ctx["embedder"],
                ctx["config"].voice_cosine_threshold, ctx=ctx)
        else:
            raise ValueError(f"unknown job type: {job['type']!r}")
        store.mark_progress(job_id, 90)
        store.complete_job(job_id, result)
        return store.get_job(job_id)
    except Exception as exc:
        # Generic error only: never leak stack traces / DB details.
        logger.exception("job %s failed", job_id)
        store.fail_job(job_id, f"{type(exc).__name__}: {exc}")
        return store.get_job(job_id)
    finally:
        # Payload bytes are dropped even on failure — raw media is
        # never kept after inference.
        payload = None
