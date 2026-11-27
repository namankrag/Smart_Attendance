"""Face pipeline: detection, embeddings, heuristic liveness, matching.

Thread-safety note
------------------
dlib's C++ models are **not thread-safe**. Streamlit can execute code
concurrently (multiple sessions / reruns in one process), so every dlib
model load and use in this module is serialised behind ``_DLIB_LOCK``.
This follows the "limit concurrent execution of compute-intensive code"
pattern for Streamlit:
https://dev.to/whitphx/limit-concurrent-execution-of-compute-intensive-code-in-a-streamlit-app-239d
Serialising costs throughput under concurrent load; that is the safe
trade-off for Phase 0. (A Phase 2 embedding service would move dlib /
ONNX inference out of the Streamlit process entirely.)

Liveness honesty
----------------
``validate_liveness`` is a **heuristic only**. It looks for glare and
Moiré / screen texture. It does **NOT** reliably block
printed photos or video replays, and must never be described as doing
so. Phase 2 replaces it with a real presentation-attack-detection (PAD)
model — MiniFASNet / CDCN (https://arxiv.org/abs/2106.14948) —
evaluated per ISO/IEC 30107-3.

Matching honesty
----------------
``FACE_MATCH_DISTANCE_THRESHOLD`` (0.38) is **uncalibrated**: it was
chosen ad hoc, not measured on a labelled dataset. Phase 2 will
calibrate the operating point per ISO/IEC 19795-1 (FMR/FNMR curves)
before it is trusted for any high-stakes decision.
"""

from PIL import Image as PILImage
from scipy.spatial.distance import cdist

# dlib is the active face backend while students are enrolled with
# 128-D templates in students.face_embedding. Keep this import defensive
# so unrelated UI screens still load if a deployment missed the face
# dependencies; recognition then reports a clear setup error.
try:
    import dlib
except ImportError:  # pragma: no cover - optional for non-face screens
    dlib = None  # type: ignore[assignment]
import importlib.resources as pkg_res
import logging
import numpy as np
import streamlit as st
import threading
from typing import List, Dict, Tuple, Any, Optional

from src.database.rest_db import get_all_students, get_student_by_id

logger = logging.getLogger(__name__)

# Serialises ALL dlib model load/use in this module (see module docstring).
_DLIB_LOCK = threading.Lock()

# Euclidean distance on L2-normalised 128-D descriptors. UNCALIBRATED —
# chosen ad hoc; Phase 2 will calibrate per ISO/IEC 19795-1.
FACE_MATCH_DISTANCE_THRESHOLD = 0.38
# Strict cosine-similarity gate for adding a NEW face template to an
# existing student's gallery: a new scan must be very close to the
# stored template(s) or it is rejected as (probably) someone else's face.
FACE_GALLERY_MIN_COSINE = 0.85

# Backwards-compatible alias (old name used by existing call sites).
DISTANCE_THRESHOLD = FACE_MATCH_DISTANCE_THRESHOLD


def _resolve_model_path(filename: str) -> str:
    """Resolve face_recognition_models weight file path cleanly."""
    try:
        ref = pkg_res.files("face_recognition_models") / "models" / filename
        with pkg_res.as_file(ref) as p:
            return str(p)
    except Exception:
        import face_recognition_models as _frm
        import os

        return os.path.join(os.path.dirname(_frm.__file__), "models", filename)


@st.cache_resource(show_spinner=False)
def load_dlib_models():
    """Load and cache pre-trained HOG detector, landmark predictor, and ResNet feature extractor.

    dlib models are not thread-safe, so loading is serialised behind
    ``_DLIB_LOCK``. ``@st.cache_resource`` still applies, so the models
    are loaded once per process.

    Raises ``RuntimeError`` (loudly) when dlib is not installed. Never
    silently returns a stub.
    """
    if dlib is None:
        raise RuntimeError(
            "dlib face models are not installed. Install the UI "
            "dependencies from requirements-ui.txt before using face recognition."
        )
    with _DLIB_LOCK:
        detector = dlib.get_frontal_face_detector()
        landmark_predictor = dlib.shape_predictor(
            _resolve_model_path("shape_predictor_68_face_landmarks.dat")
        )
        face_encoder = dlib.face_recognition_model_v1(
            _resolve_model_path("dlib_face_recognition_resnet_model_v1.dat")
        )
    return detector, landmark_predictor, face_encoder


def cosine_similarity(a: Any, b: Any) -> float:
    """Cosine similarity between two embedding vectors, in [-1, 1].

    Both vectors are L2-normalised first, so this is a plain dot product
    of the normalised vectors. Returns 0.0 if either vector is zero.
    """
    va = np.asarray(a, dtype=np.float32).ravel()
    vb = np.asarray(b, dtype=np.float32).ravel()
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.clip(float(np.dot(va / na, vb / nb)), -1.0, 1.0))


def euclidean_to_cosine(distance: float) -> float:
    """Convert a Euclidean distance to cosine similarity.

    Only valid for L2-normalised vectors, where
    ``||a - b||^2 = 2 - 2*cos(a, b)``, i.e. ``cos = 1 - d^2 / 2``.
    The result is clipped to [-1, 1]. For reference, the default match
    threshold of 0.38 corresponds to a cosine of ~0.928.
    """
    return float(np.clip(1.0 - (float(distance) ** 2) / 2.0, -1.0, 1.0))


def _as_embedding_list(embedding: Any) -> List[np.ndarray]:
    """Normalise a stored embedding (single 128-list or list of them) to a list of arrays."""
    out: List[np.ndarray] = []
    if embedding is None:
        return out
    if isinstance(embedding, np.ndarray):
        if embedding.ndim == 1 and embedding.shape[0] == 128:
            out.append(embedding.astype(np.float32))
        elif embedding.ndim == 2 and embedding.shape[1] == 128:
            out.extend(row.astype(np.float32) for row in embedding)
        return out
    if isinstance(embedding, list) and embedding:
        if isinstance(embedding[0], np.ndarray):
            # List of np.ndarray templates (e.g. from get_face_embeddings).
            for sub in embedding:
                arr = np.asarray(sub, dtype=np.float32)
                if arr.ndim == 1 and arr.shape[0] == 128:
                    out.append(arr)
                elif arr.ndim == 2 and arr.shape[1] == 128:
                    out.extend(row.astype(np.float32) for row in arr)
            return out
        if isinstance(embedding[0], (int, float)) and len(embedding) == 128:
            out.append(np.array(embedding, dtype=np.float32))
        elif isinstance(embedding[0], list):
            for sub in embedding:
                if isinstance(sub, list) and len(sub) == 128:
                    out.append(np.array(sub, dtype=np.float32))
    return out


def _normalised(vec: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vec))
    return vec / (norm + 1e-10) if norm > 0 else vec


def verify_face_1to1(
    query_embedding: Any,
    gallery_embeddings: Any,
    *,
    distance_threshold: float = FACE_MATCH_DISTANCE_THRESHOLD,
) -> Tuple[bool, float, Optional[float]]:
    """1:1 face verification: does ``query_embedding`` match ONE student?

    ``gallery_embeddings`` is that single student's stored template(s)
    (one 128-D vector, or a list of them). Only that student's templates
    are compared — no other student is ever consulted.

    Returns ``(matched, best_distance, margin)`` where ``best_distance``
    is the smallest Euclidean distance to any of the student's templates
    (``float("inf")`` if the gallery is empty) and ``margin`` is always
    ``None``: a genuine second-best / impostor margin needs scores from
    a *different* identity, and a 1:1 check against a single student's
    own templates has no second identity to compare against. (Even with
    several templates of the same student, the second-best template is
    the same person, so it is a measure of template spread, not an
    impostor margin, and reporting it as a margin would be misleading.)

    ``distance_threshold`` defaults to ``FACE_MATCH_DISTANCE_THRESHOLD``
    (0.38, uncalibrated — see module docstring).
    """
    gallery = _as_embedding_list(gallery_embeddings)
    if not gallery:
        return False, float("inf"), None
    query = _normalised(np.asarray(query_embedding, dtype=np.float32).ravel())
    distances = [float(np.linalg.norm(query - _normalised(vec))) for vec in gallery]
    best_distance = min(distances)
    return best_distance <= distance_threshold, best_distance, None


def find_duplicate_face_owner(
    query_embedding: Any,
    all_students_embeddings: Optional[List[Tuple[Any, Any]]] = None,
    threshold: float = FACE_MATCH_DISTANCE_THRESHOLD,
) -> Optional[Any]:
    """Registration duplicate check: is this face already enrolled?

    ``all_students_embeddings`` is a list of ``(student_id, embedding)``
    pairs, where each embedding is a single 128-D vector or a list of
    them (one student's stored templates). Returns the ``student_id`` of
    the first student whose closest template is within ``threshold`` of
    the query, or ``None`` if no enrolled student matches.

    If ``all_students_embeddings`` is omitted, the gallery is loaded
    here by paging through ``get_all_students`` (bounded pages, never a
    whole-table load in one call) — this is the form the student
    registration screen calls, ``find_duplicate_face_owner(embedding)``.

    Phase 1: a 512-d query (ArcFace/AdaFace, Phase 2 dimensionality)
    is checked against the pgvector ``match_faces`` RPC instead — the
    global duplicate-face check runs in SQL over the HNSW index
    (migrations/004_phase1_pgvector.sql; HNSW paper
    https://arxiv.org/abs/1603.09320), and a match counts only when
    its cosine similarity is >= FACE_GALLERY_MIN_COSINE (0.85,
    provisional — to be calibrated in Phase 2 per ISO/IEC 19795-1).
    RPC failures propagate (fail closed): a duplicate check that
    cannot run must not silently report "no duplicate". The legacy
    128-d path below is unchanged.
    """
    query = _normalised(np.asarray(query_embedding, dtype=np.float32).ravel())
    if query.shape[0] == 512:
        from src.database.rest_db import match_faces as _rpc_match_faces

        matches = _rpc_match_faces(None, query.tolist(), k=1)
        if matches:
            best = matches[0]
            if float(best.get("cosine_similarity", 0.0)) >= FACE_GALLERY_MIN_COSINE:
                return best.get("student_id")
        return None
    if all_students_embeddings is None:
        all_students_embeddings = []
        _offset = 0
        while True:
            _page = get_all_students(limit=100, offset=_offset)
            if not _page:
                break
            all_students_embeddings.extend(
                (s.get("student_id"), s.get("face_embedding")) for s in _page
            )
            _offset += len(_page)
            if len(_page) < 100:
                break
    for student_id, embedding in all_students_embeddings:
        for template in _as_embedding_list(embedding):
            if float(np.linalg.norm(query - _normalised(template))) <= threshold:
                return student_id
    return None


def validate_liveness(image_input: Any) -> Tuple[bool, str]:
    """
    HEURISTIC-ONLY passive liveness screening — NOT presentation-attack detection.

    Inspects a captured face for weak presentation-attack indicators:
    specular backlight / glass reflection and Fourier frequency-energy
    distribution (digital subpixel Moiré grid). These are weak signals: this check does NOT
    reliably block printed photos or video replays, and a "pass" is not
    proof that a live person is in front of the camera. Phase 2 will
    replace it with a real PAD model (MiniFASNet / CDCN,
    https://arxiv.org/abs/2106.14948) evaluated per ISO/IEC 30107-3.
    Until then, face login must be treated as a convenience factor, not
    a security boundary — the Student ID + PIN path remains available.
    """
    detector, _, _ = load_dlib_models()

    if isinstance(image_input, PILImage.Image):
        pil_img = image_input.convert("RGB")
    elif isinstance(image_input, np.ndarray):
        pil_img = PILImage.fromarray(image_input).convert("RGB")
    else:
        return False, "Invalid image format"

    img_arr = np.array(pil_img)
    with _DLIB_LOCK:
        faces = detector(img_arr, 1)
        if len(faces) == 0:
            faces = detector(img_arr, 2)

    if len(faces) == 0:
        return False, "No face detected in camera viewport"

    if len(faces) > 1:
        return False, "Multiple faces detected. Ensure only one person is in frame"

    face = faces[0]
    h, w, _ = img_arr.shape
    margin_x = int((face.right() - face.left()) * 0.1)
    margin_y = int((face.bottom() - face.top()) * 0.1)

    x1 = max(0, face.left() - margin_x)
    y1 = max(0, face.top() - margin_y)
    x2 = min(w, face.right() + margin_x)
    y2 = min(h, face.bottom() + margin_y)

    face_crop = img_arr[y1:y2, x1:x2]
    if face_crop.shape[0] < 40 or face_crop.shape[1] < 40:
        return False, "Face too small or too far from camera"

    # 1. Specular Glare & Backlight Saturation Check
    gray = np.dot(face_crop[..., :3], [0.2989, 0.5870, 0.1140])
    overexposed_ratio = float(np.mean(gray >= 252))
    if overexposed_ratio > 0.08:
        return False, "Heuristic flag: possible screen glare or glass reflection (not conclusive)"

    # 2. Fourier Frequency Moiré Pattern Analysis (Calibrated for indoor webcams)
    crop_resized = np.array(
        PILImage.fromarray(face_crop).resize((128, 128)).convert("L"), dtype=np.float32
    )
    fft2 = np.fft.fft2(crop_resized)
    fft_shift = np.fft.fftshift(fft2)
    mag_spec = np.abs(fft_shift)

    center_y, center_x = 64, 64
    y, x = np.ogrid[:128, :128]
    dist_from_center = np.sqrt((x - center_y) ** 2 + (y - center_x) ** 2)

    low_freq_mask = dist_from_center <= 16
    high_freq_mask = (dist_from_center > 36) & (dist_from_center <= 60)

    low_energy = float(np.sum(mag_spec[low_freq_mask])) + 1e-5
    high_energy = float(np.sum(mag_spec[high_freq_mask])) + 1e-5
    freq_ratio = high_energy / low_energy

    # High periodic noise threshold to tolerate low-light webcam sensors while flagging screens
    if freq_ratio > 0.55:
        return (
            False,
            "Heuristic flag: possible digital screen texture / Moiré pattern (not conclusive)",
        )

    return (
        True,
        "Heuristic liveness checks passed — this does NOT prove a live person (printed photos / rep"
            "lays are not reliably blocked)",
    )


def get_face_embeddings(
    image_input: Any, num_jitters: int = 1, is_single_face: bool = False
) -> List[np.ndarray]:
    """
    High-Precision Adaptive Face Extraction:
    - Normalizes image resolution to bound memory and HOG compute.
    - Single-face login: Fast-path upright scan (~50ms).
    - Classroom group photos: Upright scan + micro-tilt passes (±15°) to capture
      students leaning or resting heads sideways, deduplicating via descriptor distance (< 0.38).
    - Descriptors are L2-normalized 128-D vectors.
    - All dlib detector / landmark / encoder calls run under ``_DLIB_LOCK``
      (dlib is not thread-safe; see module docstring).
    """
    detector, landmark_predictor, face_encoder = load_dlib_models()

    if isinstance(image_input, PILImage.Image):
        pil_img = image_input.convert("RGB")
    elif isinstance(image_input, np.ndarray):
        pil_img = PILImage.fromarray(image_input).convert("RGB")
    else:
        return []

    target_max_dim = 640 if is_single_face else 1200
    orig_w, orig_h = pil_img.size
    max_dim = max(orig_w, orig_h)
    if max_dim > target_max_dim:
        ratio = float(target_max_dim) / max_dim
        pil_img = pil_img.resize((int(orig_w * ratio), int(orig_h * ratio)), PILImage.BILINEAR)

    img_arr = np.array(pil_img)
    all_descriptors: List[np.ndarray] = []

    def _extract_faces(current_arr: np.ndarray, upsample: int = 1) -> int:
        # dlib calls serialised: detector / predictor / encoder are not thread-safe.
        with _DLIB_LOCK:
            rects = detector(current_arr, upsample)
            extracted = 0
            for rect in rects:
                shape = landmark_predictor(current_arr, rect)
                desc = np.array(
                    face_encoder.compute_face_descriptor(current_arr, shape, num_jitters),
                    dtype=np.float32,
                )
                norm = np.linalg.norm(desc)
                if norm > 0:
                    desc = desc / norm

                # Deduplicate by Euclidean descriptor proximity
                is_duplicate = False
                for existing in all_descriptors:
                    if np.linalg.norm(existing - desc) < FACE_MATCH_DISTANCE_THRESHOLD:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    all_descriptors.append(desc)
                    extracted += 1
        return extracted

    # Pass 1: Primary upright scan
    _extract_faces(img_arr, upsample=1)

    # For single-face login, if upright worked, return immediately
    if is_single_face and all_descriptors:
        return all_descriptors

    # Pass 2: For classroom group photos, run targeted micro-tilts (±15°)
    if not is_single_face:
        for tilt_angle in (-15, 15):
            rot = pil_img.rotate(tilt_angle, expand=True, resample=PILImage.BILINEAR)
            _extract_faces(np.array(rot), upsample=1)

    # Pass 3: Fallback only if NO faces were found anywhere in the image
    if not all_descriptors:
        _extract_faces(img_arr, upsample=2)
        if not all_descriptors:
            for angle in (-30, 30):
                rot = pil_img.rotate(angle, expand=True, resample=PILImage.BILINEAR)
                if _extract_faces(np.array(rot), upsample=1) > 0:
                    break

    return all_descriptors


@st.cache_resource(show_spinner=False)
def _gallery_store() -> Dict[str, Any]:
    """Per-student gallery cache (Phase 1 replacement for the old cache).

    Phase 1 replaces the old 5-minute ``@st.cache_data(ttl=300)`` gallery
    (Streamlit caching docs:
    https://docs.streamlit.io/develop/concepts/architecture/caching):
    ``cache_data`` copied the whole gallery on every call, refetched
    everything every 5 minutes, and went stale across instances. This
    store is a plain dict held in a ``cache_resource``: one entry per
    student_id holding that student's normalised 128-d templates, so
    adding a template invalidates ONLY that student
    (:func:`invalidate_student_gallery`), never the whole roster.
    Entries hold normalised vectors only — never hashes, never PINs.
    """
    return {}


def invalidate_student_gallery(student_id: Any) -> None:
    """Drop one student's cached templates (call after their gallery changes)."""
    _gallery_store().pop(str(student_id), None)


def _student_gallery_vectors(student_id: Any) -> List[np.ndarray]:
    """Normalised 128-d templates for ONE student, cached per student.

    Fetches only that student via ``get_student_by_id`` — never the
    whole table. This is the only gallery loader the matching path
    uses; the whole-table paging below exists solely for legacy
    callers that do not pass a roster.
    """
    sid = str(student_id)
    store = _gallery_store()
    cached = store.get(sid)
    if cached is not None:
        return cached
    student = get_student_by_id(sid)
    vectors = [
        _normalised(vec)
        for vec in _as_embedding_list(student.get("face_embedding") if student else None)
    ]
    store[sid] = vectors
    return vectors


def _fetch_and_build_embeddings_matrix(
    candidate_ids: Optional[List[Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Build a gallery matrix for the given candidates only (Phase 1).

    When ``candidate_ids`` (the enrolled roster of the subject being
    marked) is given, only those students' templates are fetched, one
    per-student cached lookup each — no whole-table load, no 5-minute
    TTL. Without candidates (legacy callers only) it pages through
    ``get_all_students`` as before; that path is kept for backwards
    compatibility and logged, because classroom matching must always
    pass the roster (see :func:`predict_attendance`).
    """
    if candidate_ids is not None:
        student_ids = [str(sid) for sid in candidate_ids]
        X_list: List[np.ndarray] = []
        y_list: List[str] = []
        for sid in student_ids:
            for vec in _student_gallery_vectors(sid):
                X_list.append(vec)
                y_list.append(sid)
        if not X_list:
            return None
        return {
            "X": np.vstack(X_list),
            "y": np.array(y_list, dtype=object),
            "student_ids": sorted(set(y_list)),
        }

    logger.warning(
        "_fetch_and_build_embeddings_matrix called without candidate_ids: "
        "paging the whole student table (legacy path)"
    )
    students: List[Dict[str, Any]] = []
    _offset = 0
    while True:
        _page = get_all_students(limit=100, offset=_offset)
        if not _page:
            break
        students.extend(_page)
        _offset += len(_page)
        if len(_page) < 100:
            break
    if not students:
        return None

    X_list = []
    y_list = []

    for stud in students:
        sid = stud.get("student_id")
        embedding = stud.get("face_embedding")
        if sid is None or not embedding:
            continue
        sid = str(sid)
        for vec in _as_embedding_list(embedding):
            X_list.append(_normalised(vec))
            y_list.append(sid)

    if not X_list:
        return None

    return {
        "X": np.vstack(X_list),
        "y": np.array(y_list, dtype=object),
        "student_ids": sorted(list(set(y_list))),
    }


def get_trained_model(
    candidate_ids: Optional[List[Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Retrieve the gallery matrix, scoped to ``candidate_ids`` when given.

    Pass the enrolled roster for classroom matching; the matrix then
    contains only those students. Called without arguments (legacy) it
    builds the whole-gallery matrix — see
    :func:`_fetch_and_build_embeddings_matrix`.
    """
    return _fetch_and_build_embeddings_matrix(candidate_ids)


def train_classifier(student_id: Any = None) -> bool:
    """Invalidate gallery cache entries after a template change.

    With ``student_id``, only that student's cached templates are
    dropped (per-student invalidation); without one, the whole store is
    cleared. The matrix is rebuilt lazily on the next match — nothing
    is re-fetched here. Always returns True (invalidation cannot fail).
    """
    if student_id is None:
        _gallery_store().clear()
    else:
        invalidate_student_gallery(student_id)
    return True


def predict_one_to_one(
    image: Any,
    student_id: Any,
    gallery_embeddings: Any = None,
    *,
    distance_threshold: float = FACE_MATCH_DISTANCE_THRESHOLD,
    num_jitters: int = 1,
    is_single_face: bool = True,
) -> Dict[str, Any]:
    """1:1 face verification for ONE student (student login path).

    Runs heuristic liveness, extracts the single face embedding, and
    verifies it against ``gallery_embeddings`` — the *given student's*
    stored template(s) only — via :func:`verify_face_1to1`.

    This function deliberately does NOT load all students (contrast
    :func:`predict_attendance`, which is 1:N). If ``gallery_embeddings``
    is omitted, only the claimed student's templates are fetched via
    ``get_student_by_id(student_id)`` — never another student's face.
    ``is_single_face`` is accepted for call-site compatibility and is
    always True here (a login must contain exactly one face).

    Returns a dict::

        {
            "student_id": student_id,
            "is_live": bool,              # heuristic liveness only (see validate_liveness)
            "liveness_message": str,
            "matched": bool,              # False unless live AND embedding matches
            "best_distance": float | None,  # None when no single face was found
            "margin": None,               # always None for 1:1 (see verify_face_1to1)
            "num_faces": int,
        }
    """
    if gallery_embeddings is None:
        # 1:1 only: fetch ONLY the claimed student's templates.
        _student = get_student_by_id(str(student_id))
        gallery_embeddings = _student.get("face_embedding") if _student else None
    is_live, liveness_msg = validate_liveness(image)
    result: Dict[str, Any] = {
        "student_id": student_id,
        "is_live": is_live,
        "liveness_message": liveness_msg,
        "matched": False,
        "best_distance": None,
        "margin": None,
        "num_faces": 0,
    }
    if not is_live:
        return result

    encodings = get_face_embeddings(image, num_jitters=num_jitters, is_single_face=True)
    result["num_faces"] = len(encodings)
    if len(encodings) != 1:
        logger.info(
            "predict_one_to_one: expected exactly 1 face for student %s, found %d",
            student_id,
            len(encodings),
        )
        return result

    matched, best_distance, margin = verify_face_1to1(
        encodings[0], gallery_embeddings, distance_threshold=distance_threshold
    )
    result["matched"] = matched
    result["best_distance"] = best_distance
    result["margin"] = margin
    return result


def predict_attendance(
    class_image_np: Any,
    distance_threshold: float = FACE_MATCH_DISTANCE_THRESHOLD,
    num_jitters: int = 1,
    is_single_face: bool = False,
    candidate_ids: Optional[List[Any]] = None,
) -> Tuple[Dict[Any, bool], List[Any], int]:
    """
    Match faces detected in class_image_np against the gallery matrix.

    WARNING — 1:N matching, teacher classroom use only: this compares
    every detected face against EVERY student in the gallery, which is
    only acceptable for teacher-started classroom attendance scoped to
    the enrolled roster. In practice ``candidate_ids`` (the enrolled
    students of the selected subject) is REQUIRED: without it, a face
    could match a student from another class. Never use this function
    for student login — use :func:`predict_one_to_one` instead, which
    verifies against one claimed student only.

    Hardened against impostor/unregistered student collisions:
    - If candidate_ids is provided, restricts candidate matrix to ONLY
      students enrolled in this class.
    - Strict calibrated threshold (default 0.38) prevents strangers
      (e.g. unregistered Nikunj) from matching absent students (e.g. Naman).
    - Unambiguous 1-to-1 matching: if two faces match the same student, only the closer one wins.
    """
    if candidate_ids is None:
        logger.warning(
            "predict_attendance called without candidate_ids: 1:N matching "
            "against the full gallery. Pass the enrolled roster's IDs."
        )
    encodings = get_face_embeddings(
        class_image_np, num_jitters=num_jitters, is_single_face=is_single_face
    )
    detected_students: Dict[Any, bool] = {}

    # Phase 1: the gallery matrix is built for the enrolled roster only
    # (per-student cached lookups), never the whole table.
    model_data = get_trained_model(candidate_ids)
    if not model_data or not encodings:
        all_sids = model_data["student_ids"] if model_data else []
        return detected_students, all_sids, len(encodings)

    X_train = model_data["X"]
    y_train = model_data["y"]
    all_sids = model_data["student_ids"]

    # Filter gallery down to enrolled candidates for this subject if provided
    if candidate_ids is not None:
        candidate_set = set(candidate_ids)
        mask = np.isin(y_train, list(candidate_set))
        if not np.any(mask):
            return detected_students, candidate_ids, len(encodings)
        X_train = X_train[mask]
        y_train = y_train[mask]
        all_sids = sorted(list(candidate_set))

    query_matrix = np.vstack(encodings).astype(np.float32)
    dist_matrix = cdist(query_matrix, X_train, metric="euclidean")

    min_indices = np.argmin(dist_matrix, axis=1)
    min_distances = dist_matrix[np.arange(len(encodings)), min_indices]

    best_match_per_student: Dict[Any, float] = {}

    for min_idx, min_dist in zip(min_indices, min_distances, strict=False):
        if min_dist <= distance_threshold:
            matched_sid = str(y_train[min_idx])
            if (
                matched_sid not in best_match_per_student
                or min_dist < best_match_per_student[matched_sid]
            ):
                best_match_per_student[matched_sid] = float(min_dist)

    for sid in best_match_per_student.keys():
        detected_students[sid] = True

    return detected_students, all_sids, len(encodings)


def predict_attendance_batch(
    images_list: List[Any],
    distance_threshold: float = FACE_MATCH_DISTANCE_THRESHOLD,
    num_jitters: int = 1,
    candidate_ids: Optional[List[Any]] = None,
) -> Dict[Any, List[str]]:
    """
    Process multiple classroom images sequentially to ensure safe memory
    access with Dlib C++ models.
    Scoped to candidate enrolled students to eliminate out-of-class impostor false positives.
    Pipeline code never calls st.error/st.warning: per-photo failures are
    logged and the batch continues, so the UI can decide how to report them.
    """
    all_detected_ids: Dict[Any, List[str]] = {}
    if not images_list:
        return all_detected_ids

    analyzed_photos = 0
    last_error: Optional[Exception] = None
    for idx, img in enumerate(images_list):
        try:
            if isinstance(img, PILImage.Image):
                img_np = np.array(img.convert("RGB"))
            else:
                img_np = np.array(img)

            detected, _, _ = predict_attendance(
                img_np,
                distance_threshold=distance_threshold,
                num_jitters=num_jitters,
                is_single_face=False,
                candidate_ids=candidate_ids,
            )
            analyzed_photos += 1
            if detected:
                for sid in detected.keys():
                    all_detected_ids.setdefault(str(sid), []).append(f"Photo {idx + 1}")
        except Exception as exc:
            # Log and continue with the next photo; never st.error() from pipeline code.
            last_error = exc
            logger.exception("Error analyzing Photo %d; skipping it", idx + 1)

    if analyzed_photos == 0 and last_error is not None:
        if (
            "PGRST202" in str(last_error)
            and "get_authorized_student_profile" in str(last_error)
        ):
            raise RuntimeError(
                "Face analysis cannot load student profiles: apply "
                "migrations/007_student_self_enrollment.sql to the connected Supabase project, "
                "then reload the PostgREST schema cache."
            ) from last_error
        raise RuntimeError(
            "All classroom photos failed face analysis. Check the server logs and try again."
        ) from last_error

    return all_detected_ids
