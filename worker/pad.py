"""Face presentation-attack detection (Phase 2.4).

Replaces the heuristic liveness in ``src/pipelines/face_pipeline.py``
(glare / Moiré / bezel checks), which the spec is explicit about: it
does NOT reliably block printed photos or video replays, and must
never be the sole gate. This module is the replacement:

* **Passive PAD** — a trained model (MiniFASNet / CDCN in ONNX).
  CDCN: https://arxiv.org/abs/2003.04092 ; anti-spoofing survey:
  https://arxiv.org/abs/2106.14948 . The model scores a face crop;
  below threshold the face is rejected.
* **Randomised active challenge** — at registration and 1:1 login the
  server issues a short-lived, single-use challenge (``blink`` or
  ``head_turn``), chosen at random. The client must perform it while
  the camera is live; verification uses eye-aspect-ratio (blink) or
  landmark displacement (head turn) across two frames.

Fail closed, always: if the PAD model is unavailable (weights missing,
library missing), verification returns ``is_live=False`` with reason
``pad_model_unavailable`` — it NEVER silently accepts, and NEVER falls
back to the old heuristic. The heuristic is removed as a gate; it does
not exist in this module at all.

Challenge flow (documented):
1. UI requests a challenge from the worker (``issue_challenge``) and
   shows the instruction ("Blink now" / "Turn your head left").
2. The UI captures a before/after frame pair (or a short clip) while
   the challenge is displayed, and submits both frames with the
   challenge id.
3. The worker verifies: challenge id exists, is unexpired and unused
   (consumed on first verification attempt), the passive PAD score
   passes on the face crop, AND the active motion matches the issued
   challenge. Any failure rejects the login/registration.
"""

from __future__ import annotations

import logging
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import numpy as np

from worker.face_onnx import ModelUnavailableError, ONNXModel

logger = logging.getLogger(__name__)

__all__ = [
    "PADModel",
    "ActiveChallenge",
    "ChallengeStore",
    "LivenessVerifier",
    "eye_aspect_ratio",
]

CHALLENGE_KINDS = ("blink", "head_turn")


def eye_aspect_ratio(eye_landmarks: np.ndarray) -> float:
    """Eye aspect ratio from 6 eye landmarks (order: outer corner, upper
    l1, upper l2, inner corner, lower l2, lower l1).

    EAR drops sharply when the eye closes — a blink is a transient EAR
    dip below ~0.2 and back. The absolute threshold is uncalibrated;
    verification uses the *relative* drop between the two frames.
    """
    eye = np.asarray(eye_landmarks, dtype=np.float32)
    if eye.shape != (6, 2):
        raise ValueError("eye_aspect_ratio needs 6 landmarks (6, 2)")
    vertical = float(np.linalg.norm(eye[1] - eye[5]) + np.linalg.norm(eye[2] - eye[4]))
    horizontal = float(np.linalg.norm(eye[0] - eye[3]))
    return vertical / (2.0 * horizontal + 1e-9)


@dataclass
class ActiveChallenge:
    """A server-issued, short-lived, single-use liveness challenge."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    kind: str = "blink"  # "blink" | "head_turn"
    expires_at: float = 0.0
    used: bool = False

    def is_expired(self, now: Optional[float] = None) -> bool:
        return (now if now is not None else time.time()) > self.expires_at


class ChallengeStore:
    """In-memory issued challenges (worker process only).

    Challenges are single-use and short-lived; expired entries are
    dropped lazily on verify. This is intentionally in-memory: a
    challenge is worthless after ~60 s, and persisting it would create
    a replayable record.
    """

    def __init__(self, ttl_seconds: int = 60):
        self.ttl_seconds = ttl_seconds
        self._store: Dict[str, ActiveChallenge] = {}

    def issue(self) -> ActiveChallenge:
        """Issue a random challenge (blink or head turn, 50/50)."""
        kind = secrets.choice(CHALLENGE_KINDS)
        chal = ActiveChallenge(kind=kind, expires_at=time.time() + self.ttl_seconds)
        self._store[chal.id] = chal
        return chal

    def verify_and_consume(self, challenge_id: str) -> Optional[ActiveChallenge]:
        """Return the challenge if it exists, is unused and unexpired —
        and mark it used. Returns ``None`` otherwise (expired, unknown,
        or replayed)."""
        chal = self._store.pop(challenge_id, None)
        if chal is None or chal.used or chal.is_expired():
            return None
        chal.used = True
        return chal


class PADModel:
    """Trained passive PAD (MiniFASNet / CDCN, ONNX).

    The model takes an aligned 112x112 (MiniFASNet) face crop and
    returns a liveness score in [0, 1] (higher = more likely live).
    CDCN (arXiv:2003.04092) predicts a depth map; MiniFASNet
    (https://github.com/minivision-ai/Silent-Face-Anti-Spoofing)
    predicts a spoof score. Either way this wrapper normalises to a
    single ``live_score`` via the model's first output: deployments
    must confirm the output semantics against the baked weights (see
    ``worker/README.md``) — the threshold default is UNCALIBRATED.
    """

    def __init__(self, model_path: str, session_factory=None):
        self.model = ONNXModel(model_path, session_factory=session_factory)

    def live_score(self, aligned_crop: np.ndarray) -> float:
        """Score an aligned face crop; ``float`` in [0, 1]."""
        img = np.asarray(aligned_crop, dtype=np.float32)
        if img.ndim == 3:
            img = img.transpose(2, 0, 1)[None, :, :, :]
        img = (img - 127.5) / 128.0
        out = self.model.run(img.astype(np.float32))[0]
        score = float(np.asarray(out).ravel()[0])
        return float(np.clip(score, 0.0, 1.0))


class LivenessVerifier:
    """Passive PAD + active challenge, fail-closed.

    ``verify`` returns ``{"is_live", "reason", "pad_score",
    "challenge_kind"}``. ``is_live`` is True only when the PAD model
    loaded AND scored above threshold AND the issued challenge was
    verified. Any missing piece → ``is_live=False``.
    """

    def __init__(self, config, session_factory=None,
                 challenge_store: Optional[ChallengeStore] = None):
        self.config = config
        self._session_factory = session_factory
        self.challenges = challenge_store or ChallengeStore(
            ttl_seconds=config.pad_challenge_ttl_seconds)
        self._pad: Optional[PADModel] = None
        self._pad_error: Optional[str] = None

    def _ensure_pad(self) -> PADModel:
        if self._pad is None:
            if self._pad_error is not None:
                raise ModelUnavailableError(self._pad_error)
            try:
                self._pad = PADModel(self.config.pad_path,
                                     session_factory=self._session_factory)
            except ModelUnavailableError as exc:
                # Remember: do not retry a missing model on every frame.
                self._pad_error = str(exc)
                raise
        return self._pad

    def issue_challenge(self) -> ActiveChallenge:
        """Issue a randomised active challenge for registration / login."""
        return self.challenges.issue()

    def verify(self, aligned_crop: np.ndarray, challenge_id: str,
               frames: Dict[str, Any]) -> Dict[str, Any]:
        """Verify liveness for one face.

        ``frames`` carries the challenge evidence: for ``blink``,
        ``{"eye_before": (6,2), "eye_after": (6,2)}`` landmarks; for
        ``head_turn``, ``{"nose_before": (2,), "nose_after": (2,),
        "face_width": float}``. Returns a result dict; never raises
        for a failed check (only model-load failure raises, and the
        caller treats that as reject).
        """
        chal = self.challenges.verify_and_consume(challenge_id)
        if chal is None:
            return {"is_live": False, "reason": "invalid_or_expired_challenge",
                    "pad_score": None, "challenge_kind": None}
        try:
            pad = self._ensure_pad()
        except ModelUnavailableError as exc:
            # FAIL CLOSED: no PAD model → reject, never accept.
            logger.error("PAD model unavailable; rejecting liveness: %s", exc)
            return {"is_live": False, "reason": "pad_model_unavailable",
                    "pad_score": None, "challenge_kind": chal.kind}
        score = pad.live_score(aligned_crop)
        if score < self.config.pad_live_threshold:
            return {"is_live": False, "reason": "pad_score_below_threshold",
                    "pad_score": score, "challenge_kind": chal.kind}
        challenge_ok = self._verify_challenge_motion(chal.kind, frames)
        if not challenge_ok:
            return {"is_live": False, "reason": "challenge_not_performed",
                    "pad_score": score, "challenge_kind": chal.kind}
        return {"is_live": True, "reason": "ok",
                "pad_score": score, "challenge_kind": chal.kind}

    @staticmethod
    def _verify_challenge_motion(kind: str, frames: Dict[str, Any]) -> bool:
        if kind == "blink":
            try:
                ear_before = eye_aspect_ratio(np.asarray(frames["eye_before"]))
                ear_after = eye_aspect_ratio(np.asarray(frames["eye_after"]))
            except (KeyError, ValueError):
                return False
            # A blink is a transient EAR collapse: after-frame EAR must
            # be clearly lower than the before-frame EAR.
            return bool(ear_before > 0.15 and ear_after < 0.6 * ear_before)
        if kind == "head_turn":
            try:
                before = np.asarray(frames["nose_before"], dtype=np.float32)
                after = np.asarray(frames["nose_after"], dtype=np.float32)
                width = float(frames["face_width"])
            except (KeyError, ValueError, TypeError):
                return False
            if width <= 0:
                return False
            shift = float(abs(after[0] - before[0])) / width
            return shift >= 0.10
        return False
