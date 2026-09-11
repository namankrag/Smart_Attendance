import streamlit as st

from src.components.header import header_home
from src.components.footer import footer_home
from src.ui.base_layout import style_base_layout, style_bg_home

def home_screen():

    header_home()
    style_bg_home()
    style_base_layout()

    col1, col2 = st.columns(2, gap = "large")

    with col1:
        st.header("I'm Student")
        st.image("", width = 120)

        if st.button('Student Portal', type = 'primary', icon = ":material/arrow_outward:", icon_position = "right"):
            st.session_state["login_type"] = "student"
            st.rerun()

    with col2:
        st.header("I'am Teacher")
        st.image("", width = 145)

        if st.button('Teacher Portal', type = 'primary', icon = ':material/arrow_outward:', icon_position = "right"):
            st.session_state['login_type'] = 'teacher'
            st.rerun()

    footer_home()