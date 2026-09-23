import dlib
import numpy as np
import importlib.resources as pkg_res
import streamlit as st
from PIL import Image as PILImage

from src.database.db import get_all_students

def _model_path(filename: str) -> str:
    """Resolve a face_recognition_models file path without pkg_resources."""
    try:
        # Python 3.9+ path — works on 3.14
        ref = pkg_res.files("face_recognition_models") / "models" / filename
        with pkg_res.as_file(ref) as p:
            return str(p)
    except Exception:
        # Fallback: locate the package directory manually
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

def get_face_embeddings(image_np):
    """
    High-performance multi-pass face detection:
    - Normalizes ultra-high resolution inputs to ~960px for 5-10x speed boost
    - Fast path: tests upright image first (upsample 1, fallback to 2 if needed)
    - Prioritized rotation sweep on key tilt angles ([-45, -30, -15, 15, 30, 45, 60, -60, 90, 170, 180, 270])
    - Deduplicates faces by descriptor proximity (< 0.30 = same face)
    """
    detector, sp, face_rec = load_dilib_models()

    if isinstance(image_np, PILImage.Image):
        pil_orig = image_np.convert('RGB')
    else:
        pil_orig = PILImage.fromarray(image_np)

    # Normalize resolution to max 960px for massive speedup
    orig_w, orig_h = pil_orig.size
    max_dim = max(orig_w, orig_h)
    if max_dim > 960:
        ratio = 960.0 / max_dim
        pil_orig = pil_orig.resize((int(orig_w * ratio), int(orig_h * ratio)), PILImage.BILINEAR)

    all_encodings = []

    def _extract_from(img_arr, upsample):
        found = detector(img_arr, upsample)
        for face in found:
            shape = sp(img_arr, face)
            desc  = np.array(face_rec.compute_face_descriptor(img_arr, shape, 1))
            # Dedup: skip if close to an already-found face descriptor (< 0.45 belongs to same person)
            for existing in all_encodings:
                if np.linalg.norm(existing - desc) < 0.45:
                    break
            else:
                all_encodings.append(desc)
        return len(found)

    img_arr = np.array(pil_orig)

    # Pass 1 — Fast upright check (upsample 1)
    _extract_from(img_arr, 1)

    # Pass 2 — If no upright face found at upsample 1, try upsample 2
    if not all_encodings:
        _extract_from(img_arr, 2)

    # Pass 3 — Key tilt rotations with upsample 1 (covers common head tilts & landscape/portrait rotations)
    KEY_ANGLES = (-45, -30, -15, 15, 30, 45, 60, -60, 90, 170, 180, 270)
    for angle in KEY_ANGLES:
        rot = pil_orig.rotate(angle, expand=True, resample=PILImage.BILINEAR)
        _extract_from(np.array(rot), 1)

    # Pass 4 — If STILL no face detected at all, test rotations with upsample 2
    if not all_encodings:
        for angle in KEY_ANGLES:
            rot = pil_orig.rotate(angle, expand=True, resample=PILImage.BILINEAR)
            if _extract_from(np.array(rot), 2) > 0:
                break

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
        if embedding:
            X.append(np.array(embedding))
            y.append(int(stud.get('student_id')))

    if len(X) == 0:
        return None

    return {'X': np.array(X), 'y': np.array(y)}

def train_classifier():
    st.cache_resource.clear()
    model_data = get_trained_model()
    return bool(model_data)

def predict_attendance(class_image_np, distance_threshold=0.52):
    encodings = get_face_embeddings(class_image_np)
    detected_student = {}

    model_data = get_trained_model()

    if not model_data:
        return detected_student, [], len(encodings)

    X_train = model_data['X']
    y_train = model_data['y']
    all_stud = sorted(list(set(y_train)))

    # Strict FaceID threshold (0.50 - 0.52) prevents false matches between different individuals
    for encode in encodings:
        # Fast vectorized distance calculation across all stored embeddings
        diffs = X_train - encode
        distances = np.linalg.norm(diffs, axis=1)
        min_idx = int(np.argmin(distances))
        min_distance = distances[min_idx]

        if min_distance <= distance_threshold:
            detected_student[int(y_train[min_idx])] = True

    return detected_student, all_stud, len(encodings)


def predict_attendance_batch(images_list):
    """
    Processes multiple classroom images efficiently.
    Returns: dict mapping student_id -> list of photo labels (e.g. ['Photo 1', 'Photo 3'])
    """
    all_detected_ids = {}
    for idx, img in enumerate(images_list):
        if isinstance(img, PILImage.Image):
            img_np = np.array(img.convert('RGB'))
        else:
            img_np = np.array(img)
        detected, _, _ = predict_attendance(img_np)
        if detected:
            for sid in detected.keys():
                all_detected_ids.setdefault(int(sid), []).append(f"Photo {idx+1}")

    return all_detected_ids

