import streamlit as st

from src.ui.base_layout import style_base_layout, style_bg_dashboard
from src.components.header import header_dashboard
from src.components.footer import footer_dashboard

from PIL import Image
import numpy as np

def student_dashboard():
    stud_data = st.session_state.student_data
    stud_id = stud_data['student_id']

    c1, c2 = st.columns(2, vertical_alignment='center', gap='xxlarge')
    with c1:
        header_dashboard()
    with c2:
        st.subheader(f"""Welcome, {stud_data['name']}""")
        st.button("Logout", type='secondary', key='backbtn', shortcut="control+backspace")



def student_screen():

    style_bg_dashboard()
    style_base_layout()

    if "student_data" in st.session_state:
        student_dashboard()
        return

    c1, c2 = st.columns(2, vertical_alignment='center', gap='xxlarge')
    with c1:
        header_dashboard()
    with c2:
        if st.button("Go Back To Home", type='secondary', key='backbtn', shortcut='control+backspace'):
            st.session_state['login_type'] = None
            st.rerun()

    st.header('Login using FaceID', text_alignment='center')

    st.space()
    st.space()

    show_reg = True
    photo_src = st.camera_input("Position your face in the center")

    footer_dashboard()