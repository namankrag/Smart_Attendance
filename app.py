import sys
import types
import logging

import streamlit as st
from pathlib import Path

# Provide a safe pkg_resources shim for legacy models if not present in runtime
if "pkg_resources" not in sys.modules:
    try:
        import pkg_resources  # noqa: F401  # imported for its side effect: registers the real package in sys.modules
    except ImportError:
        _pkg_shim = types.ModuleType("pkg_resources")
        _pkg_shim.resource_filename = lambda pkg, res: res
        _pkg_shim.require = lambda *a, **kw: []
        _pkg_shim.get_distribution = lambda name: type("D", (), {"version": "0.0.0"})()
        sys.modules["pkg_resources"] = _pkg_shim

from src.screen.home_screen import home_screen
from src.screen.teacher_screen import teacher_screen
from src.screen.student_screen import student_screen
from src.components.dialog_auto_enroll import auto_enroll

# Phase 0 startup schema guard (db agent). Imported defensively: if the
# db layer has not landed it yet, startup must not crash — the guard is
# skipped and the missing guard is logged.
try:
    from src.database.db import check_pin_schema_guard
except ImportError:  # pragma: no cover
    check_pin_schema_guard = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.resolve()

# Login persistence — Phase 1 (Google-first, Option A):
# Login state is persisted via Streamlit's OIDC login (st.login) plus
# the Supabase Auth JWT — see src/database/auth_session.py. The JWT is
# sent as Authorization: Bearer on the PostgREST client so RLS
# auth.uid() resolves; screens are gated behind require_google_login()
# and the app never silently falls back to anon for RLS tables.
# Session state itself holds only an ID + name (no hashes, no
# embeddings). The service_role key stays server-side in the future ML
# worker only, never in Streamlit code.
#   Streamlit st.login: https://docs.streamlit.io/develop/api-reference/user/st.login
#   Supabase RLS: https://supabase.com/docs/guides/database/postgres/row-level-security


def _run_startup_schema_guard() -> None:
    """Fail loudly if the student PIN schema is not ready.

    The guard runs only when Streamlit secrets are available; missing
    secrets (e.g. local tests without a secrets file) skip it instead of
    crashing startup.
    """
    if check_pin_schema_guard is None:
        logger.warning("check_pin_schema_guard is unavailable; startup schema guard skipped")
        return
    try:
        secrets_available = bool(st.secrets)
    except Exception:
        # No secrets file / secrets unavailable — do not crash on missing
        # secrets in tests or local runs without secrets configured.
        logger.info("Streamlit secrets unavailable; startup schema guard skipped")
        return
    if not secrets_available:
        return
    try:
        check_pin_schema_guard()
    except Exception:
        logger.exception("Startup PIN schema guard failed")
        st.error(
            "Startup check failed: the student PIN schema is not ready. "
            "Set a PIN for every active student before starting the app."
        )
        st.stop()


def main():
    # Phase 1: the page icon is the logo only when the file exists; a
    # missing img/ directory must not crash startup (2026-11-22 finding).
    _icon_path = BASE_DIR / "img" / "header.png"
    page_icon = str(_icon_path) if _icon_path.is_file() else "🎓"
    st.set_page_config(
        page_title="SmartClass - AI-Powered Attendance Platform",
        page_icon=page_icon,
        initial_sidebar_state="collapsed",
        layout="wide",
    )

    _run_startup_schema_guard()

    # Root CSS reset to remove Streamlit's default white header and decoration banners
    st.markdown(
        """
        <style>
            [data-testid="stHeader"] {
                background: transparent !important;
                background-color: transparent !important;
            }
            [data-testid="stDecoration"] {
                display: none !important;
            }
            [data-testid="stAppDeployButton"] {
                display: none !important;
            }
            #MainMenu {
                visibility: hidden !important;
            }
            footer {
                visibility: hidden !important;
            }
        </style>
    """,
        unsafe_allow_html=True,
    )

    # Initialize fundamental session state keys
    if "login_type" not in st.session_state:
        st.session_state["login_type"] = None
    if "is_logged_in" not in st.session_state:
        st.session_state["is_logged_in"] = False

    # Route according to workspace selection
    current_workspace = st.session_state.get("login_type")
    if current_workspace == "teacher":
        teacher_screen()
    elif current_workspace == "student":
        student_screen()
    else:
        home_screen()

    # Handle join-code deep links (e.g. from QR codes or direct share links).
    # Read the param once; clear it as soon as the auto-enroll dialog opens
    # so the code does not linger in the URL / re-trigger on refresh.
    join_code = st.query_params.get("join-code")
    if join_code:
        if st.session_state.get("login_type") != "student":
            st.session_state["login_type"] = "student"
            st.rerun()
        elif (
            st.session_state.get("is_logged_in") and st.session_state.get("user_role") == "student"
        ):
            st.query_params.clear()
            auto_enroll(join_code)


if __name__ == "__main__":
    main()
