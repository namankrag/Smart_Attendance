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

    def render_home():
        st.session_state["login_type"] = None
        home_screen(student_page, teacher_page)

    def render_student():
        student_screen()

    def render_teacher():
        teacher_screen()

    home_page = st.Page(
        render_home,
        title="SmartClass",
        url_path="",
        default=True,
        visibility="hidden",
    )
    student_page = st.Page(
        render_student,
        title="Student Portal",
        url_path="students",
        visibility="hidden",
    )
    teacher_page = st.Page(
        render_teacher,
        title="Teacher Portal",
        url_path="teachers",
        visibility="hidden",
    )
    current_page = st.navigation(
        [home_page, student_page, teacher_page],
        position="hidden",
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

    # Keep the current URL and the legacy auth/session routing key in sync.
    # Tracking the previous path lets portal logout and "Go to Home" actions
    # return to the root route, while direct visits to /students or /teachers
    # initialize the matching workspace.
    current_route = current_page.url_path or ""
    route_workspace = {"students": "student", "teachers": "teacher"}
    workspace = route_workspace.get(current_route)
    previous_route = st.session_state.get("_active_route")
    if "login_type" not in st.session_state or current_route != previous_route:
        st.session_state["login_type"] = workspace
    elif workspace is not None and st.session_state.get("login_type") is None:
        st.switch_page(home_page)
    st.session_state["_active_route"] = current_route

    if "is_logged_in" not in st.session_state:
        st.session_state["is_logged_in"] = False

    # Handle join-code deep links (e.g. from QR codes or direct share links).
    # Keep the code in session state while routing so switching to /students
    # does not lose it if Streamlit clears query parameters during navigation.
    join_code = st.query_params.get("join-code")
    if join_code:
        st.session_state["_pending_join_code"] = join_code
        if current_route != "students":
            st.session_state["login_type"] = "student"
            st.switch_page(student_page)

    current_page.run()

    # Wait until the student is authenticated before opening the enrollment
    # dialog, then clear both the URL parameter and its session copy.
    join_code = st.session_state.get("_pending_join_code") or st.query_params.get("join-code")
    if (
        join_code
        and current_route == "students"
        and st.session_state.get("is_logged_in")
        and st.session_state.get("user_role") == "student"
    ):
        st.query_params.clear()
        st.session_state.pop("_pending_join_code", None)
        auto_enroll(join_code)


if __name__ == "__main__":
    main()
