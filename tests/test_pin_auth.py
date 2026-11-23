"""Phase 0 item 1-2: PIN bypass / mandatory PIN / Argon2id.
These tests FAIL on the old code: old get_all_students() never returned
pin_hash, old create_student() made PIN optional and silently dropped
pin_hash on insert failure, and old hashing was bcrypt only.
"""
import bcrypt
import pytest
from src.database.auth import (
    hash_pin, hash_password, validate_pin, verify_credential,
    is_argon2_hash, is_bcrypt_hash,
)


def test_validate_pin_accepts_4_to_6_digits():
    assert validate_pin("1234") == "1234"
    assert validate_pin(" 123456 ") == "123456"


@pytest.mark.parametrize("bad", ["", "123", "1234567", "12a4", "12 4", "abcd", None, 1234])
def test_validate_pin_rejects_non_numeric_or_wrong_length(bad):
    with pytest.raises(ValueError):
        validate_pin(bad)


def test_pin_roundtrip_argon2id():
    h = hash_pin("1234")
    assert is_argon2_hash(h)
    ok, needs_rehash = verify_credential("1234", h)
    assert ok is True and needs_rehash is False
    assert verify_credential("9999", h)[0] is False


def test_missing_pin_hash_fails_closed():
    # Old code treated a missing pin_hash as "PIN-less, allow login".
    assert verify_credential("1234", None) == (False, False)
    assert verify_credential("1234", "") == (False, False)
    assert verify_credential("", "whatever") == (False, False)


def test_legacy_bcrypt_verifies_but_needs_rehash():
    legacy = bcrypt.hashpw(b"teacher-pass", bcrypt.gensalt()).decode()
    assert is_bcrypt_hash(legacy)
    ok, needs = verify_credential("teacher-pass", legacy)
    assert ok is True and needs is True
    assert verify_credential("wrong", legacy)[0] is False


def test_long_password_not_truncated_at_72_bytes():
    # bcrypt silently truncates >72 bytes; two passwords sharing a
    # 72-byte prefix must NOT verify against the same hash.
    a = "x" * 72 + "A"
    b = "x" * 72 + "B"
    h = hash_password(a)
    assert verify_credential(a, h)[0] is True
    assert verify_credential(b, h)[0] is False


def test_teacher_password_minimum_enforced_in_db(monkeypatch, fake_db):
    import src.database.db as db
    monkeypatch.setattr(db, "supabase", fake_db)
    with pytest.raises(ValueError):
        db.create_teacher("u1", "short", "Name")


def test_get_student_for_login_selects_pin_hash(monkeypatch, fake_db):
    import src.database.db as db
    monkeypatch.setattr(db, "supabase", fake_db)
    # Ben's row must be fetched with pin_hash included.
    row = db.get_student_for_login("1MS21CS002")
    assert row is not None and "pin_hash" in row
    assert "pin_hash" in fake_db.last_select["students"]


def test_get_all_students_never_returns_pin_hash(monkeypatch, fake_db):
    import src.database.db as db
    monkeypatch.setattr(db, "supabase", fake_db)
    rows = db.get_all_students(limit=10)
    assert rows
    assert all("pin_hash" not in r for r in rows)
    assert "pin_hash" not in fake_db.last_select["students"]


def test_create_student_requires_pin(monkeypatch, fake_db):
    import src.database.db as db
    monkeypatch.setattr(db, "supabase", fake_db)
    with pytest.raises((ValueError, TypeError)):
        db.create_student("New", [0.1]*128, None, pin=None)
    with pytest.raises(ValueError):
        db.create_student("New", [0.1]*128, None, pin="12")
    created = db.create_student("New", [0.1]*128, None, pin="1234", usn="1MS21CS099")
    assert created and created[0]["pin_hash"].startswith("$argon2id$")
