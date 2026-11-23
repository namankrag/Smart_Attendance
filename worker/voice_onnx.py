"""Voice pipeline (Phase 2.5): ECAPA-TDNN + pyannote + AASIST.

Replaces Resemblyzer (256-d) and the naive ``librosa.split(top_db=28)``
segmentation in ``src/pipelines/voice_pipeline.py``:

* **Embeddings** — ECAPA-TDNN (arXiv:2005.07143) via SpeechBrain
  ``speechbrain/spkrec-ecapa-voxceleb`` (192-d). The legacy 256-d
  Resemblyzer templates are NOT compatible: re-enrolment is required
  when the worker switches over (old templates stay readable by the
  legacy path only).
* **Diarization** — pyannote.audio ``pyannote/speaker-diarization-3.1``
  (arXiv:1911.01255; https://huggingface.co/pyannote/speaker-diarization-3.1).
  Needs ffmpeg and an ``HF_TOKEN`` — read from the **worker
  environment only** (``worker/config.py``), never in Streamlit, never
  in a committed file. Without the token the diarizer raises loudly.
* **Anti-spoofing** — AASIST (arXiv:2110.01200), ONNX. A replayed /
  synthesised voice is rejected before matching. Fail closed: if the
  AASIST model is unavailable, verification rejects.
* **Challenge phrase** — the server issues a short-lived random phrase
  for 1:1 voice verification and re-enrolment. The speaker must say
  the phrase; the phrase is random per attempt so a replay of an old
  recording does not match the current challenge.

Speech recognition is deliberately NOT added: the spec says to ask
Naman before adding a check that the spoken words match the phrase,
and he is asleep. The challenge is therefore a liveness/replay
defence (fresh audio, AASIST-clean, ECAPA-matched), not a proof the
words were spoken. Documented optional next step, not built here.
"""

from __future__ import annotations

import logging
import os
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from worker.face_onnx import ModelUnavailableError, ONNXModel

logger = logging.getLogger(__name__)

__all__ = [
    "ECAPAEmbedder",
    "Diarizer",
    "AASISTAntiSpoof",
    "VoiceChallenge",
    "VoiceChallengeStore",
    "VoiceVerifier",
    "cosine_similarity",
]

# Short wordlist for server-issued challenge phrases. Random 4-word
# phrases from this list are unpredictable per attempt (12^4 combos
# before the random word order is considered — the phrase is issued
# per attempt and expires in 120 s, so guessing is not the threat;
# replay of a previous attempt's audio is, and the phrase changes).
_CHALLENGE_WORDS = (
    "river", "copper", "meadow", "harbor", "velvet", "planet",
    "silver", "garden", "marble", "rocket", "pillow", "candle",
)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity of two vectors in [-1, 1]; 0.0 if either is zero."""
    va = np.asarray(a, dtype=np.float32).ravel()
    vb = np.asarray(b, dtype=np.float32).ravel()
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.clip(float(np.dot(va / na, vb / nb)), -1.0, 1.0))


class ECAPAEmbedder:
    """ECAPA-TDNN speaker embeddings (arXiv:2005.07143).

    SpeechBrain ``spkrec-ecapa-voxceleb``: 192-d, L2-normalised.
    The SpeechBrain model is loaded lazily; missing torch/speechbrain
    or a missing model cache raises :class:`ModelUnavailableError` —
    never a silent fallback to Resemblyzer (whose 256-d templates are
    incompatible anyway).
    """

    def __init__(self, model_id: str = "speechbrain/spkrec-ecapa-voxceleb",
                 model_loader=None):
        self.model_id = model_id
        self._loader = model_loader
        self._model = None

    def _ensure_loaded(self):
        if self._model is not None:
            return self._model
        if self._loader is not None:
            self._model = self._loader(self.model_id)
            return self._model
        try:
            from speechbrain.inference.speaker import SpeakerRecognition
        except ImportError as exc:
            raise ModelUnavailableError(
                "speechbrain/torch are not installed in the worker image; "
                "ECAPA-TDNN cannot run"
            ) from exc
        try:
            self._model = SpeakerRecognition.from_hparams(source=self.model_id)
        except Exception as exc:
            raise ModelUnavailableError(
                f"failed to load ECAPA-TDNN {self.model_id!r}: {exc}. "
                "The model must be baked into the worker image; the worker "
                "never downloads models at runtime."
            ) from exc
        return self._model

    def embed(self, wav_16k: np.ndarray) -> np.ndarray:
        """192-d L2-normalised embedding for mono 16 kHz audio."""
        model = self._ensure_loaded()
        import torch
        wav = np.asarray(wav_16k, dtype=np.float32).ravel()
        with torch.no_grad():
            emb = model.encode_batch(torch.from_numpy(wav).unsqueeze(0))
        vec = np.asarray(emb.squeeze().cpu().numpy(), dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 0 else vec


class Diarizer:
    """pyannote.audio speaker diarization 3.1 (arXiv:1911.01255).

    ``HF_TOKEN`` comes from the worker environment only (config).
    The gated model refuses without a token — that raises loudly here
    instead of silently returning one segment.
    """

    def __init__(self, config, pipeline_loader=None):
        self.config = config
        self._loader = pipeline_loader
        self._pipeline = None

    def _ensure_loaded(self):
        if self._pipeline is not None:
            return self._pipeline
        token = getattr(self.config, "hf_token", "") or os.environ.get("HF_TOKEN", "")
        if not token:
            raise ModelUnavailableError(
                "HF_TOKEN is not set in the worker environment; pyannote "
                "speaker-diarization-3.1 is a gated model and cannot load "
                "without it. Set HF_TOKEN in the worker host's environment "
                "only — never in Streamlit, never in a file."
            )
        if self._loader is not None:
            self._pipeline = self._loader(token)
            return self._pipeline
        try:
            from pyannote.audio import Pipeline
        except ImportError as exc:
            raise ModelUnavailableError(
                "pyannote.audio is not installed in the worker image"
            ) from exc
        try:
            self._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1", use_auth_token=token)
        except Exception as exc:
            raise ModelUnavailableError(
                f"failed to load pyannote diarization: {exc}"
            ) from exc
        return self._pipeline

    def diarize(self, wav_16k: np.ndarray, sample_rate: int = 16000
                ) -> List[Dict[str, Any]]:
        """Return ``[{"start", "end", "speaker"}, ...]`` segments.

        Replaces the old ``librosa.split(top_db=28)`` segmentation,
        which split on energy in noise and could not separate
        overlapping speech (audit 35).
        """
        pipeline = self._ensure_loaded()
        import torch
        waveform = torch.from_numpy(
            np.asarray(wav_16k, dtype=np.float32)).unsqueeze(0)
        diarization = pipeline({"waveform": waveform, "sample_rate": sample_rate})
        segments = []
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            segments.append({"start": float(turn.start), "end": float(turn.end),
                             "speaker": str(speaker)})
        return segments


class AASISTAntiSpoof:
    """AASIST anti-spoofing (arXiv:2110.01200) via ONNX.

    Scores raw audio; returns a bonafide score in [0, 1] (higher =
    more likely a genuine live voice). Fail closed when weights are
    missing — see :class:`ModelUnavailableError`.
    """

    def __init__(self, model_path: str, session_factory=None):
        self.model = ONNXModel(model_path, session_factory=session_factory)

    def bonafide_score(self, wav_16k: np.ndarray) -> float:
        wav = np.asarray(wav_16k, dtype=np.float32).ravel()[None, :]
        out = self.model.run(wav.astype(np.float32))[0]
        return float(np.clip(float(np.asarray(out).ravel()[0]), 0.0, 1.0))


@dataclass
class VoiceChallenge:
    """Server-issued random challenge phrase (short-lived, single-use)."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    phrase: str = ""
    expires_at: float = 0.0
    used: bool = False

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) > self.expires_at


class VoiceChallengeStore:
    """In-memory issued voice challenges (worker process only)."""

    def __init__(self, ttl_seconds: int = 120):
        self.ttl_seconds = ttl_seconds
        self._store: Dict[str, VoiceChallenge] = {}

    def issue(self) -> VoiceChallenge:
        """Issue a random 4-word phrase challenge."""
        phrase = " ".join(secrets.choice(_CHALLENGE_WORDS) for _ in range(4))
        chal = VoiceChallenge(phrase=phrase,
                              expires_at=time.time() + self.ttl_seconds)
        self._store[chal.id] = chal
        return chal

    def verify_and_consume(self, challenge_id: str) -> Optional[VoiceChallenge]:
        chal = self._store.pop(challenge_id, None)
        if chal is None or chal.used or chal.is_expired():
            return None
        chal.used = True
        return chal


class VoiceVerifier:
    """1:1 voice verification: challenge + AASIST + ECAPA match.

    Order matters: the challenge is consumed first (replay defence),
    then AASIST (spoof defence), then ECAPA cosine against the claimed
    student's template only. Any failure rejects. No speech-recognition
    check of the phrase is performed — that is a documented optional
    next step requiring Naman's approval (see module docstring).
    """

    def __init__(self, config, session_factory=None,
                 embedder: Optional[ECAPAEmbedder] = None,
                 spoof: Optional[AASISTAntiSpoof] = None,
                 challenge_store: Optional[VoiceChallengeStore] = None):
        self.config = config
        self._session_factory = session_factory
        self.embedder = embedder
        self._spoof = spoof
        self.challenges = challenge_store or VoiceChallengeStore(
            ttl_seconds=config.voice_challenge_ttl_seconds)
        self._spoof_error: Optional[str] = None

    def issue_challenge(self) -> VoiceChallenge:
        return self.challenges.issue()

    def _ensure_spoof(self) -> AASISTAntiSpoof:
        if self._spoof is not None:
            return self._spoof
        if self._spoof_error is not None:
            raise ModelUnavailableError(self._spoof_error)
        try:
            self._spoof = AASISTAntiSpoof(self.config.aasist_path,
                                          session_factory=self._session_factory)
        except ModelUnavailableError as exc:
            self._spoof_error = str(exc)
            raise
        return self._spoof

    def _ensure_embedder(self) -> ECAPAEmbedder:
        if self.embedder is None:
            self.embedder = ECAPAEmbedder()
        return self.embedder

    def verify_1to1(self, wav_16k: np.ndarray, challenge_id: str,
                    gallery_embeddings: Sequence[np.ndarray]) -> Dict[str, Any]:
        """Verify a voice sample against ONE student's templates only."""
        chal = self.challenges.verify_and_consume(challenge_id)
        if chal is None:
            return {"matched": False, "reason": "invalid_or_expired_challenge",
                    "cosine": None, "spoof_score": None}
        try:
            spoof = self._ensure_spoof()
        except ModelUnavailableError as exc:
            logger.error("AASIST unavailable; rejecting voice verification: %s", exc)
            return {"matched": False, "reason": "spoof_model_unavailable",
                    "cosine": None, "spoof_score": None}
        spoof_score = spoof.bonafide_score(wav_16k)
        if spoof_score < self.config.voice_spoof_threshold:
            return {"matched": False, "reason": "spoof_score_below_threshold",
                    "cosine": None, "spoof_score": spoof_score}
        try:
            query = self._ensure_embedder().embed(wav_16k)
        except ModelUnavailableError as exc:
            logger.error("ECAPA unavailable; rejecting voice verification: %s", exc)
            return {"matched": False, "reason": "voice_model_unavailable",
                    "cosine": None, "spoof_score": spoof_score}
        sims = [cosine_similarity(query, g) for g in gallery_embeddings]
        best = max(sims) if sims else -1.0
        matched = bool(best >= self.config.voice_cosine_threshold)
        return {"matched": matched,
                "reason": "ok" if matched else "below_threshold",
                "cosine": best, "spoof_score": spoof_score,
                "challenge_phrase": chal.phrase}
