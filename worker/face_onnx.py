"""Face pipeline (Phase 2.3): SCRFD + ArcFace/AdaFace on ONNX Runtime.

Replaces the legacy dlib HOG detector + ResNet (``src/pipelines/
face_pipeline.py``). The legacy path is kept behind the explicit
``FACE_BACKEND=dlib`` flag for the transition — but the ONNX path is
the default, and the worker has no dlib installed, so selecting
``dlib`` here raises loudly instead of silently falling back. Model
loading fails loudly when weights are missing: **weights are NOT
bundled in this repo** and must be baked into the worker image at
build time (see ``worker/README.md``). Nothing here downloads models
at runtime.

Papers / standards (see SPEC REFERENCES):
* SCRFD detection: https://arxiv.org/abs/2105.04714
* ArcFace embeddings: https://arxiv.org/abs/1801.07698
* AdaFace (quality-adaptive margin): https://arxiv.org/abs/2204.00964
* MagFace (feature norm ~= quality): https://arxiv.org/abs/2103.06627
* InsightFace model zoo / SCRFD ONNX layout:
  https://github.com/deepinsight/insightface
* Hungarian one-to-one assignment: ``scipy.optimize.linear_sum_assignment``.
* Threshold calibration: ISO/IEC 19795-1 — see
  ``scripts/evaluate_biometrics.py``; the defaults here are
  UNCALIBRATED starting points.

Pipeline
--------
1. Detect with SCRFD (``SCRFDDetector``), 5-point landmarks.
2. Large group photos: overlapping tiled inference
   (``detect_tiled``) so back-row / small faces are found, then NMS
   merges tile overlaps.
3. Align each face by its 5 landmarks to 112x112 (similarity transform).
4. Batch ALL aligned crops in ONE ArcFace/AdaFace forward pass.
5. Feature-norm quality gate (AdaFace/MagFace style): reject blurry /
   occluded enrolments, flag low-confidence detections.
6. Group matching: Hungarian one-to-one assignment over cosine
   similarity plus a second-best margin test.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

__all__ = [
    "Detection",
    "ONNXModel",
    "SCRFDDetector",
    "FaceEmbedder",
    "ONNXFacePipeline",
    "tile_image",
    "nms",
    "align_face",
    "feature_norm_quality",
    "hungarian_match",
    "cosine_similarities",
    "ModelUnavailableError",
]

# SCRFD (InsightFace) reference points for 112x112 alignment.
_ARC_FACE_DST = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)
SCRFD_STRIDES = (8, 16, 32)


class ModelUnavailableError(RuntimeError):
    """A required model file or library is missing.

    Fail loudly, fail closed: callers must reject the job, never
    silently fall back to another backend or accept the face.
    """


# ---------------------------------------------------------------------------
# Pure geometry / matching helpers (no models — fully unit-testable)
# ---------------------------------------------------------------------------
@dataclass
class Detection:
    """One detected face: box (x1, y1, x2, y2), 5 landmarks (x, y), score."""

    bbox: Tuple[float, float, float, float]
    landmarks: np.ndarray  # (5, 2) float32
    score: float


def tile_image(
    img: np.ndarray, tile_size: int = 1280, overlap: float = 0.25
) -> List[Tuple[int, int, np.ndarray]]:
    """Split ``img`` (H, W, C) into overlapping tiles.

    Tiles overlap by ``overlap`` fraction so faces straddling a tile
    boundary are fully visible in at least one tile; duplicates are
    removed later by NMS. Returns ``[(x0, y0, tile), ...]``.
    """
    h, w = img.shape[:2]
    if max(h, w) <= tile_size:
        return [(0, 0, img)]
    step = max(1, int(tile_size * (1.0 - overlap)))
    tiles = []
    for y0 in range(0, h, step):
        for x0 in range(0, w, step):
            y1 = min(h, y0 + tile_size)
            x1 = min(w, x0 + tile_size)
            tiles.append((x0, y0, img[y0:y1, x0:x1]))
            if x1 >= w:
                break
        if y1 >= h:
            break
    return tiles


def _iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    x1 = np.maximum(a[:, 0], b[0])
    y1 = np.maximum(a[:, 1], b[1])
    x2 = np.minimum(a[:, 2], b[2])
    y2 = np.minimum(a[:, 3], b[3])
    inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / np.maximum(area_a + area_b - inter, 1e-9)


def nms(detections: List[Detection], iou_threshold: float = 0.4) -> List[Detection]:
    """Non-maximum suppression over detections (highest score wins).

    Deduplicates faces found in overlapping tiles and by overlapping
    strides. Pure function — no model needed.
    """
    if not detections:
        return []
    boxes = np.array([d.bbox for d in detections], dtype=np.float32)
    scores = np.array([d.score for d in detections], dtype=np.float32)
    order = np.argsort(-scores)
    keep: List[Detection] = []
    while order.size:
        i = int(order[0])
        keep.append(detections[i])
        if order.size == 1:
            break
        rest = order[1:]
        keep_mask = _iou(boxes[rest], boxes[i]) <= iou_threshold
        order = rest[keep_mask]
    return keep


def _umeyama_similarity(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """Least-squares similarity transform (rotation + uniform scale +
    translation) mapping ``src`` (N, 2) onto ``dst`` (N, 2)."""
    n = src.shape[0]
    src_mean = src.mean(axis=0)
    dst_mean = dst.mean(axis=0)
    src_c = src - src_mean
    dst_c = dst - dst_mean
    cov = (dst_c.T @ src_c) / n
    u, d, vt = np.linalg.svd(cov)
    s = np.eye(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        s[1, 1] = -1
    r = u @ s @ vt
    scale = float(np.sum(d * np.diag(s)) / max(np.sum(src_c**2) / n, 1e-9))
    t = dst_mean - scale * (r @ src_mean)
    m = np.zeros((2, 3), dtype=np.float32)
    m[:2, :2] = scale * r
    m[:, 2] = t
    return m


def align_face(img: np.ndarray, landmarks: np.ndarray, output_size: int = 112) -> np.ndarray:
    """Align a face by its 5 landmarks to ``output_size`` x ``output_size``.

    Similarity transform onto the ArcFace reference points
    (InsightFace default). Implemented with numpy only — no OpenCV
    dependency in the worker. Returns a ``(output_size, output_size, 3)``
    uint8 crop.
    """
    from PIL import Image

    dst = _ARC_FACE_DST * (output_size / 112.0)
    m = _umeyama_similarity(np.asarray(landmarks, dtype=np.float32), dst)
    # Invert: warp output pixels back into the source image (PIL affine
    # takes the inverse mapping).
    inv = np.linalg.inv(np.vstack([m, [0, 0, 1]]))[:2, :]
    pil = Image.fromarray(img)
    aligned = pil.transform(
        (output_size, output_size),
        Image.AFFINE,
        data=(inv[0, 0], inv[0, 1], inv[0, 2], inv[1, 0], inv[1, 1], inv[1, 2]),
        resample=Image.BILINEAR,
    )
    return np.asarray(aligned)


def cosine_similarities(query: np.ndarray, gallery: np.ndarray) -> np.ndarray:
    """Cosine similarity of L2-normalised ``query`` (D,) vs rows of ``gallery`` (N, D)."""
    q = np.asarray(query, dtype=np.float32).ravel()
    g = np.asarray(gallery, dtype=np.float32)
    qn = q / (np.linalg.norm(q) + 1e-10)
    gn = g / (np.linalg.norm(g, axis=1, keepdims=True) + 1e-10)
    return gn @ qn


def feature_norm_quality(embedding_raw: np.ndarray, min_norm: float) -> Tuple[bool, float]:
    """AdaFace/MagFace-style quality gate (arXiv:2204.00964, arXiv:2103.06627).

    The L2 norm of the (pre-normalisation) embedding correlates with
    image quality: blurry / occluded / badly lit faces produce
    low-norm features. Returns ``(passes, norm)``; enrolments below
    ``min_norm`` must be rejected, detections below it flagged.
    """
    norm = float(np.linalg.norm(np.asarray(embedding_raw, dtype=np.float32)))
    return norm >= min_norm, norm


def hungarian_match(
    query_embeddings: Sequence[np.ndarray],
    gallery_embeddings: np.ndarray,
    gallery_owner_ids: Sequence[str],
    *,
    cosine_threshold: float,
    margin_threshold: float,
) -> Dict[int, Dict[str, Any]]:
    """One-to-one group matching (Hungarian + second-best margin test).

    Cost is ``1 - cosine``; ``scipy.optimize.linear_sum_assignment``
    gives the globally optimal one-to-one assignment (each gallery
    template used at most once, each query matched at most once) —
    unlike the old greedy "closest wins" loop, which could assign two
    faces to the same student. A match is accepted only if its cosine
    is >= ``cosine_threshold`` AND it beats the best score from a
    *different* student by >= ``margin_threshold`` (second-best margin
    test, SPEC 2.3 / audit 17).

    Returns ``{query_index: {"student_id", "cosine", "margin"}}`` for
    accepted matches only.
    """
    from scipy.optimize import linear_sum_assignment

    if not query_embeddings or gallery_embeddings.size == 0:
        return {}
    queries = np.stack([np.asarray(q, dtype=np.float32) for q in query_embeddings])
    gallery = np.asarray(gallery_embeddings, dtype=np.float32)
    qn = queries / (np.linalg.norm(queries, axis=1, keepdims=True) + 1e-10)
    gn = gallery / (np.linalg.norm(gallery, axis=1, keepdims=True) + 1e-10)
    sims = qn @ gn.T  # (n_queries, n_gallery) cosine
    cost = 1.0 - sims
    row_ind, col_ind = linear_sum_assignment(cost)
    owners = list(gallery_owner_ids)
    results: Dict[int, Dict[str, Any]] = {}
    for qi, gi in zip(row_ind.tolist(), col_ind.tolist(), strict=False):
        cosine = float(sims[qi, gi])
        if cosine < cosine_threshold:
            continue
        owner = owners[gi]
        # Second-best: best cosine from any OTHER student.
        other = [float(sims[qi, j]) for j in range(sims.shape[1]) if owners[j] != owner]
        second_best = max(other) if other else -1.0
        margin = cosine - second_best
        if margin < margin_threshold:
            continue
        results[int(qi)] = {"student_id": owner, "cosine": cosine, "margin": margin}
    return results


# ---------------------------------------------------------------------------
# ONNX Runtime loading (fails loudly — never silent fallback)
# ---------------------------------------------------------------------------
class ONNXModel:
    """A single ONNX Runtime session loaded from a baked-in weights file.

    ``session_factory`` is injectable for tests (a fake session); in
    production it is ``onnxruntime.InferenceSession``.
    """

    def __init__(self, path: str, session_factory=None):
        if not path or not os.path.isfile(path):
            raise ModelUnavailableError(
                f"ONNX model weights not found: {path!r}. Weights must be "
                "baked into the worker image at build time — the worker "
                "never downloads models at runtime."
            )
        if session_factory is None:
            try:
                import onnxruntime as ort
            except ImportError as exc:
                raise ModelUnavailableError(
                    "onnxruntime is not installed in the worker image"
                ) from exc
            session_factory = ort.InferenceSession
        try:
            self.session = session_factory(path, providers=["CPUExecutionProvider"])
        except Exception as exc:
            raise ModelUnavailableError(f"failed to load ONNX model {path!r}: {exc}") from exc
        self.path = path
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]

    def run(self, blob: np.ndarray) -> List[np.ndarray]:
        return self.session.run(None, {self.input_name: blob})


class SCRFDDetector:
    """SCRFD face detector (arXiv:2105.04714) via ONNX Runtime.

    Decodes the InsightFace SCRFD ONNX layout: per-stride (8/16/32)
    ``score_*`` / ``bbox_*`` / ``kps_*`` outputs, anchor-distance box
    decoding (``x1 = ax - dx*s`` ...). Landmarks are 5 points.
    """

    def __init__(
        self,
        model_path: str,
        session_factory=None,
        score_threshold: float = 0.5,
        nms_threshold: float = 0.4,
    ):
        self.model = ONNXModel(model_path, session_factory=session_factory)
        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold

    # -- decoding --------------------------------------------------------
    def _decode(
        self, outputs: List[np.ndarray], input_hw: Tuple[int, int], scale: float
    ) -> List[Detection]:
        h, w = input_hw
        by_name = {n: o for n, o in zip(self.model.output_names, outputs, strict=False)}
        detections: List[Detection] = []
        for stride in SCRFD_STRIDES:
            scores = by_name.get(f"score_{stride}")
            bboxes = by_name.get(f"bbox_{stride}")
            kps = by_name.get(f"kps_{stride}")
            if scores is None or bboxes is None or kps is None:
                continue
            fh, fw = h // stride, w // stride
            # Anchor grid: (fw*fh, 2) centres.
            ys, xs = np.mgrid[0:fh, 0:fw]
            anchors = np.stack([xs.ravel() * stride, ys.ravel() * stride], axis=1).astype(
                np.float32
            )
            s = scores.reshape(-1)
            keep = np.where(s >= self.score_threshold)[0]
            if keep.size == 0:
                continue
            bb = bboxes.reshape(-1, 4)[keep]
            kp = kps.reshape(-1, 10)[keep]
            an = anchors[keep]
            x1 = (an[:, 0] - bb[:, 0] * stride) / scale
            y1 = (an[:, 1] - bb[:, 1] * stride) / scale
            x2 = (an[:, 0] + bb[:, 2] * stride) / scale
            y2 = (an[:, 1] + bb[:, 3] * stride) / scale
            lm = (an[:, None, :] + kp.reshape(-1, 5, 2) * stride) / scale
            for i in range(keep.size):
                detections.append(
                    Detection(
                        bbox=(float(x1[i]), float(y1[i]), float(x2[i]), float(y2[i])),
                        landmarks=np.asarray(lm[i], dtype=np.float32),
                        score=float(s[keep[i]]),
                    )
                )
        return nms(detections, self.nms_threshold)

    def detect(self, img_rgb: np.ndarray, input_size: int = 640) -> List[Detection]:
        """Detect faces in an RGB image; returns NMS'd detections."""
        h, w = img_rgb.shape[:2]
        scale = input_size / max(h, w)
        nh, nw = max(1, int(h * scale)), max(1, int(w * scale))
        from PIL import Image

        resized = np.asarray(
            Image.fromarray(img_rgb).resize((nw, nh), Image.BILINEAR), dtype=np.float32
        )
        blob = resized.transpose(2, 0, 1)[None, :, :, :]  # NCHW, [0,255] as SCRFD expects
        outputs = self.model.run(blob.astype(np.float32))
        return self._decode(outputs, (nh, nw), scale)

    def detect_tiled(
        self, img_rgb: np.ndarray, tile_size: int = 1280, overlap: float = 0.25
    ) -> List[Detection]:
        """Overlapping tiled inference for high-resolution group photos.

        Back-row faces are small; a single 640 px resize loses them
        (audit 13). Tiles keep full resolution, overlap covers tile
        boundaries, and NMS merges duplicates across tiles.
        """
        all_dets: List[Detection] = []
        for x0, y0, tile in tile_image(img_rgb, tile_size, overlap):
            for det in self.detect(tile):
                x1, y1, x2, y2 = det.bbox
                all_dets.append(
                    Detection(
                        bbox=(x1 + x0, y1 + y0, x2 + x0, y2 + y0),
                        landmarks=det.landmarks + np.array([x0, y0], dtype=np.float32),
                        score=det.score,
                    )
                )
        return nms(all_dets, self.nms_threshold)


class FaceEmbedder:
    """ArcFace (arXiv:1801.07698) / AdaFace (arXiv:2204.00964) embeddings.

    One forward pass for a whole batch of aligned crops (SPEC 2.3):
    ``embed_batch`` stacks crops and runs a single session call.
    Outputs 512-d L2-normalised embeddings; the raw (pre-norm) norms
    are returned alongside for the quality gate.
    """

    def __init__(self, model_path: str, session_factory=None):
        self.model = ONNXModel(model_path, session_factory=session_factory)

    def embed_batch(self, crops: List[np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
        """Returns ``(embeddings (N, 512) L2-normalised, raw_norms (N,))``."""
        if not crops:
            return np.zeros((0, 512), dtype=np.float32), np.zeros((0,), dtype=np.float32)
        batch = np.stack(
            [(np.asarray(c, dtype=np.float32).transpose(2, 0, 1) - 127.5) / 128.0 for c in crops]
        ).astype(np.float32)
        raw = np.asarray(self.model.run(batch)[0], dtype=np.float32)
        norms = np.linalg.norm(raw, axis=1)
        normalised = raw / np.maximum(norms[:, None], 1e-10)
        return normalised.astype(np.float32), norms.astype(np.float32)


class ONNXFacePipeline:
    """Detection + embedding + matching, ONNX default, loud failure.

    ``backend`` must be ``"onnx"``; ``"dlib"`` raises
    :class:`ModelUnavailableError` — the worker image has no dlib, and
    a silent fallback to a different model would change matching
    behaviour without anyone noticing. The legacy dlib path lives only
    in the Streamlit process (``src/pipelines/face_pipeline.py``) as
    the UI-side fallback when the worker is unreachable.
    """

    def __init__(self, config, session_factory=None):
        backend = getattr(config, "face_backend", "onnx")
        if backend != "onnx":
            raise ModelUnavailableError(
                f"face backend {backend!r} is not available in the ML worker "
                "(no dlib here). Set FACE_BACKEND=onnx and bake the ONNX "
                "weights into the worker image."
            )
        self.config = config
        self._session_factory = session_factory
        self._detector: Optional[SCRFDDetector] = None
        self._embedder: Optional[FaceEmbedder] = None

    def _ensure_loaded(self) -> None:
        if self._detector is None:
            self._detector = SCRFDDetector(
                self.config.scrfd_path, session_factory=self._session_factory
            )
        if self._embedder is None:
            self._embedder = FaceEmbedder(
                self.config.face_rec_path, session_factory=self._session_factory
            )

    def detect_faces(self, img_rgb: np.ndarray) -> List[Detection]:
        """Detect (tiled when the image is large)."""
        self._ensure_loaded()
        assert self._detector is not None
        if max(img_rgb.shape[:2]) > 1280:
            return self._detector.detect_tiled(img_rgb)
        return self._detector.detect(img_rgb)

    def embed_detections(
        self, img_rgb: np.ndarray, detections: List[Detection]
    ) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
        """Batch-embed detections; returns embeddings + per-face quality info."""
        self._ensure_loaded()
        assert self._embedder is not None
        crops = [align_face(img_rgb, d.landmarks) for d in detections]
        embeddings, norms = self._embedder.embed_batch(crops)
        quality = []
        for norm in norms:
            # AdaFace/MagFace gate on the raw feature norm itself.
            passes = bool(norm >= self.config.face_min_feature_norm)
            quality.append({"passes_quality_gate": passes, "feature_norm": float(norm)})
        return embeddings, quality

    def verify_1to1(
        self, img_rgb: np.ndarray, gallery_embeddings: Sequence[np.ndarray]
    ) -> Dict[str, Any]:
        """1:1 verification against ONE student's templates only."""
        detections = self.detect_faces(img_rgb)
        if len(detections) != 1:
            return {"matched": False, "num_faces": len(detections), "best_cosine": None}
        embeddings, quality = self.embed_detections(img_rgb, detections)
        if not quality[0]["passes_quality_gate"]:
            return {
                "matched": False,
                "num_faces": 1,
                "best_cosine": None,
                "rejected": "low_quality",
            }
        gallery = np.stack([np.asarray(g, dtype=np.float32) for g in gallery_embeddings])
        sims = cosine_similarities(embeddings[0], gallery)
        best = float(np.max(sims)) if sims.size else -1.0
        return {
            "matched": bool(best >= self.config.face_cosine_threshold),
            "num_faces": 1,
            "best_cosine": best,
            "feature_norm": quality[0]["feature_norm"],
        }

    def match_group(
        self, img_rgb: np.ndarray, gallery: Dict[str, List[np.ndarray]]
    ) -> Dict[str, Any]:
        """Group-photo matching: Hungarian one-to-one + margin test."""
        detections = self.detect_faces(img_rgb)
        embeddings, quality = self.embed_detections(img_rgb, detections)
        gallery_vecs, owners = [], []
        for sid, vecs in gallery.items():
            for v in vecs:
                gallery_vecs.append(np.asarray(v, dtype=np.float32))
                owners.append(str(sid))
        matches = hungarian_match(
            [embeddings[i] for i in range(len(detections)) if quality[i]["passes_quality_gate"]],
            np.stack(gallery_vecs) if gallery_vecs else np.zeros((0, 512), dtype=np.float32),
            owners,
            cosine_threshold=self.config.face_cosine_threshold,
            margin_threshold=self.config.face_margin_threshold,
        )
        # hungarian_match indexes the quality-passing subset; map back.
        passing_idx = [i for i in range(len(detections)) if quality[i]["passes_quality_gate"]]
        detected: Dict[str, Dict[str, Any]] = {}
        for sub_i, m in matches.items():
            detected[m["student_id"]] = {
                "cosine": m["cosine"],
                "margin": m["margin"],
                "face_index": passing_idx[sub_i],
            }
        low_quality = [i for i in range(len(detections)) if not quality[i]["passes_quality_gate"]]
        return {
            "detected": detected,
            "num_faces": len(detections),
            "low_quality_face_indices": low_quality,
            "quality": quality,
        }
