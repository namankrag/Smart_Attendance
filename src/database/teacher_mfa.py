"""Require a Supabase TOTP factor before opening the teacher dashboard."""

import re
from typing import Any

import streamlit as st

from src.database.auth_session import (
    SUPABASE_ACCESS_TOKEN_KEY,
    SUPABASE_REFRESH_TOKEN_KEY,
    get_authenticated_supabase_client,
    get_auth_jwt,
    store_supabase_session,
)

_PENDING_FACTOR_KEY = "_teacher_mfa_pending_factor_id"
_PENDING_SECRET_KEY = "_teacher_mfa_pending_secret"
_CODE_KEY = "teacher_mfa_code"


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _response_data(response: Any) -> Any:
    return _field(response, "data", response)


def _mfa_client() -> Any:
    """Restore the server-side Supabase Auth session for MFA operations."""
    access_token = get_auth_jwt()
    refresh_token = st.session_state.get(SUPABASE_REFRESH_TOKEN_KEY)
    if not access_token or not refresh_token:
        raise RuntimeError("Supabase session is missing MFA credentials")

    client = get_authenticated_supabase_client(access_token)
    client.auth.set_session(access_token, refresh_token)
    _persist_auth_session(client)
    return client


def _persist_auth_session(client: Any) -> None:
    session = _response_data(client.auth.get_session())
    access_token = _field(session, "access_token")
    refresh_token = _field(session, "refresh_token")
    if access_token and refresh_token:
        store_supabase_session(access_token, refresh_token)


def _begin_enrollment(mfa: Any) -> None:
    response = _response_data(
        mfa.enroll({"factor_type": "totp", "friendly_name": "Teacher authenticator"})
    )
    totp = _field(response, "totp")
    factor_id = _field(response, "id")
    secret = _field(totp, "secret")
    if not factor_id or not secret:
        raise RuntimeError("Supabase returned incomplete MFA enrollment data")
    st.session_state[_PENDING_FACTOR_KEY] = factor_id
    # The seed stays in this server-side session only until enrollment verifies.
    st.session_state[_PENDING_SECRET_KEY] = secret


def _submit_code(mfa: Any, factor_id: str, code: str) -> bool:
    if not re.fullmatch(r"\d{6,8}", code):
        st.error("Enter the current code from your authenticator app.")
        return False
    try:
        challenge = _response_data(mfa.challenge({"factor_id": factor_id}))
        challenge_id = _field(challenge, "id")
        if not challenge_id:
            raise RuntimeError("Supabase returned no MFA challenge")
        mfa.verify(
            {"factor_id": factor_id, "challenge_id": challenge_id, "code": code}
        )
        st.session_state.pop(_PENDING_FACTOR_KEY, None)
        st.session_state.pop(_PENDING_SECRET_KEY, None)
        st.session_state.pop(_CODE_KEY, None)
        return True
    except Exception:
        # Auth/transport exceptions can include request details; never log the OTP.
        st.error("That code could not be verified. Check the code and try again.")
        return False


def require_teacher_mfa() -> bool:
    """Return true only for AAL2 sessions; render enrollment/challenge otherwise."""
    try:
        client = _mfa_client()
        mfa = client.auth.mfa
        aal = _response_data(mfa.get_authenticator_assurance_level())
        current_level = _field(aal, "current_level")
        next_level = _field(aal, "next_level")
        if current_level == "aal2" and next_level == "aal2":
            st.session_state.pop(_PENDING_FACTOR_KEY, None)
            st.session_state.pop(_PENDING_SECRET_KEY, None)
            st.session_state.pop(_CODE_KEY, None)
            return True

        factors = _response_data(mfa.list_factors())
        totp_factors = _field(factors, "totp", []) or []
        verified_factor = next(
            (factor for factor in totp_factors if _field(factor, "status") == "verified"),
            None,
        )

        if next_level == "aal2":
            if verified_factor is None:
                st.error("Multi-factor authentication is unavailable. Please try again later.")
                return False
            factor_id = _field(verified_factor, "id")
            st.subheader("Verify your authenticator")
            st.info("Enter the current code from your authenticator app to continue.")
        else:
            factor_id = st.session_state.get(_PENDING_FACTOR_KEY)
            secret = st.session_state.get(_PENDING_SECRET_KEY)
            if not factor_id or not secret:
                _begin_enrollment(mfa)
                factor_id = st.session_state[_PENDING_FACTOR_KEY]
                secret = st.session_state[_PENDING_SECRET_KEY]
            st.subheader("Set up multi-factor authentication")
            st.info("Add this setup key to an authenticator app, then enter its current code.")
            st.markdown(f"Setup key: `{secret}`")

        with st.form("teacher_mfa_form", clear_on_submit=True):
            code = st.text_input(
                "Authenticator code", type="password", max_chars=8, key=_CODE_KEY
            )
            submitted = st.form_submit_button("Verify and continue")
        if submitted:
            if _submit_code(mfa, factor_id, str(code or "").strip()):
                _persist_auth_session(client)
                st.rerun()
        return False
    except Exception:
        # Fail closed; keep implementation details and credentials out of logs/UI.
        st.error("Multi-factor authentication is unavailable. Please try again later.")
        return False
