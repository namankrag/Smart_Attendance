"""Focused tests for the teacher TOTP access gate."""

from types import SimpleNamespace
from pathlib import Path


class FakeMFA:
    def __init__(self):
        self.current_level = "aal1"
        self.enroll_calls = []
        self.challenge_calls = []
        self.verify_calls = []

    def get_authenticator_assurance_level(self):
        next_level = "aal2" if self.current_level == "aal2" else "aal1"
        return {"current_level": self.current_level, "next_level": next_level}

    def list_factors(self):
        return {"totp": []}

    def enroll(self, params):
        self.enroll_calls.append(params)
        return {"id": "factor-1", "totp": {"secret": "TESTSECRET234"}}

    def challenge(self, params):
        self.challenge_calls.append(params)
        return {"id": "challenge-1"}

    def verify(self, params):
        self.verify_calls.append(params)
        self.current_level = "aal2"


class FakeClient:
    def __init__(self):
        self.auth = SimpleNamespace(mfa=FakeMFA(), get_session=self.get_session)

    @staticmethod
    def get_session():
        return {"access_token": "aal2-access", "refresh_token": "refresh-token"}


def test_teacher_dashboard_requires_and_verifies_totp(monkeypatch):
    import streamlit as st
    from src.database import teacher_mfa

    st.session_state.clear()
    client = FakeClient()
    monkeypatch.setattr(teacher_mfa, "_mfa_client", lambda: client)
    monkeypatch.setattr(st, "text_input", lambda *args, **kwargs: "123456")
    submit = {"value": False}

    class Form:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(st, "form", lambda *args, **kwargs: Form(), raising=False)
    monkeypatch.setattr(
        st,
        "form_submit_button",
        lambda *args, **kwargs: submit["value"],
        raising=False,
    )

    assert teacher_mfa.require_teacher_mfa() is False
    assert client.auth.mfa.enroll_calls == [
        {"factor_type": "totp", "friendly_name": "Teacher authenticator"}
    ]
    assert st.session_state["_teacher_mfa_pending_secret"] == "TESTSECRET234"

    submit["value"] = True
    assert teacher_mfa.require_teacher_mfa() is False
    assert client.auth.mfa.challenge_calls == [{"factor_id": "factor-1"}]
    assert client.auth.mfa.verify_calls == [
        {
            "factor_id": "factor-1",
            "challenge_id": "challenge-1",
            "code": "123456",
        }
    ]
    assert "_teacher_mfa_pending_secret" not in st.session_state
    assert st.session_state["supabase_access_token"] == "aal2-access"

    assert teacher_mfa.require_teacher_mfa() is True


def test_teacher_mfa_fails_closed_if_supabase_auth_is_unavailable(monkeypatch):
    import streamlit as st
    from src.database import teacher_mfa

    monkeypatch.setattr(
        teacher_mfa,
        "_mfa_client",
        lambda: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )
    monkeypatch.setattr(st, "error", lambda *args, **kwargs: None)

    assert teacher_mfa.require_teacher_mfa() is False


def test_teacher_screen_does_not_open_dashboard_until_mfa_passes(monkeypatch):
    import streamlit as st
    from src.screen import teacher_screen

    st.session_state.clear()
    st.session_state["teacher_data"] = {"teacher_id": "teacher-1"}
    monkeypatch.setattr(teacher_screen, "require_google_login", lambda: None)
    monkeypatch.setattr(teacher_screen, "require_supabase_auth", lambda: None)
    monkeypatch.setattr(teacher_screen, "require_teacher_mfa", lambda: False)
    monkeypatch.setattr(teacher_screen, "style_bg_dashboard", lambda: None)
    monkeypatch.setattr(teacher_screen, "style_base_layout", lambda: None)
    opened = []
    monkeypatch.setattr(teacher_screen, "teacher_dashboard", lambda: opened.append(True))

    teacher_screen.teacher_screen()

    assert opened == []


def test_mfa_migration_enforces_aal2_for_teacher_data():
    migration = (
        Path(__file__).resolve().parents[1] / "migrations" / "008_teacher_mfa.sql"
    ).read_text(encoding="utf-8")

    assert "as restrictive for all to authenticated" in migration
    assert "teachers_require_aal2" in migration
    assert "public.teacher_owns_subject" in migration
    assert "public.teacher_teaches_student" in migration
    assert "multi-factor authentication required" in migration
    assert "auth.jwt()->>'aal'" in migration
