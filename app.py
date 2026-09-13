import streamlit as st

from src.screen.home_screen import home_screen

def main():
    st.set_page_config(
        page_title = 'SmartClass - Making Attendance faster'
    )

    if 'login_type' not in st.session_state:
        st.session_state['login_type'] = None

    match st.session_state['login_type']:
        # case 'teacher':
        #     teacher_screen()

        # case 'student':
        #     student_screen()

        case None:
            home_screen()

main()