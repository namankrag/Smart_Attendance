"""Worker configuration — environment variables only (Phase 2.2).

Nothing here reads Streamlit secrets and nothing here is committed
with real values. Secrets (``HF_TOKEN``, ``SUPABASE_SERVICE_ROLE_KEY``)
live in the worker host's environment / secret store only — never in
the repo, never in the Streamlit app, never in a file that is
committed. ``HF_TOKEN`` is read here (worker only) because pyannote's
gated diarization model needs it; the Streamlit UI must never see it.
The service-role key is used only by gallery loading and protected REST
operations; normal REST database calls use the signed-in user's JWT.

Threshold defaults are UNCALIBRATED (see ``scripts/evaluate_biometrics.py``):
they are starting points, not measured operating points.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = ["WorkerConfig", "get_config"]


@dataclass
class WorkerConfig:
    # Model weights directory — baked into the worker image at build
    # time. No runtime downloads, ever (see worker/README.md).
    model_dir: str = "/models"
    # SCRFD detector weights (InsightFace SCRFD ONNX).
    scrfd_model: str = "scrfd_10g_bnkps.onnx"
    # ArcFace (InsightFace) or AdaFace recognition weights.
    face_rec_model: str = "arcface_r100.onnx"
    # MiniFASNet / CDCN passive PAD weights.
    pad_model: str = "minifasnet.onnx"
    # AASIST anti-spoofing weights (ONNX export).
    aasist_model: str = "aasist.onnx"
    # Face backend: "onnx" (default, required) or "dlib".
    # "dlib" is a TRANSITION flag only: the worker has no dlib, so
    # selecting it raises loudly instead of silently falling back.
    face_backend: str = "onnx"

    database_url: str = ""  # Postgres DSN; empty -> in-memory job store (dev only)
    supabase_url: str = ""
    supabase_service_role_key: str = ""  # WORKER ONLY. Never in Streamlit.
    # Hugging Face token for pyannote's gated diarization model.
    # Worker environment only. Never in Streamlit, never in files.
    hf_token: str = ""

    # Job payload limit (decoded bytes). Larger uploads are rejected 413.
    max_payload_bytes: int = 25 * 1024 * 1024
    # Active-challenge lifetimes (seconds).
    pad_challenge_ttl_seconds: int = 60
    voice_challenge_ttl_seconds: int = 120

    # -- UNCALIBRATED starting thresholds (calibrate per ISO/IEC 19795-1) --
    face_cosine_threshold: float = 0.40  # ArcFace/AdaFace cosine; provisional
    face_margin_threshold: float = 0.05  # second-best margin; provisional
    face_min_feature_norm: float = 5.0  # AdaFace/MagFace quality gate; provisional
    pad_live_threshold: float = 0.5  # passive PAD score; provisional
    voice_cosine_threshold: float = 0.65  # ECAPA cosine; provisional
    voice_spoof_threshold: float = 0.5  # AASIST bonafide score; provisional

    @property
    def scrfd_path(self) -> str:
        return os.path.join(self.model_dir, self.scrfd_model)

    @property
    def face_rec_path(self) -> str:
        return os.path.join(self.model_dir, self.face_rec_model)

    @property
    def pad_path(self) -> str:
        return os.path.join(self.model_dir, self.pad_model)

    @property
    def aasist_path(self) -> str:
        return os.path.join(self.model_dir, self.aasist_model)


def get_config() -> WorkerConfig:
    """Build config from the worker process environment."""
    return WorkerConfig(
        model_dir=os.environ.get("MODEL_DIR", "/models"),
        scrfd_model=os.environ.get("SCRFD_MODEL", "scrfd_10g_bnkps.onnx"),
        face_rec_model=os.environ.get("FACE_REC_MODEL", "arcface_r100.onnx"),
        pad_model=os.environ.get("PAD_MODEL", "minifasnet.onnx"),
        aasist_model=os.environ.get("AASIST_MODEL", "aasist.onnx"),
        face_backend=os.environ.get("FACE_BACKEND", "onnx"),
        database_url=os.environ.get("DATABASE_URL", ""),
        supabase_url=os.environ.get("SUPABASE_URL", ""),
        supabase_service_role_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        hf_token=os.environ.get("HF_TOKEN", ""),
        max_payload_bytes=int(os.environ.get("MAX_PAYLOAD_BYTES", str(25 * 1024 * 1024))),
    )
