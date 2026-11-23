"""ML worker package (Phase 2.2-2.5).

FastAPI + Postgres-queue ML worker. It runs OUTSIDE the Streamlit
process (separate container — see ``Dockerfile.worker``): the UI image
contains no torch / dlib / onnxruntime / pyannote.

Layout
------
* ``config`` — environment config (worker env only).
* ``queue`` — Postgres ``FOR UPDATE SKIP LOCKED`` job claiming.
* ``face_onnx`` — SCRFD detection + ArcFace/AdaFace embeddings (ONNX
  Runtime), tiled inference + NMS, quality gate, Hungarian matching.
* ``pad`` — MiniFASNet/CDCN passive PAD + randomised active challenge.
* ``voice_onnx`` — ECAPA-TDNN + pyannote diarization + AASIST spoofing.
* ``gallery`` — roster template loading (worker-side service_role only).
* ``runner`` — job execution: payload bytes in, result dict out.
* ``app`` — FastAPI app: ``POST /jobs``, ``GET /jobs/{id}``,
  ``GET /healthz``, ``GET /readyz``.

Model weights are NEVER downloaded at runtime: they must be baked
into the worker image at build time (see ``worker/README.md``). Every
model loader fails loudly (``FileNotFoundError`` / ``RuntimeError``)
when weights or libraries are missing — never a silent fallback to
the legacy dlib path, never a silent accept.
"""

__all__ = []
