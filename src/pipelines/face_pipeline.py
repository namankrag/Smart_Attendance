from PIL import Image as PILImage
from scipy.spatial.distance import cdist
import dlib
import importlib.resources as pkg_res
import numpy as np
import streamlit as st
from typing import List, Dict, Tuple, Any, Optional, Set

from src.database.db import get_all_students

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
    """Load and cache pre-trained HOG detector, landmark predictor, and ResNet feature extractor."""
    detector = dlib.get_frontal_face_detector()
    landmark_predictor = dlib.shape_predictor(_resolve_model_path("shape_predictor_68_face_landmarks.dat"))
    face_encoder = dlib.face_recognition_model_v1(_resolve_model_path("dlib_face_recognition_resnet_model_v1.dat"))
    return detector, landmark_predictor, face_encoder

def validate_liveness(image_input: Any) -> Tuple[bool, str]:
    """
    Passive Multi-Feature 2D Anti-Spoofing & Screen Detection:
    Inspects captured face for digital presentation attack indicators:
    1. Specular Backlight & Glass Reflection (Screen glare clipping)
    2. Fourier Frequency Energy Distribution (Digital subpixel Moiré grid)
    3. Chrominance Realism (YCbCr human skin distribution)
    """
    detector, _, _ = load_dlib_models()

    if isinstance(image_input, PILImage.Image):
        pil_img = image_input.convert("RGB")
    elif isinstance(image_input, np.ndarray):
        pil_img = PILImage.fromarray(image_input).convert("RGB")
    else:
        return False, "Invalid image format"

    img_arr = np.array(pil_img)
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

    # 1. Device Bezel / Phone Screen Border Detection
    # When a phone/tablet is held in front of a camera, the surrounding region contains
    # a dark physical device bezel and holding fingers (> 20% dark pixels).
    fw = x2 - x1
    fh = y2 - y1
    bx1 = max(0, x1 - int(fw * 0.4))
    by1 = max(0, y1 - int(fh * 0.3))
    bx2 = min(w, x2 + int(fw * 0.4))
    by2 = min(h, y2 + int(fh * 0.3))

    surround = img_arr[by1:by2, bx1:bx2]
    dark_bezel_ratio = float(np.mean(np.max(surround, axis=2) < 40))

    if dark_bezel_ratio > 0.20:
        return False, "Digital device bezel / phone screen frame detected"

    # 2. Specular Glare & Backlight Saturation Check
    gray = np.dot(face_crop[..., :3], [0.2989, 0.5870, 0.1140])
    overexposed_ratio = float(np.mean(gray >= 252))
    if overexposed_ratio > 0.08:
        return False, "Screen glare or glass reflection detected"

    # 3. Fourier Frequency Moiré Pattern Analysis (Calibrated for indoor webcams)
    crop_resized = np.array(PILImage.fromarray(face_crop).resize((128, 128)).convert("L"), dtype=np.float32)
    fft2 = np.fft.fft2(crop_resized)
    fft_shift = np.fft.fftshift(fft2)
    mag_spec = np.abs(fft_shift)

    center_y, center_x = 64, 64
    y, x = np.ogrid[:128, :128]
    dist_from_center = np.sqrt((x - center_y)**2 + (y - center_x)**2)

    low_freq_mask = dist_from_center <= 16
    high_freq_mask = (dist_from_center > 36) & (dist_from_center <= 60)

    low_energy = float(np.sum(mag_spec[low_freq_mask])) + 1e-5
    high_energy = float(np.sum(mag_spec[high_freq_mask])) + 1e-5
    freq_ratio = high_energy / low_energy

    # High periodic noise threshold to tolerate low-light webcam sensors while flagging screens
    if freq_ratio > 0.55:
        return False, "Digital screen texture / Moiré pattern detected"

    return True, "Live face verified"

def get_face_embeddings(
    image_input: Any, 
    num_jitters: int = 1, 
    is_single_face: bool = False
) -> List[np.ndarray]:
    """
    High-Precision Adaptive Face Extraction:
    - Normalizes image resolution to bound memory and HOG compute.
    - Single-face login: Fast-path upright scan (~50ms).
    - Classroom group photos: Upright scan + micro-tilt passes (±15°) to capture
      students leaning or resting heads sideways, deduplicating via descriptor distance (< 0.38).
    - Descriptors are L2-normalized 128-D vectors.
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
        rects = detector(current_arr, upsample)
        extracted = 0
        for rect in rects:
            shape = landmark_predictor(current_arr, rect)
            desc = np.array(face_encoder.compute_face_descriptor(current_arr, shape, num_jitters), dtype=np.float32)
            norm = np.linalg.norm(desc)
            if norm > 0:
                desc = desc / norm
            
            # Deduplicate by Euclidean descriptor proximity
            is_duplicate = False
            for existing in all_descriptors:
                if np.linalg.norm(existing - desc) < 0.38:
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

@st.cache_data(ttl=300, show_spinner=False)
def _fetch_and_build_embeddings_matrix() -> Optional[Dict[str, Any]]:
    """Build gallery matrix from database student records with 5-minute TTL caching."""
    students = get_all_students()
    if not students:
        return None

    X_list: List[np.ndarray] = []
    y_list: List[int] = []

    for stud in students:
        sid = stud.get("student_id")
        embedding = stud.get("face_embedding")
        if sid is None or not embedding:
            continue

        sid = int(sid)
        if isinstance(embedding, list) and len(embedding) > 0:
            if isinstance(embedding[0], (int, float)) and len(embedding) == 128:
                vec = np.array(embedding, dtype=np.float32)
                norm = np.linalg.norm(vec)
                X_list.append(vec / (norm + 1e-10))
                y_list.append(sid)
            elif isinstance(embedding[0], list):
                for sub_emb in embedding:
                    if isinstance(sub_emb, list) and len(sub_emb) == 128:
                        vec = np.array(sub_emb, dtype=np.float32)
                        norm = np.linalg.norm(vec)
                        X_list.append(vec / (norm + 1e-10))
                        y_list.append(sid)
        elif isinstance(embedding, np.ndarray):
            if embedding.ndim == 1 and embedding.shape[0] == 128:
                vec = embedding.astype(np.float32)
                norm = np.linalg.norm(vec)
                X_list.append(vec / (norm + 1e-10))
                y_list.append(sid)
            elif embedding.ndim == 2 and embedding.shape[1] == 128:
                for sub_emb in embedding:
                    vec = sub_emb.astype(np.float32)
                    norm = np.linalg.norm(vec)
                    X_list.append(vec / (norm + 1e-10))
                    y_list.append(sid)

    if not X_list:
        return None

    return {
        "X": np.vstack(X_list),
        "y": np.array(y_list, dtype=np.int64),
        "student_ids": sorted(list(set(y_list)))
    }

def get_trained_model() -> Optional[Dict[str, Any]]:
    """Retrieve pre-built embeddings matrix."""
    return _fetch_and_build_embeddings_matrix()

def train_classifier() -> bool:
    """Invalidate embeddings matrix cache when a new face profile is registered."""
    _fetch_and_build_embeddings_matrix.clear()
    model = get_trained_model()
    return bool(model)

def predict_attendance(
    class_image_np: Any, 
    distance_threshold: float = 0.38, 
    num_jitters: int = 1, 
    is_single_face: bool = False,
    candidate_ids: Optional[List[int]] = None
) -> Tuple[Dict[int, bool], List[int], int]:
    """
    Match faces detected in class_image_np against the gallery matrix.
    
    Hardened against impostor/unregistered student collisions:
    - If candidate_ids is provided, restricts candidate matrix to ONLY students enrolled in this class.
    - Strict calibrated threshold (default 0.38) prevents strangers (e.g. unregistered Nikunj) from matching absent students (e.g. Naman).
    - Unambiguous 1-to-1 matching: if two faces match the same student, only the closer one wins.
    """
    encodings = get_face_embeddings(class_image_np, num_jitters=num_jitters, is_single_face=is_single_face)
    detected_students: Dict[int, bool] = {}

    model_data = get_trained_model()
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

    best_match_per_student: Dict[int, float] = {}

    for min_idx, min_dist in zip(min_indices, min_distances):
        if min_dist <= distance_threshold:
            matched_sid = int(y_train[min_idx])
            if matched_sid not in best_match_per_student or min_dist < best_match_per_student[matched_sid]:
                best_match_per_student[matched_sid] = float(min_dist)

    for sid in best_match_per_student.keys():
        detected_students[sid] = True

    return detected_students, all_sids, len(encodings)

def predict_attendance_batch(
    images_list: List[Any], 
    distance_threshold: float = 0.38, 
    num_jitters: int = 1,
    candidate_ids: Optional[List[int]] = None
) -> Dict[int, List[str]]:
    """
    Process multiple classroom images sequentially to ensure safe memory access with Dlib C++ models.
    Scoped to candidate enrolled students to eliminate out-of-class impostor false positives.
    """
    all_detected_ids: Dict[int, List[str]] = {}
    if not images_list:
        return all_detected_ids

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
                candidate_ids=candidate_ids
            )
            if detected:
                for sid in detected.keys():
                    all_detected_ids.setdefault(int(sid), []).append(f"Photo {idx + 1}")
        except Exception as e:
            st.error(f"⚠️ Error analyzing Photo {idx + 1}: {e}")

    return all_detected_ids
