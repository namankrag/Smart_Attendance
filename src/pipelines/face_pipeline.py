from concurrent.futures import ThreadPoolExecutor
from PIL import Image as PILImage
from scipy.spatial.distance import cdist
import dlib
import importlib.resources as pkg_res
import numpy as np
import streamlit as st

from src.database.db import get_all_students

def _model_path(filename: str) -> str:
    """Resolve a face_recognition_models file path without pkg_resources."""
    try:
        ref = pkg_res.files("face_recognition_models") / "models" / filename
        with pkg_res.as_file(ref) as p:
            return str(p)
    except Exception:
        import face_recognition_models as _frm
        import os
        return os.path.join(os.path.dirname(_frm.__file__), "models", filename)

@st.cache_resource
def load_dilib_models():
    detector = dlib.get_frontal_face_detector()
    sp = dlib.shape_predictor(
        _model_path("shape_predictor_68_face_landmarks.dat")
    )
    face_rec = dlib.face_recognition_model_v1(
        _model_path("dlib_face_recognition_resnet_model_v1.dat")
    )
    return detector, sp, face_rec

def get_face_embeddings(image_np, num_jitters=1, is_single_face=False):
    """
    Latency-Optimized Multi-Pass Face Detection and Feature Extraction:
    - Normalizes image resolution (640px for single-face login, 960px for group photos)
    - Fast Path: Upright check (upsample 1). If is_single_face and found, exits immediately (~30-50ms)
    - Fallback: Upsample 2 if needed, followed by prioritized small tilt angles
    - num_jitters: resamples random crops for robust landmark and feature invariance
    - Deduplicates faces by descriptor proximity (< 0.40 = same face)
    """
    detector, sp, face_rec = load_dilib_models()

    if isinstance(image_np, PILImage.Image):
        pil_orig = image_np.convert('RGB')
    else:
        pil_orig = PILImage.fromarray(image_np)

    # Resolution target: 640px is extremely fast for single-person login/selfies
    target_dim = 640 if is_single_face else 960
    orig_w, orig_h = pil_orig.size
    max_dim = max(orig_w, orig_h)
    if max_dim > target_dim:
        ratio = float(target_dim) / max_dim
        pil_orig = pil_orig.resize((int(orig_w * ratio), int(orig_h * ratio)), PILImage.BILINEAR)

    all_encodings = []

    def _extract_from(img_arr, upsample):
        found = detector(img_arr, upsample)
        for face in found:
            shape = sp(img_arr, face)
            desc = np.array(face_rec.compute_face_descriptor(img_arr, shape, num_jitters))
            for existing in all_encodings:
                if np.linalg.norm(existing - desc) < 0.40:
                    break
            else:
                all_encodings.append(desc)
        return len(found)

    img_arr = np.array(pil_orig)

    ALL_TILT_ANGLES = (-15, 15, -30, 30, -45, 45, -60, 60, 90, 170, 180, 270)

    # Pass 1 — Fast upright check (upsample 1)
    _extract_from(img_arr, 1)
    if is_single_face and all_encodings:
        return all_encodings

    # Pass 2 — If single-face mode and upright wasn't found, try upsample 2 upright
    if is_single_face and not all_encodings:
        if _extract_from(img_arr, 2) > 0:
            return all_encodings

    # Pass 3 — Angle sweep (-45° to 270°):
    # - In single-face mode: executes only if upright had no face, and stops immediately once found.
    # - In classroom mode: scans tilt angles to detect students looking sideways/tilted, deduplicating them.
    for angle in ALL_TILT_ANGLES:
        rot = pil_orig.rotate(angle, expand=True, resample=PILImage.BILINEAR)
        if _extract_from(np.array(rot), 1) > 0 and is_single_face:
            return all_encodings

    # Pass 4 — Fallback for classroom photo if no face at all was found across all passes
    if not all_encodings:
        _extract_from(img_arr, 2)

    return all_encodings


@st.cache_resource
def get_trained_model():
    X = []
    y = []

    student_db = get_all_students()

    if not student_db:
        return None

    for stud in student_db:
        embedding = stud.get('face_embedding')
        sid = stud.get('student_id')
        if not embedding or sid is None:
            continue

        sid = int(sid)
        if isinstance(embedding, list) and len(embedding) > 0:
            if isinstance(embedding[0], (int, float)) and len(embedding) == 128:
                X.append(np.array(embedding, dtype=np.float64))
                y.append(sid)
            elif isinstance(embedding[0], list):
                for sub_emb in embedding:
                    if len(sub_emb) == 128:
                        X.append(np.array(sub_emb, dtype=np.float64))
                        y.append(sid)
        elif isinstance(embedding, np.ndarray):
            if embedding.ndim == 1 and embedding.shape[0] == 128:
                X.append(embedding.astype(np.float64))
                y.append(sid)
            elif embedding.ndim == 2 and embedding.shape[1] == 128:
                for sub_emb in embedding:
                    X.append(sub_emb.astype(np.float64))
                    y.append(sid)

    if len(X) == 0:
        return None

    return {'X': np.array(X, dtype=np.float64), 'y': np.array(y, dtype=np.int64)}


def train_classifier():
    st.cache_resource.clear()
    model_data = get_trained_model()
    return bool(model_data)


def predict_attendance(class_image_np, distance_threshold=0.44, num_jitters=1, is_single_face=False):
    """
    Predict attendance for faces found in class_image_np.
    Uses BLAS-accelerated cdist matrix calculations for instantaneous distance evaluation.
    """
    encodings = get_face_embeddings(class_image_np, num_jitters=num_jitters, is_single_face=is_single_face)
    detected_student = {}

    model_data = get_trained_model()

    if not model_data or not encodings:
        return detected_student, [] if not model_data else sorted(list(set(model_data['y'].tolist()))), len(encodings)

    X_train = model_data['X']
    y_train = model_data['y']
    all_stud = sorted(list(set(y_train.tolist())))

    enc_matrix = np.array(encodings, dtype=np.float64)
    # Hardware-accelerated OpenBLAS pairwise distance computation
    dist_matrix = cdist(enc_matrix, X_train, metric='euclidean')

    min_indices = np.argmin(dist_matrix, axis=1)
    min_distances = dist_matrix[np.arange(len(encodings)), min_indices]

    for min_idx, min_dist in zip(min_indices, min_distances):
        if min_dist <= distance_threshold:
            detected_student[int(y_train[min_idx])] = True

    return detected_student, all_stud, len(encodings)


def predict_attendance_batch(images_list, distance_threshold=0.45, num_jitters=1):
    """
    Processes multiple classroom images in parallel using ThreadPoolExecutor.
    Returns: dict mapping student_id -> list of photo labels (e.g. ['Photo 1', 'Photo 3'])
    """
    all_detected_ids = {}
    if not images_list:
        return all_detected_ids

    def _process_single(item):
        idx, img = item
        if isinstance(img, PILImage.Image):
            img_np = np.array(img.convert('RGB'))
        else:
            img_np = np.array(img)
        detected, _, _ = predict_attendance(img_np, distance_threshold=distance_threshold, num_jitters=num_jitters, is_single_face=False)
        return idx, detected

    max_workers = min(4, len(images_list))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = executor.map(_process_single, enumerate(images_list))

    for idx, detected in results:
        if detected:
            for sid in detected.keys():
                all_detected_ids.setdefault(int(sid), []).append(f"Photo {idx+1}")

    return all_detected_ids

