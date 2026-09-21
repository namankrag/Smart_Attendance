import sys
import types

# Several older packages (webrtcvad, face_recognition_models) use pkg_resources
# which was removed in Python 3.14. Inject a minimal shim before any local
# imports trigger those packages.
if "pkg_resources" not in sys.modules:
    _pkg_shim = types.ModuleType("pkg_resources")
    _pkg_shim.resource_filename = lambda package_or_requirement, resource_name: resource_name
    _pkg_shim.require = lambda *a, **kw: []
    _pkg_shim.get_distribution = lambda name: type("D", (), {"version": "0.0.0"})()
    sys.modules["pkg_resources"] = _pkg_shim

import streamlit as st
from pathlib import Path

from src.screen.home_screen import home_screen
from src.screen.teacher_screen import teacher_screen
from src.screen.student_screen import student_screen
from src.components.dialog_auto_enroll import auto_enroll

BASE_DIR = Path(__file__).parent.resolve()

def main():
    st.set_page_config(
        page_title = 'SmartClass - Making Attendance faster using AI',
        page_icon = str(BASE_DIR / "img" / "header.png"),
        initial_sidebar_state = "expanded",
    )

    if 'login_type' not in st.session_state:
        st.session_state['login_type'] = None

    match st.session_state['login_type']:
        case 'teacher':
            teacher_screen()
        case 'student':
            student_screen()
        case None:
            home_screen()

    join_code = st.query_params.get('join-code')
    if join_code:
        if st.session_state.login_type != 'student':
            st.session_state.login_type = 'student'
            st.rerun()
        if st.session_state.get('is_logged_in') and st.session_state.get('user_role') == 'student':
            auto_enroll(join_code)

main()
