"""Phase 2.3 face pipeline tests (mocked ONNX sessions; no weights).

Covers: tiling, NMS, 5-point alignment, feature-norm quality gate,
Hungarian one-to-one matching + margin test, SCRFD decoding from a
fake session, batched embedding in one forward pass, loud failure
when weights are missing, and no silent dlib fallback.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO)

from worker.face_onnx import (  # noqa: E402
    Detection,
    FaceEmbedder,
    ModelUnavailableError,
    ONNXFacePipeline,
    ONNXModel,
    SCRFDDetector,
    align_face,
    feature_norm_quality,
    hungarian_match,
    nms,
    tile_image,
    cosine_similarities,
)
from worker.config import WorkerConfig  # noqa: E402


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def test_tile_image_single_tile_when_small():
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    assert len(tile_image(img)) == 1


def test_tile_image_overlaps_and_covers():
    img = np.zeros((3000, 2000, 3), dtype=np.uint8)
    tiles = tile_image(img, tile_size=1280, overlap=0.25)
    assert len(tiles) > 1
    # Union covers the whole image (last tile reaches each edge).
    assert max(x0 + t.shape[1] for x0, _, t in tiles) == 2000
    assert max(y0 + t.shape[0] for _, y0, t in tiles) == 3000


def test_nms_keeps_highest_score_and_drops_overlap():
    def det(x1, score):
        return Detection(
            bbox=(x1, 0, x1 + 100, 100), landmarks=np.zeros((5, 2), dtype=np.float32), score=score
        )

    kept = nms([det(0, 0.9), det(10, 0.8), det(500, 0.7)])
    assert [d.score for d in kept] == [0.9, 0.7]


def test_align_face_identity_landmarks():
    # Landmarks already at the ArcFace reference points: the aligned
    # crop should be (approximately) the source image itself.
    # Smooth gradient image (no uint8 wrap discontinuities).
    grad = np.tile(np.arange(112, dtype=np.uint8)[None, :, None], (112, 1, 3))
    img = np.ascontiguousarray(grad)
    from worker.face_onnx import _ARC_FACE_DST

    out = align_face(img, _ARC_FACE_DST.copy())
    assert out.shape == (112, 112, 3)
    assert np.abs(out.astype(int) - img.astype(int)).mean() < 3


def test_feature_norm_quality_gate():
    ok, norm = feature_norm_quality(np.ones(512) * 2.0, min_norm=5.0)
    assert ok and norm == pytest.approx(float(np.linalg.norm(np.ones(512) * 2.0)))
    ok, _ = feature_norm_quality(np.ones(512) * 0.01, min_norm=5.0)
    assert not ok


def test_cosine_similarities():
    q = np.array([1.0, 0.0])
    g = np.array([[1.0, 0.0], [0.0, 1.0]])
    assert cosine_similarities(q, g).tolist() == pytest.approx([1.0, 0.0])


def test_hungarian_one_to_one_assignment():
    # Two queries, two students: query 0 is close to student A only,
    # query 1 close to student B only. Greedy "closest wins" could
    # double-assign; Hungarian must not.
    gallery = np.array([[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    owners = ["A", "A", "B"]
    queries = [np.array([1.0, 0.0]), np.array([0.0, 1.0])]
    out = hungarian_match(queries, gallery, owners, cosine_threshold=0.4, margin_threshold=0.05)
    assert out[0]["student_id"] == "A"
    assert out[1]["student_id"] == "B"


def test_hungarian_rejects_below_threshold():
    gallery = np.array([[1.0, 0.0]], dtype=np.float32)
    out = hungarian_match(
        [np.array([0.0, 1.0])], gallery, ["A"], cosine_threshold=0.4, margin_threshold=0.05
    )
    assert out == {}


def test_hungarian_margin_test_rejects_ambiguous():
    # Query is equally close to A and B: no margin → no match.
    gallery = np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    out = hungarian_match(
        [np.array([1.0, 0.0])], gallery, ["A", "B"], cosine_threshold=0.4, margin_threshold=0.05
    )
    assert out == {}


def test_hungarian_empty_inputs():
    assert (
        hungarian_match([], np.zeros((0, 512)), [], cosine_threshold=0.4, margin_threshold=0.05)
        == {}
    )


# ---------------------------------------------------------------------------
# ONNX loading: loud failure, no silent fallback
# ---------------------------------------------------------------------------
def test_onnx_model_missing_weights_fails_loudly(tmp_path):
    with pytest.raises(ModelUnavailableError, match="not found"):
        ONNXModel(str(tmp_path / "nope.onnx"))


def test_onnx_model_missing_library_fails_loudly(tmp_path):
    weights = tmp_path / "m.onnx"
    weights.write_bytes(b"fake")
    with pytest.raises(ModelUnavailableError):
        # session_factory that raises like a missing/broken runtime
        def boom(path, providers=None):
            raise RuntimeError("onnxruntime missing")

        ONNXModel(str(weights), session_factory=boom)


def test_pipeline_dlib_backend_raises_not_falls_back():
    cfg = WorkerConfig(face_backend="dlib")
    with pytest.raises(ModelUnavailableError, match="dlib"):
        ONNXFacePipeline(cfg)


def test_pipeline_missing_weights_raises(tmp_path):
    cfg = WorkerConfig(model_dir=str(tmp_path))
    pipe = ONNXFacePipeline(cfg)
    with pytest.raises(ModelUnavailableError):
        pipe.detect_faces(np.zeros((64, 64, 3), dtype=np.uint8))


# ---------------------------------------------------------------------------
# Fake ONNX sessions
# ---------------------------------------------------------------------------
class FakeIONode:
    def __init__(self, name):
        self.name = name


class FakeSession:
    """Stand-in for onnxruntime.InferenceSession."""

    def __init__(self, outputs, output_names, input_name="input"):
        self._outputs = outputs
        self._output_names = output_names
        self._input_name = input_name
        self.calls = 0

    def get_inputs(self):
        return [FakeIONode(self._input_name)]

    def get_outputs(self):
        return [FakeIONode(n) for n in self._output_names]

    def run(self, _output_names, inputs):
        self.calls += 1
        return self._outputs


def _scrfd_fake_session():
    """SCRFD outputs for a 640x640 input with ONE face at stride 8.

    Anchor (40, 40) grid -> (320, 320); deltas give box
    (300, 300, 340, 340); landmarks at the anchor.
    """
    names = [
        "score_8",
        "score_16",
        "score_32",
        "bbox_8",
        "bbox_16",
        "bbox_32",
        "kps_8",
        "kps_16",
        "kps_32",
    ]
    outs = []
    for stride, n in ((8, 6400), (16, 1600), (32, 400)):
        s = np.zeros(n, dtype=np.float32)
        if stride == 8:
            s[40 * 80 + 40] = 0.95
        outs.append(s)
    for stride, n in ((8, 6400), (16, 1600), (32, 400)):
        b = np.zeros((n, 4), dtype=np.float32)
        if stride == 8:
            b[40 * 80 + 40] = [2.5, 2.5, 2.5, 2.5]
        outs.append(b)
    for stride, n in ((8, 6400), (16, 1600), (32, 400)):
        k = np.zeros((n, 10), dtype=np.float32)
        if stride == 8:
            # Five distinct landmarks around the anchor (in stride
            # units), so alignment is well-defined.
            k[40 * 80 + 40] = [-2, -2, 2, -2, 0, 0, -1, 2, 1, 2]
        outs.append(k)
    return FakeSession(outs, names)


def test_scrfd_detect_decodes_one_face(tmp_path):
    weights = tmp_path / "scrfd.onnx"
    weights.write_bytes(b"x")
    session = _scrfd_fake_session()
    det = SCRFDDetector(str(weights), session_factory=lambda *a, **k: session)
    img = np.zeros((640, 640, 3), dtype=np.uint8)
    dets = det.detect(img)
    assert len(dets) == 1
    assert dets[0].bbox == pytest.approx((300, 300, 340, 340))
    assert dets[0].landmarks.shape == (5, 2)
    assert dets[0].score == pytest.approx(0.95)


def test_scrfd_detect_tiled_offsets_detections(tmp_path):
    weights = tmp_path / "scrfd.onnx"
    weights.write_bytes(b"x")
    session = _scrfd_fake_session()
    det = SCRFDDetector(str(weights), session_factory=lambda *a, **k: session)
    # Square 1000 px tiles (overlap 0) so the fake session's square
    # 640x640 assumption holds per tile; the test verifies tile offsets.
    img = np.zeros((2000, 2000, 3), dtype=np.uint8)
    dets = det.detect_tiled(img, tile_size=1000, overlap=0.0)
    # The fake session reports one face per tile at tile-local
    # (300..340) on a 1000 px tile resized to 640 (scale 0.64), so the
    # global boxes are (468.75..531.25) plus the tile offset.
    assert len(dets) == 4
    boxes = sorted(d.bbox for d in dets)
    assert boxes[0] == pytest.approx((468.75, 468.75, 531.25, 531.25))
    assert boxes[-1] == pytest.approx((1468.75, 1468.75, 1531.25, 1531.25))


def test_embedder_batches_all_crops_in_one_forward(tmp_path):
    weights = tmp_path / "arc.onnx"
    weights.write_bytes(b"x")
    emb = np.ones((3, 512), dtype=np.float32)
    session = FakeSession([emb], ["output"])
    embedder = FaceEmbedder(str(weights), session_factory=lambda *a, **k: session)
    # Three crops, ONE session.run call (batched forward pass, SPEC 2.3).
    crops = [np.zeros((112, 112, 3), dtype=np.uint8) for _ in range(3)]
    vecs, norms = embedder.embed_batch(crops)
    assert session.calls == 1
    assert vecs.shape == (3, 512)
    assert all(float(np.linalg.norm(v)) == pytest.approx(1.0) for v in vecs)
    assert norms[0] == pytest.approx(float(np.sqrt(512)))


def test_pipeline_verify_1to1_with_fake_models(tmp_path):
    cfg = WorkerConfig(
        model_dir=str(tmp_path), face_min_feature_norm=1.0, face_cosine_threshold=0.4
    )
    for name in ("scrfd_10g_bnkps.onnx", "arcface_r100.onnx"):
        (tmp_path / name).write_bytes(b"x")
    scrfd = _scrfd_fake_session()
    emb = np.ones((1, 512), dtype=np.float32)
    arc = FakeSession([emb], ["output"])

    def factory(path, providers=None):
        return scrfd if "scrfd" in path else arc

    pipe = ONNXFacePipeline(cfg, session_factory=factory)
    img = np.zeros((640, 640, 3), dtype=np.uint8)
    gallery = [np.ones(512, dtype=np.float32)]
    out = pipe.verify_1to1(img, gallery)
    assert out["matched"] is True
    assert out["num_faces"] == 1
    assert out["best_cosine"] == pytest.approx(1.0)
