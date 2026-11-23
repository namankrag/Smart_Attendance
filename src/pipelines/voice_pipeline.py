"""Voice pipeline: speaker embeddings and identification.

Pipeline code never calls st.error / st.warning: failures return
``None`` / ``{}`` and are logged, so the UI layer decides how to
report them.

Student IDs are UUID strings (``str``), not ints — the Phase 1
migration moves ``students.student_id`` to UUID. The dict keys in
``identify_speaker`` / ``process_bulk_audio`` are passed through
unchanged, so callers must use the IDs exactly as Supabase returns
them.
"""

from typing import Dict, Tuple, Optional
import io

# Phase 2: librosa / resemblyzer are legacy dependencies. The light UI
# image (Dockerfile.ui / requirements-ui.txt) does NOT install them, so
# these imports are defensive: the module must still import (the UI
# boots), and any legacy in-process voice call fails loudly via
# load_voice_encoder() instead of crashing at import time. The ONNX
# worker (worker/voice_onnx.py: ECAPA-TDNN + pyannote + AASIST) is the
# default path.
try:
    import librosa
except ImportError:  # pragma: no cover - light UI image has no librosa
    librosa = None  # type: ignore[assignment]
import logging
import numpy as np
import streamlit as st

try:
    from resemblyzer import VoiceEncoder, preprocess_wav
except ImportError:  # pragma: no cover - light UI image has no resemblyzer
    VoiceEncoder = None  # type: ignore[assignment]

    def preprocess_wav(wav):  # type: ignore[misc]
        raise RuntimeError(
            "Legacy Resemblyzer voice models are not installed in this "
            "image. Use the Phase 2 ML worker (POST /jobs) or install "
            "the legacy stack from requirements.txt for local dev."
        )


logger = logging.getLogger(__name__)


@st.cache_resource(show_spinner=False)
def load_voice_encoder() -> VoiceEncoder:
    """Load and cache pre-trained speaker embedding network.

    Phase 2: raises ``RuntimeError`` (loudly) when resemblyzer is not
    installed — the light UI image has none, and the ONNX worker is
    the default path. Never silently returns a stub.
    """
    if VoiceEncoder is None or librosa is None:
        raise RuntimeError(
            "Legacy Resemblyzer voice models are not installed in this "
            "image. Use the Phase 2 ML worker (POST /jobs) or install "
            "the legacy stack from requirements.txt for local dev."
        )
    return VoiceEncoder()


def _normalize(v: np.ndarray) -> np.ndarray:
    """L2-normalize an embedding vector for true cosine dot product."""
    norm = np.linalg.norm(v)
    return v / (norm + 1e-10)


def get_voice_embedding(audio_bytes: Optional[bytes]) -> Optional[list]:
    """Generate normalized 256-D voice embedding from raw audio bytes.

    Returns ``None`` (and logs) when there is no audio or feature
    extraction fails; the caller decides what to show the user.
    """
    if not audio_bytes:
        return None
    try:
        encoder = load_voice_encoder()
        audio, _ = librosa.load(io.BytesIO(audio_bytes), sr=16000)
        wav = preprocess_wav(audio)
        embedding = encoder.embed_utterance(wav)
        normalized = _normalize(embedding)
        return normalized.tolist()
    except Exception as exc:
        logger.warning("Voice feature extraction failed: %s", exc)
        return None


def identify_speaker(
    new_embedding: Optional[list], candidate_dict: Dict[str, list], threshold: float = 0.65
) -> Tuple[Optional[str], float]:
    """
    Match query speaker embedding against candidate dictionary via normalized cosine similarity.
    Keys of ``candidate_dict`` are student IDs (UUID ``str``).
    Returns: (matched_student_id, confidence_score)
    """
    if not new_embedding or not candidate_dict:
        return None, 0.0

    valid_candidates = [
        (sid, emb) for sid, emb in candidate_dict.items() if emb and len(emb) == 256
    ]
    if not valid_candidates:
        return None, 0.0

    sids, embeddings = zip(*valid_candidates, strict=False)

    # Ensure all vectors are L2-normalized
    emb_matrix = np.array(
        [_normalize(np.array(e, dtype=np.float32)) for e in embeddings], dtype=np.float32
    )
    query_vec = _normalize(np.array(new_embedding, dtype=np.float32))

    # Vectorized cosine similarity dot product
    similarities = np.dot(emb_matrix, query_vec)
    best_idx = int(np.argmax(similarities))
    best_score = float(similarities[best_idx])

    if best_score >= threshold:
        return sids[best_idx], best_score

    return None, best_score


def process_bulk_audio(
    audio_bytes: Optional[bytes], candidate_dict: Dict[str, list], threshold: float = 0.65
) -> Dict[str, float]:
    """
    Segment classroom speech audio and identify all present speakers.
    Keys of ``candidate_dict`` are student IDs (UUID ``str``).
    Returns mapping: student_id -> highest_confidence_score.
    Returns ``{}`` (and logs) when there is no audio or recognition fails.
    """
    if not audio_bytes:
        return {}

    try:
        encoder = load_voice_encoder()
        audio, sr = librosa.load(io.BytesIO(audio_bytes), sr=16000)
        segments = librosa.effects.split(audio, top_db=28)
        identified_results: Dict[str, float] = {}

        for start, end in segments:
            # Skip noise blips shorter than 0.4s
            if (end - start) < (sr * 0.4):
                continue
            segment_audio = audio[start:end]
            wav = preprocess_wav(segment_audio)
            embedding = encoder.embed_utterance(wav)
            norm_emb = _normalize(embedding).tolist()

            sid, score = identify_speaker(norm_emb, candidate_dict, threshold=threshold)
            if sid:
                if sid not in identified_results or score > identified_results[sid]:
                    identified_results[sid] = score

        return identified_results
    except Exception as exc:
        logger.exception("Bulk voice recognition failed: %s", exc)
        return {}
