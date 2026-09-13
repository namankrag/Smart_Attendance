import streamlit as st
from pathlib import Path

from src.components.header import header_home
from src.components.footer import footer_home
from src.ui.base_layout import style_base_layout, style_bg_home

BASE_DIR = Path(__file__).resolve().parents[2]

student_img = BASE_DIR / "img" / "student.png"
teacher_img = BASE_DIR / "img" / "teacher.png"


def home_screen():

    header_home()
    style_bg_home()
    style_base_layout()

    col1, col2 = st.columns(2, gap = "large")

    with col1:
        st.header("I'm Student")
        st.image(student_img, width = 120)

        if st.button('Student Portal', type = 'primary', icon = ":material/arrow_outward:", icon_position = "right"):
            st.session_state["login_type"] = "student"
            st.rerun()

    with col2:
        st.header("I'm Teacher")
        st.image(teacher_img, width = 145)

        if st.button('Teacher Portal', type = 'primary', icon = ':material/arrow_outward:', icon_position = "right"):
            st.session_state['login_type'] = 'teacher'
            st.rerun()

    footer_home()