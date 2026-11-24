"""Phase 0 items 5-6, 12: 1:1 face verification, duplicate-face check,
honest liveness wording. Old code: login was 1:N via predict_attendance
over the whole gallery, with no duplicate check at registration.
"""
import math
import numpy as np
import pytest
from src.pipelines.face_pipeline import (
    cosine_similarity, verify_face_1to1, find_duplicate_face_owner,
    FACE_MATCH_DISTANCE_THRESHOLD, FACE_GALLERY_MIN_COSINE,
)


def _unit(vec):
    a = np.array(vec, dtype=float)
    return a / np.linalg.norm(a)


def test_cosine_similarity_identical_is_one():
    v = [0.1, 0.2, 0.3] + [0.0]*125
    assert cosine_similarity(v, v) == pytest.approx(1.0)
    assert cosine_similarity(v, [-x for x in v]) == pytest.approx(-1.0)


def test_verify_1to1_matches_only_claimed_student():
    gallery = [_unit([0.5]*128), _unit([0.51]*128)]
    query = _unit([0.5]*128)
    matched, dist, margin = verify_face_1to1(query, gallery)
    assert matched is True and dist < FACE_MATCH_DISTANCE_THRESHOLD
    assert margin is None  # 1:1 has no second identity to form a margin
    other = _unit([1.0] + [0.0]*127)
    matched, _, _ = verify_face_1to1(other, gallery)
    assert matched is False


def test_verify_1to1_empty_gallery_fails_closed():
    matched, dist, _ = verify_face_1to1(_unit([0.5]*128), [])
    assert matched is False and math.isinf(dist)


def test_find_duplicate_face_owner():
    students = [
        ("uuid-asha", [[0.5]*128]),
        ("uuid-ben", [[0.1]*128]),
    ]
    assert find_duplicate_face_owner(_unit([0.5]*128), students) == "uuid-asha"
    assert find_duplicate_face_owner(_unit([1.0] + [0.0]*127), students) is None


def test_gallery_threshold_is_strict():
    assert FACE_GALLERY_MIN_COSINE >= 0.8


def test_liveness_docstring_is_honest():
    import src.pipelines.face_pipeline as fp
    doc = fp.validate_liveness.__doc__ or ""
    assert "HEURISTIC" in doc.upper() or "heuristic" in doc
    assert "does NOT" in doc or "not reliably" in doc.lower()


def test_liveness_does_not_reject_dark_background_as_device_bezel(monkeypatch):
    import src.pipelines.face_pipeline as fp

    class Face:
        def left(self):
            return 30

        def top(self):
            return 20

        def right(self):
            return 70

        def bottom(self):
            return 70

    monkeypatch.setattr(fp, "load_dlib_models", lambda: (lambda *_: [Face()], None, None))
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    image[15:75, 25:75] = 120

    is_live, message = fp.validate_liveness(image)

    assert is_live, message
