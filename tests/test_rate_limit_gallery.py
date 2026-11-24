"""Phase 0 items 3-4: gallery poisoning + DB rate limiting.
Old code: add_student_face_embedding had no re-auth, no similarity
check, and evicted the original template; there was no rate limiting.
"""
from datetime import datetime, timedelta, timezone
import pytest
from src.database import db as dbmod
from src.database.rate_limit import (
    record_login_attempt, check_login_allowed, is_locked_out,
)


def _set_pin(monkeypatch, fake_db):
    from src.database.auth import hash_pin
    fake_db.tables["students"][1]["pin_hash"] = hash_pin("1234")
    monkeypatch.setattr(dbmod, "supabase", fake_db)


def test_add_face_requires_fresh_reauth(monkeypatch, fake_db):
    _set_pin(monkeypatch, fake_db)
    with pytest.raises(PermissionError):
        dbmod.add_student_face_embedding(
            "22222222-2222-2222-2222-222222222222", [0.2]*128, reauthenticated=False)


def test_add_face_rejects_dissimilar_template(monkeypatch, fake_db):
    _set_pin(monkeypatch, fake_db)
    # Ben's gallery is [0.2]*128 (normalised direction ~ all-equal);
    # a near-orthogonal vector must be rejected.
    dissimilar = [1.0] + [0.0]*127
    with pytest.raises(ValueError):
        dbmod.add_student_face_embedding(
            "22222222-2222-2222-2222-222222222222", dissimilar, reauthenticated=True)


def test_add_face_preserves_original_and_caps_at_five(monkeypatch, fake_db):
    _set_pin(monkeypatch, fake_db)
    sid = "22222222-2222-2222-2222-222222222222"
    base = [0.2]*128
    for i in range(6):
        # Slightly perturbed copies stay cosine-similar to the original.
        vec = [0.2 + (0.001 if j == i else 0.0) for j in range(128)]
        dbmod.add_student_face_embedding(sid, vec, reauthenticated=True)
    gallery = fake_db.tables["students"][1]["face_embedding"]
    assert len(gallery) == 5
    assert gallery[0] == base  # original enrolment template never evicted


def test_rate_limit_allows_under_five_failures(fake_db):
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    for _ in range(4):
        record_login_attempt("1ms21cs001", "pin", False, client=fake_db)
    allowed, _ = check_login_allowed("1MS21CS001", "pin", client=fake_db, now=now)
    assert allowed is True


def test_student_auth_records_login_attempt_with_current_signature(monkeypatch):
    from src.screen import student_auth

    attempts = []
    monkeypatch.setattr(
        student_auth,
        "record_login_attempt",
        lambda identifier, kind, success: attempts.append((identifier, kind, success)),
    )

    student_auth._record_login_attempt("1MS21CS001", False, "pin")

    assert attempts == [("1MS21CS001", "pin", False)]


def test_rate_limit_locks_out_after_five_and_expands(monkeypatch, fake_db):
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    # Seed failures with explicit timestamps (fake client stores them).
    for _ in range(5):
        fake_db.tables["login_attempts"].append({
            "identifier": "1ms21cs001", "kind": "pin", "success": False,
            "attempted_at": (now - timedelta(minutes=1)).isoformat()})
    allowed, retry = check_login_allowed("1MS21CS001", "pin", client=fake_db, now=now)
    assert allowed is False and retry > 0 and retry <= 900
    assert is_locked_out("1MS21CS001", "pin", client=fake_db, now=now) is True
    # After the lockout expires, login is allowed again.
    later = now + timedelta(minutes=16)
    allowed, _ = check_login_allowed("1MS21CS001", "pin", client=fake_db, now=later)
    assert allowed is True
