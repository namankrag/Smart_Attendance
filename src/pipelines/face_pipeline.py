import dlib
import numpy as np
import importlib.resources as pkg_res
from sklearn.svm import SVC
import streamlit as st

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
    detector, sp, face_rec = load_dilib_models()
    faces = detector(image_np, 1)

    encodings = []

    for face in faces:
        shape = sp(image_np, face)
        face_descriptor = face_rec.compute_face_descriptor(image_np, shape, 1)

        encodings.append(np.array(face_descriptor))
    return encodings

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

    clf = None
    if len(set(y)) >= 2:
        try:
            clf = SVC(kernel='linear', probability=True, class_weight='balanced')
            clf.fit(X, y)
        except Exception:
            clf = None

    return {'clf': clf, 'X': X, 'y': y}

def train_classifier():
    st.cache_resource.clear()
    model_data = get_trained_model()
    return bool(model_data)

def predict_attendance(class_image_np):
    encodings = get_face_embeddings(class_image_np)
    detected_student = {}

    model_data = get_trained_model()

    if not model_data:
        return detected_student, [], len(encodings)

    X_train = model_data['X']
    y_train = model_data['y']
    clf = model_data.get('clf')

    all_stud = sorted(list(set(y_train)))

    # Standard dlib ResNet-v1 Euclidean distance threshold for matching faces
    DISTANCE_THRESHOLD = 0.60

    for encode in encodings:
        best_student_id = None
        min_distance = float('inf')

        # 1. Metric Nearest-Neighbor matching across all stored embeddings
        for i, stored_emb in enumerate(X_train):
            dist = np.linalg.norm(stored_emb - encode)
            if dist < min_distance:
                min_distance = dist
                best_student_id = y_train[i]

        # 2. If Euclidean distance is within standard threshold (0.60), consider it a valid match
        if min_distance <= DISTANCE_THRESHOLD and best_student_id is not None:
            # Optional double-check with SVM if multi-class classifier is trained
            if clf is not None and len(all_stud) >= 2:
                try:
                    proba = clf.predict_proba([encode])[0]
                    best_idx = int(np.argmax(proba))
                    pred_id = int(clf.classes_[best_idx])
                    # If SVM strongly agrees or metric distance is very small (< 0.50), accept match
                    if pred_id == best_student_id or min_distance <= 0.50:
                        detected_student[best_student_id] = True
                    elif proba[best_idx] >= 0.60:
                        detected_student[pred_id] = True
                except Exception:
                    detected_student[best_student_id] = True
            else:
                detected_student[best_student_id] = True

    return detected_student, all_stud, len(encodings)

