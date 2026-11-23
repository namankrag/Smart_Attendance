"""Phase 2.4 (PAD) + 2.5 (voice) tests (mocked models; no weights).

Covers: active-challenge issue/consume/replay/expiry, blink + head-turn
verification, PAD fail-closed when the model is missing, AASIST fail-closed,
ECAPA + diarization with fake loaders, HF_TOKEN required in the worker only,
voice challenge phrases, and no speech-recognition check.
"""
import sys
import time
from pathlib import Path

import numpy as np
import pytest

REPO = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO)

from worker.config import WorkerConfig  # noqa: E402
from worker.face_onnx import ModelUnavailableError  # noqa: E402
from worker.pad import (  # noqa: E402
    ChallengeStore, LivenessVerifier, PADModel, eye_aspect_ratio,
)
from worker.voice_onnx import (  # noqa: E402
    AASISTAntiSpoof, Diarizer, ECAPAEmbedder, VoiceChallengeStore,
    VoiceVerifier,
)


class FakeSession:
    def __init__(self, outputs, output_names=("output",), input_name="input"):
        self._outputs = outputs
        self._output_names = list(output_names)
        self._input_name = input_name
    def get_inputs(self):
        class N:
            name = "input"
        return [N()]
    def get_outputs(self):
        class N:
            def __init__(self, n):
                self.name = n
        return [N(n) for n in self._output_names]
    def run(self, _names, _inputs):
        return self._outputs


def _cfg(tmp_path, **kw):
    return WorkerConfig(model_dir=str(tmp_path), **kw)


# ---------------------------------------------------------------------------
# Eye aspect ratio + active challenge
# ---------------------------------------------------------------------------
def test_eye_aspect_ratio_open_vs_closed():
    # Open eye: tall; closed eye: flat.
    open_eye = np.array([[0, 0], [2, -3], [8, -3], [10, 0], [8, 3], [2, 3]], dtype=float)
    closed_eye = np.array([[0, 0], [2, -0.4], [8, -0.4], [10, 0], [8, 0.4], [2, 0.4]], dtype=float)
    assert eye_aspect_ratio(open_eye) > eye_aspect_ratio(closed_eye)
    assert eye_aspect_ratio(closed_eye) < 0.6 * eye_aspect_ratio(open_eye)


def test_challenge_store_single_use_and_replay_rejected():
    store = ChallengeStore(ttl_seconds=60)
    chal = store.issue()
    assert chal.kind in ("blink", "head_turn")
    assert store.verify_and_consume(chal.id) is not None
    assert store.verify_and_consume(chal.id) is None  # replay rejected


def test_challenge_store_expired_rejected():
    store = ChallengeStore(ttl_seconds=60)
    chal = store.issue()
    chal.expires_at = time.time() - 1
    assert store.verify_and_consume(chal.id) is None


def test_challenge_store_unknown_rejected():
    assert ChallengeStore().verify_and_consume("nope") is None


# ---------------------------------------------------------------------------
# PAD: fail closed without the model; pass with a fake model
# ---------------------------------------------------------------------------
def test_pad_model_missing_weights_fails_loudly(tmp_path):
    with pytest.raises(ModelUnavailableError):
        PADModel(str(tmp_path / "minifasnet.onnx"))


def test_liveness_verifier_fails_closed_without_pad_model(tmp_path):
    cfg = _cfg(tmp_path)
    verifier = LivenessVerifier(cfg)
    chal = verifier.issue_challenge()
    crop = np.zeros((112, 112, 3), dtype=np.uint8)
    out = verifier.verify(crop, chal.id, {})
    assert out["is_live"] is False
    assert out["reason"] == "pad_model_unavailable"


def test_liveness_verifier_rejects_bad_challenge(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "minifasnet.onnx").write_bytes(b"x")
    verifier = LivenessVerifier(cfg)
    crop = np.zeros((112, 112, 3), dtype=np.uint8)
    out = verifier.verify(crop, "unknown-challenge", {})
    assert out["is_live"] is False
    assert out["reason"] == "invalid_or_expired_challenge"


def test_liveness_verifier_accepts_with_fake_pad_and_blink(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "minifasnet.onnx").write_bytes(b"x")
    session = FakeSession([np.array([[0.95]], dtype=np.float32)])
    verifier = LivenessVerifier(cfg, session_factory=lambda *a, **k: session)
    chal = verifier.issue_challenge()
    # Force a blink challenge for determinism.
    chal.kind = "blink"
    verifier.challenges._store[chal.id] = chal
    open_eye = np.array([[0, 0], [2, -3], [8, -3], [10, 0], [8, 3], [2, 3]], dtype=float)
    closed_eye = np.array([[0, 0], [2, -0.4], [8, -0.4], [10, 0], [8, 0.4], [2, 0.4]], dtype=float)
    crop = np.zeros((112, 112, 3), dtype=np.uint8)
    out = verifier.verify(crop, chal.id,
                          {"eye_before": open_eye, "eye_after": closed_eye})
    assert out["is_live"] is True
    assert out["reason"] == "ok"
    assert out["pad_score"] == pytest.approx(0.95)


def test_liveness_verifier_rejects_low_pad_score(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "minifasnet.onnx").write_bytes(b"x")
    session = FakeSession([np.array([[0.1]], dtype=np.float32)])
    verifier = LivenessVerifier(cfg, session_factory=lambda *a, **k: session)
    chal = verifier.issue_challenge()
    out = verifier.verify(np.zeros((112, 112, 3), dtype=np.uint8), chal.id, {})
    assert out["is_live"] is False
    assert out["reason"] == "pad_score_below_threshold"


def test_liveness_verifier_rejects_unperformed_challenge(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "minifasnet.onnx").write_bytes(b"x")
    session = FakeSession([np.array([[0.95]], dtype=np.float32)])
    verifier = LivenessVerifier(cfg, session_factory=lambda *a, **k: session)
    chal = verifier.issue_challenge()
    chal.kind = "head_turn"
    verifier.challenges._store[chal.id] = chal
    out = verifier.verify(np.zeros((112, 112, 3), dtype=np.uint8), chal.id,
                          {"nose_before": [50, 50], "nose_after": [51, 50], "face_width": 100})
    assert out["is_live"] is False
    assert out["reason"] == "challenge_not_performed"


# ---------------------------------------------------------------------------
# Voice: ECAPA, diarization, AASIST, challenges
# ---------------------------------------------------------------------------
def test_ecapa_embedder_fails_loudly_without_speechbrain():
    # speechbrain/torch are not installed in this env: loading must
    # raise ModelUnavailableError, never silently fall back.
    import sys as _sys
    saved = _sys.modules.pop("speechbrain", None)
    _sys.modules["speechbrain"] = None  # None in sys.modules -> ImportError
    try:
        emb = ECAPAEmbedder()
        with pytest.raises(ModelUnavailableError):
            emb.embed(np.zeros(16000, dtype=np.float32))
    finally:
        if saved is not None:
            _sys.modules["speechbrain"] = saved
        else:
            _sys.modules.pop("speechbrain", None)


def test_diarizer_requires_hf_token_in_worker_env(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    cfg = _cfg(tmp_path, hf_token="")
    with pytest.raises(ModelUnavailableError, match="HF_TOKEN"):
        Diarizer(cfg).diarize(np.zeros(16000, dtype=np.float32))


def test_diarizer_uses_injected_loader_when_token_present(tmp_path):
    cfg = _cfg(tmp_path, hf_token="hf_test_token")  # noqa: S106  # dummy token in a test fixture
    diarizer = Diarizer(cfg, pipeline_loader=lambda token: "fake-pipeline")
    assert diarizer._ensure_loaded() == "fake-pipeline"


def test_aasist_missing_weights_fails_loudly(tmp_path):
    with pytest.raises(ModelUnavailableError):
        AASISTAntiSpoof(str(tmp_path / "aasist.onnx"))


def test_aasist_score_from_fake_session(tmp_path):
    (tmp_path / "aasist.onnx").write_bytes(b"x")
    session = FakeSession([np.array([[0.8]], dtype=np.float32)])
    model = AASISTAntiSpoof(str(tmp_path / "aasist.onnx"),
                            session_factory=lambda *a, **k: session)
    assert model.bonafide_score(np.zeros(16000, dtype=np.float32)) == pytest.approx(0.8)


def test_voice_challenge_phrase_random_and_single_use():
    store = VoiceChallengeStore(ttl_seconds=120)
    c1 = store.issue()
    c2 = store.issue()
    assert c1.phrase and c1.phrase != c2.phrase  # random per attempt
    assert len(c1.phrase.split()) == 4
    assert store.verify_and_consume(c1.id) is not None
    assert store.verify_and_consume(c1.id) is None


def test_voice_verifier_fails_closed_without_spoof_model(tmp_path):
    cfg = _cfg(tmp_path)
    verifier = VoiceVerifier(cfg)
    chal = verifier.issue_challenge()
    out = verifier.verify_1to1(np.zeros(16000, dtype=np.float32), chal.id,
                               [np.ones(192, dtype=np.float32)])
    assert out["matched"] is False
    assert out["reason"] == "spoof_model_unavailable"


def test_voice_verifier_rejects_spoofed_audio(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "aasist.onnx").write_bytes(b"x")
    session = FakeSession([np.array([[0.1]], dtype=np.float32)])
    verifier = VoiceVerifier(cfg, session_factory=lambda *a, **k: session)
    chal = verifier.issue_challenge()
    out = verifier.verify_1to1(np.zeros(16000, dtype=np.float32), chal.id,
                               [np.ones(192, dtype=np.float32)])
    assert out["matched"] is False
    assert out["reason"] == "spoof_score_below_threshold"


def test_voice_verifier_accepts_match_with_fake_models(tmp_path):
    cfg = _cfg(tmp_path)
    (tmp_path / "aasist.onnx").write_bytes(b"x")
    session = FakeSession([np.array([[0.9]], dtype=np.float32)])

    class FakeECAPA:
        def embed(self, wav):
            return np.ones(192, dtype=np.float32) / np.sqrt(192)

    verifier = VoiceVerifier(cfg, session_factory=lambda *a, **k: session,
                             embedder=FakeECAPA())
    chal = verifier.issue_challenge()
    out = verifier.verify_1to1(np.zeros(16000, dtype=np.float32), chal.id,
                               [np.ones(192, dtype=np.float32)])
    assert out["matched"] is True
    assert out["reason"] == "ok"
    assert out["cosine"] == pytest.approx(1.0)
    # No speech-recognition check exists: the result must not claim the
    # words were verified (spec: ask Naman before adding it).
    assert "words_verified" not in out and "transcript" not in out
