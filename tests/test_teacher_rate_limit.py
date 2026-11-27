import pytest


def test_teacher_login_checks_rate_limit_before_password_verification(monkeypatch):
    from src.screen import teacher_auth

    checked = []
    recorded = []
    monkeypatch.setattr(
        teacher_auth, "check_login_allowed",
        lambda identifier, kind: checked.append((identifier, kind)) or (False, 300),
    )
    monkeypatch.setattr(
        teacher_auth, "record_login_attempt",
        lambda *args, **kwargs: recorded.append((args, kwargs)),
    )
    monkeypatch.setattr(
        teacher_auth, "teacher_login_with_rehash",
        lambda *args: pytest.fail("password verification ran while locked out"),
    )

    teacher, needs_rehash, status, _ref = teacher_auth._authenticate_teacher(
        "teacher@example", "guess"
    )

    assert checked == [("teacher@example", "teacher")]
    assert recorded == []
    assert (teacher, needs_rehash, status) == (None, False, "limited")


def test_teacher_login_records_failed_password_attempt(monkeypatch):
    from src.screen import teacher_auth

    recorded = []
    monkeypatch.setattr(teacher_auth, "check_login_allowed", lambda *a, **k: (True, 0))
    monkeypatch.setattr(teacher_auth, "teacher_login_with_rehash", lambda *a: None)
    monkeypatch.setattr(
        teacher_auth, "record_login_attempt",
        lambda identifier, **kwargs: recorded.append((identifier, kwargs)),
    )

    teacher, needs_rehash, status, _ref = teacher_auth._authenticate_teacher(
        "teacher@example", "wrong-password"
    )

    assert recorded == [("teacher@example", {"kind": "teacher", "success": False})]
    assert (teacher, needs_rehash, status) == (None, False, "invalid")
