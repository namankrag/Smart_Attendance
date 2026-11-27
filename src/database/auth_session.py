"""Google-first login for Smart Attendance (Phase 1, Option A).

Login order, decided by Naman 2026-11-22: **Google sign-in FIRST**
(``st.login``), then USN + face/PIN as the second step. The Google
identity is what makes Row Level Security work: the Supabase Auth JWT
carries ``auth.uid()``, which the 001/003 RLS policies match against
``teachers.auth_user_id`` / ``students.auth_user_id``.

Why this module exists (live finding, 2026-11-22): under the anon key,
``get_student_for_login`` returns ``[]`` for every student — RLS denies
anon outright — so even a correct PIN fails closed and PIN login can
never succeed. The fix is not to weaken RLS; it is to stop using anon
for RLS tables and to send the user's JWT instead. This module is that
wiring.

Flow:
1. :func:`require_google_login` — call at the top of every screen.
   If ``st.user`` is not logged in, it calls ``st.login("google")``
   (Streamlit OIDC: https://docs.streamlit.io/develop/api-reference/user/st.login)
   and stops; Streamlit handles the redirect and returns to the app
   authenticated.
2. The Google ID token is exchanged for a Supabase session with
   ``sign_in_with_id_token`` (Supabase Auth bridge — the same pattern
   SPEC Phase 0 item 8 describes), via :func:`exchange_google_id_token`.
   The resulting Supabase access token is kept ONLY in
   ``st.session_state["supabase_access_token"]`` (a short-lived token,
   never a password hash or an embedding).
3. :func:`get_authenticated_supabase_client` builds a Supabase client
   authenticated with that JWT (``Authorization: Bearer <jwt>`` on the
   PostgREST client) so ``auth.uid()`` resolves server-side.
4. Fail closed: when no Google session / JWT exists, the authenticated
   client raises ``RuntimeError`` instead of silently falling back to
   the anon client for RLS tables. Anon is still the client for
   genuinely public reads only; nothing in this codebase may use it to
   read ``students`` / ``subjects`` / ``attendance_logs``.

Setup Naman still has to do (not code): register Google as a named
Streamlit OIDC provider in ``.streamlit/secrets.toml`` (or Streamlit
Cloud settings) with the shared settings in ``[auth]`` and only the
provider credentials in ``[auth.google]`` — with a named provider
(``st.login("google")``), ``redirect_uri`` and ``cookie_secret`` MUST
live in ``[auth]``; ``[auth.google]`` holds only ``client_id``,
``client_secret`` and ``server_metadata_url`` (putting
``redirect_uri`` / ``cookie_secret`` under ``[auth.google]`` is wrong
and Streamlit ignores them there). Client ID/secret come from the
Google Cloud console, already created 2026-11-22, and the Google
provider must stay enabled in Supabase Auth > Providers (done
2026-11-22). Google Cloud must ALSO list the Streamlit redirect URI
as an Authorized redirect URI — locally
``http://localhost:8501/oauth2callback``, deployed
``https://<app>.streamlit.app/oauth2callback`` — in ADDITION to the
Supabase callback
``https://tomhefyrrwjdyaddlidg.supabase.co/auth/v1/callback``; without
it Google login fails with ``redirect_uri_mismatch``. ``cookie_secret``
must be a strong random string (generate a fresh one per deployment);
never commit ``secrets.toml`` — it is gitignored, and only the
placeholder template in ``.streamlit/secrets.toml.example`` is
committed. Until setup is done :func:`require_google_login` fails
closed with a clear message instead of letting the app run logged-out.

The ``service_role`` key is NEVER used here — it bypasses RLS by
design and stays server-side in the future ML worker only.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import time
from typing import Any, Dict, Optional
from uuid import UUID

import streamlit as st

logger = logging.getLogger(__name__)

# Session-state keys this module owns. Only IDs, names and short-lived
# tokens are ever stored — never password/PIN hashes or embeddings.
SUPABASE_ACCESS_TOKEN_KEY = "supabase_access_token"
SUPABASE_REFRESH_TOKEN_KEY = "supabase_refresh_token"
GOOGLE_ID_TOKEN_KEY = "google_id_token"

# Keys wiped on logout (Phase 1 hygiene): every namespaced key plus the
# login/session keys the screens use. The theme preference is kept —
# it is not identity data.
_LOGOUT_EXPLICIT_KEYS = {
    "student_data",
    "teacher_data",
    "login_type",
    "camera_active",
    "is_logged_in",
    "user_role",
    "show_student_reg",
    "teacher_login_type",
    "current_teacher_tab",
    "teacher_mfa_code",
    "attendance_images",
    "last_saved_attendance",
    SUPABASE_ACCESS_TOKEN_KEY,
    SUPABASE_REFRESH_TOKEN_KEY,
    GOOGLE_ID_TOKEN_KEY,
}
_LOGOUT_PREFIXES = (
    "_teacher_mfa_",
    "smartclass_",
    "reg_",
    "login_pin_",
    "login_face",
    "modal_face_update",
    "voice_",
)

__all__ = [
    "SUPABASE_ACCESS_TOKEN_KEY",
    "SUPABASE_REFRESH_TOKEN_KEY",
    "GOOGLE_ID_TOKEN_KEY",
    "is_google_logged_in",
    "require_google_login",
    "SupabaseNonceMismatchError",
    "require_supabase_auth",
    "get_auth_jwt",
    "get_supabase_user_id",
    "store_supabase_session",
    "exchange_google_id_token",
    "refresh_supabase_session",
    "get_authenticated_supabase_client",
    "get_authenticated_db_client",
    "clear_session_on_logout",
]


def is_google_logged_in() -> bool:
    """True only when Streamlit reports a logged-in OIDC user."""
    user = getattr(st, "user", None)
    if user is None:
        return False
    # st.user.is_logged_in is the documented flag (Streamlit >= 1.33);
    # fall back to "a user object with an email/sub exists".
    logged_in = getattr(user, "is_logged_in", None)
    if logged_in is not None:
        return bool(logged_in)
    return bool(getattr(user, "email", None) or getattr(user, "sub", None))


def require_google_login() -> Any:
    """Gate a screen behind Google sign-in; return the ``st.user`` object.

    When no Google session exists this calls ``st.login("google")`` and
    then ``st.stop()`` — the user is redirected to Google and comes
    back authenticated; the screen body below the call never runs
    logged-out. Returns the logged-in user (``st.user``) otherwise.
    """
    if not is_google_logged_in():
        logger.info("No Google session; redirecting to st.login('google')")
        login = getattr(st, "login", None)
        if login is None:
            raise RuntimeError(
                "Google sign-in is required, but st.login is unavailable "
                "in this Streamlit version; upgrade Streamlit and configure "
                "the Google OIDC provider"
            )
        login("google")
        st.stop()
    return st.user


def get_auth_jwt() -> Optional[str]:
    """Return the Supabase Auth JWT for the signed-in user, or ``None``.

    Only the Supabase access token is valid here. Google OIDC tokens must
    first be exchanged with :func:`exchange_google_id_token`.
    """
    state = getattr(st, "session_state", {}) or {}
    token = state.get(SUPABASE_ACCESS_TOKEN_KEY)
    if isinstance(token, str) and token.strip():
        return token.strip()
    return None


def _user_value(user: Any, key: str) -> Any:
    try:
        return user.get(key)
    except (AttributeError, TypeError):
        return getattr(user, key, None)


def _jwt_is_expired(token: str) -> bool:
    """Treat malformed or near-expiry JWTs as unusable for a new exchange."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        expires_at = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
    except (AttributeError, IndexError, TypeError, ValueError, binascii.Error):
        return True
    return (
        not isinstance(expires_at, (int, float))
        or isinstance(expires_at, bool)
        or expires_at <= time.time() + 30
    )


def _restart_google_login() -> None:
    """Clear Supabase tokens and redirect through a fresh Google OIDC login."""
    state = getattr(st, "session_state", None)
    if state is not None:
        state.pop(SUPABASE_ACCESS_TOKEN_KEY, None)
        state.pop(SUPABASE_REFRESH_TOKEN_KEY, None)

    logout = getattr(st, "logout", None)
    if callable(logout):
        logout()
    else:
        login = getattr(st, "login", None)
        if not callable(login):
            raise RuntimeError("Google sign-in expired. Please sign in again.")
        login("google")
    st.stop()


class SupabaseNonceMismatchError(RuntimeError):
    """Supabase's Google provider needs nonce checking skipped for Streamlit OIDC."""


def require_supabase_auth() -> None:
    """Exchange the current Streamlit OIDC tokens for a Supabase session."""
    if get_auth_jwt():
        return

    user = getattr(st, "user", None)
    tokens = _user_value(user, "tokens")
    id_token = _user_value(tokens, "id")
    if not isinstance(id_token, str) or not id_token.strip():
        raise RuntimeError(
            "Google sign-in tokens are unavailable. Set [auth].expose_tokens = ['id', 'access'] "
            "in Streamlit secrets, then sign in again."
        )
    if _jwt_is_expired(id_token):
        logger.info("Google ID token is expired; restarting Google sign-in")
        _restart_google_login()

    access_token = _user_value(tokens, "access")
    try:
        exchange_google_id_token(
            id_token,
            access_token=access_token if isinstance(access_token, str) else None,
        )
    except Exception as exc:
        error = str(exc).casefold()
        if "nonce" in error and (
            "mismatch" in error or "both exist" in error
        ):
            raise SupabaseNonceMismatchError(
                "Supabase rejected Streamlit's OIDC nonce. Enable 'Skip nonce check' "
                "for Google under Supabase Authentication > Providers. Streamlit "
                "validates this nonce during Google sign-in."
            ) from exc
        raise


def get_supabase_user_id() -> Optional[str]:
    """Read the Supabase user ID from its JWT; RLS validates it on insert."""
    token = get_auth_jwt()
    if not token:
        return None
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        subject = json.loads(base64.urlsafe_b64decode(payload)).get("sub")
        return str(UUID(subject))
    except (AttributeError, IndexError, TypeError, ValueError, binascii.Error) as exc:
        raise RuntimeError("The Supabase session has an invalid user ID.") from exc


def store_supabase_session(
    access_token: str, refresh_token: Optional[str] = None
) -> None:
    """Persist a Supabase session's tokens in session state.

    Only short-lived tokens are stored. Nothing secret is logged.
    """
    if not isinstance(access_token, str) or not access_token.strip():
        raise ValueError("access_token must be a non-empty string")
    st.session_state[SUPABASE_ACCESS_TOKEN_KEY] = access_token.strip()
    if refresh_token:
        st.session_state[SUPABASE_REFRESH_TOKEN_KEY] = refresh_token


def exchange_google_id_token(
    id_token: str,
    client: Any = None,
    *,
    access_token: Optional[str] = None,
    nonce: Optional[str] = None,
) -> Dict[str, Any]:
    """Exchange a Google ID token for a Supabase Auth session.

    Uses ``supabase.auth.sign_in_with_id_token({"provider": "google",
    "token": id_token})`` — the documented Supabase bridge for an
    OIDC login (SPEC Phase 0 item 8). On success the Supabase access
    token is stored via :func:`store_supabase_session` and the session
    dict is returned. Raises on failure (fail closed — no session, no
    DB access).
    """
    if not isinstance(id_token, str) or not id_token.strip():
        raise ValueError("id_token must be a non-empty string")
    if client is None:
        from src.database.config import supabase as _supabase

        client = _supabase
    credentials = {"provider": "google", "token": id_token.strip()}
    if access_token:
        credentials["access_token"] = access_token
    if nonce:
        credentials["nonce"] = nonce
    response = client.auth.sign_in_with_id_token(credentials)
    session = getattr(response, "session", None) or {}
    if isinstance(session, dict):
        access_token = session.get("access_token")
        refresh_token = session.get("refresh_token")
    else:
        access_token = getattr(session, "access_token", None)
        refresh_token = getattr(session, "refresh_token", None)
    if not access_token:
        raise RuntimeError(
            "Google ID token exchange returned no Supabase session"
        )
    store_supabase_session(access_token, refresh_token)
    return {"access_token": access_token, "session": session}


def refresh_supabase_session(client: Any = None) -> bool:
    """Refresh an expired Supabase access token; return False on failure."""
    refresh_token = (getattr(st, "session_state", {}) or {}).get(
        SUPABASE_REFRESH_TOKEN_KEY
    )
    if not refresh_token:
        return False
    if client is None:
        from src.database.config import get_supabase

        client = get_supabase()
    try:
        response = client.auth.refresh_session(refresh_token)
        session = getattr(response, "session", None) or {}
        if isinstance(session, dict):
            access_token = session.get("access_token")
            next_refresh_token = session.get("refresh_token")
        else:
            access_token = getattr(session, "access_token", None)
            next_refresh_token = getattr(session, "refresh_token", None)
        if not access_token:
            return False
        store_supabase_session(access_token, next_refresh_token)
        return True
    except Exception:
        logger.info("Supabase session refresh failed")
        return False


def get_authenticated_supabase_client(jwt: Optional[str] = None) -> Any:
    """Build a Supabase client authenticated with the user's JWT.

    The JWT is sent as ``Authorization: Bearer <jwt>`` on the PostgREST
    client, so Postgres ``auth.uid()`` resolves to the signed-in user
    and the RLS policies apply. Raises ``RuntimeError`` (fail closed)
    when no JWT is available — callers must NOT fall back to the anon
    client for RLS tables in that case. The anon key is still used as
    the client key (it identifies the project, not the user); the JWT
    is what authenticates the user.
    """
    token = jwt or get_auth_jwt()
    if not token:
        raise RuntimeError(
            "Google sign-in is required before accessing attendance data: "
            "no Supabase Auth JWT is available. Sign in with Google first; "
            "the app must not silently use the anon key for RLS tables."
        )
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
    except Exception as exc:
        raise RuntimeError(
            "Supabase URL/key are not configured in Streamlit secrets"
        ) from exc
    from supabase import create_client

    try:
        from src.database.config import get_client_timeout_seconds
        from supabase import ClientOptions
    except Exception:  # pragma: no cover - supabase-py without ClientOptions
        ClientOptions = None  # type: ignore[assignment]
        get_client_timeout_seconds = None  # type: ignore[assignment]

    options = None
    if ClientOptions is not None and get_client_timeout_seconds is not None:
        timeout = get_client_timeout_seconds()
        options = ClientOptions(
            postgrest_client_timeout=timeout,
            storage_client_timeout=timeout,
        )
    client = (
        create_client(url, key, options=options)
        if options is not None
        else create_client(url, key)
    )
    # supabase-py: PostgRESTClient.auth(token) sets the Authorization
    # header for every PostgREST request. That header is what makes
    # auth.uid() work server-side.
    postgrest = getattr(client, "postgrest", None)
    if postgrest is not None and hasattr(postgrest, "auth"):
        postgrest.auth(token)
    return client


def get_authenticated_db_client() -> Any:
    """Authenticated client for the current Google session (fail closed)."""
    return get_authenticated_supabase_client()


def clear_session_on_logout() -> None:
    """Clear every namespaced / identity key and end the Streamlit login.

    Keeps only non-identity preferences (e.g. ``theme``). ``st.logout()``
    clears Streamlit's local identity cookie; Google remains signed in because
    its OIDC metadata does not provide an RP-initiated logout endpoint.
    Absence of ``st.logout`` (older Streamlit) only clears local state.
    """
    state = getattr(st, "session_state", None)
    if state is not None:
        for key in list(state.keys()):
            if key in _LOGOUT_EXPLICIT_KEYS or key.startswith(_LOGOUT_PREFIXES):
                state.pop(key, None)
        # The login routing keys must end up explicitly logged-out.
        state["login_type"] = None
        state["is_logged_in"] = False
    logout = getattr(st, "logout", None)
    if callable(logout):
        logout()
