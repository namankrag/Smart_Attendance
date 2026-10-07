import sys
import types
import streamlit as st
from pathlib import Path

# Provide a safe pkg_resources shim for legacy models if not present in runtime
if "pkg_resources" not in sys.modules:
    try:
        import pkg_resources
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

BASE_DIR = Path(__file__).parent.resolve()

def main():
    st.set_page_config(
        page_title="SmartClass - AI-Powered Attendance Platform",
        page_icon=str(BASE_DIR / "img" / "header.png"),
        initial_sidebar_state="collapsed",
        layout="wide"
    )

    # Root CSS reset to remove Streamlit's default white header and decoration banners
    st.markdown("""
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
    """, unsafe_allow_html=True)

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

    # Handle join-code deep links (e.g. from QR codes or direct share links)
    join_code = st.query_params.get("join-code")
    if join_code:
        if st.session_state.get("login_type") != "student":
            st.session_state["login_type"] = "student"
            st.rerun()
        elif st.session_state.get("is_logged_in") and st.session_state.get("user_role") == "student":
            auto_enroll(join_code)

if __name__ == "__main__":
    main()
