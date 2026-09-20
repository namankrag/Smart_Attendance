import streamlit as st
from pathlib import Path

from src.components.header import header_home
from src.components.footer import footer_home
from src.ui.base_layout import style_base_layout, style_bg_home

BASE_DIR = Path(__file__).resolve().parents[2]

student_img = BASE_DIR / "img" / "student.png"
teacher_img = BASE_DIR / "img" / "teacher.png"


def home_screen():

    style_bg_home()
    style_base_layout()

    # ── Full-width header above the cards ───────────────────────
    header_home()

    # ── Portal cards ────────────────────────────────────────────
    col1, col2 = st.columns(2, gap="large")

    with col1:
        st.markdown("""
            <p style="
                font-family: 'Climate Crisis', sans-serif;
                font-size: 1.6rem;
                font-weight: 900;
                color: #5144d3;
                letter-spacing: 2px;
                margin-bottom: 8px;
                -webkit-text-fill-color: #5144d3;
            ">I'm a Student</p>
        """, unsafe_allow_html=True)
        st.image(student_img, width=145)
        st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)
        if st.button('Student Portal', type='primary', icon=":material/arrow_outward:", icon_position="right"):
            st.session_state["login_type"] = "student"
            st.rerun()

    with col2:
        st.markdown("""
            <p style="
                font-family: 'Climate Crisis', sans-serif;
                font-size: 1.6rem;
                font-weight: 900;
                color: #a855f7;
                letter-spacing: 2px;
                margin-bottom: 8px;
                -webkit-text-fill-color: #a855f7;
            ">I'm a Teacher</p>
        """, unsafe_allow_html=True)
        st.image(teacher_img, width=145)
        st.markdown("<div style='margin-top:10px'></div>", unsafe_allow_html=True)
        if st.button('Teacher Portal', type='primary', icon=':material/arrow_outward:', icon_position="right"):
            st.session_state['login_type'] = 'teacher'
            st.rerun()

    footer_home()
