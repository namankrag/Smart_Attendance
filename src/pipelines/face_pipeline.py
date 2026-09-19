import dlib
import numpy as np
import face_recognition_models
from sklearn.svm import SVC
import streamlit as st

from src.database.db import get_all_students

@st.cache_resource
def load_dilib_models():
    detector = dlib.get_frontal_face_detector()

    sp = dlib.shape_predictor(
        face_recognition_models.pose_predictor_model_location()
    )

    face_rec = dlib.face_recognition_model_v1(
        face_recognition_models.face_recognition_model_location()
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
            y.append(stud.get('student_id'))

    if len(X) == 0:
        return 0

    clf = SVC(kernel = 'linear', probability = True, class_weight = 'balanced')

    try:
        clf.fit(X, y)
    except ValueError:
        pass

    return {'clf' : clf, 'X' : X, 'y' : y}

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

    clf = model_data['clf']
    X_train = model_data['X']
    y_train = model_data['y']

    all_stud = sorted(list(set(y_train)))

    CONFIDENCE_THRESHOLD = 0.70   # SVM probability must be at least 70%
    DISTANCE_THRESHOLD   = 0.55   # Euclidean distance must be within 0.55

    for encode in encodings:
        if len(all_stud) >= 2:
            proba = clf.predict_proba([encode])[0]
            best_idx = int(np.argmax(proba))
            best_conf = proba[best_idx]
            pred_id = int(clf.classes_[best_idx])

            if best_conf < CONFIDENCE_THRESHOLD:
                continue  # not confident enough — reject
        else:
            pred_id = int(all_stud[0])

        # Secondary check: Euclidean distance to the stored embedding
        stud_emb = X_train[y_train.index(pred_id)]
        distance = np.linalg.norm(stud_emb - encode)

        if distance <= DISTANCE_THRESHOLD:
            detected_student[pred_id] = True

    return detected_student, all_stud, len(encodings)
