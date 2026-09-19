import streamlit as st
from pathlib import Path
import base64

from src.screen.home_screen import home_screen
from src.screen.teacher_screen import teacher_screen
from src.screen.student_screen import student_screen
from src.components.dilog_auto_enroll import auto_enroll

BASE_DIR = Path(__file__).parent.resolve()

def _img_to_base64(img_path: Path) -> str:
    with open(img_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def main():
    st.set_page_config(
        page_title = 'SmartClass - Making Attendance faster using AI',
        page_icon = _img_to_base64(BASE_DIR / "img" / "header.png")
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