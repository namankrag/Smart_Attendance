import streamlit as st

from src.ui.base_layout import style_bg_dashboard, style_base_layout
from src.components.header import header_dashboard
from src.components.footer import footer_dashboard

def teacher_screen():

    style_bg_dashboard()
    style_base_layout()

    if 'teacher_login_type' not in st.session_state or st.session_state.teacher_login_type == 'login':
        teacher_scrn_login()
    elif st.session_state.teacher_login_type == 'register':
        teacher_scrn_register()



def teacher_scrn_login():
    c1, c2 = st.columns(2, vertical_alignment="center", gap="xxlarge")
    with c1:
        header_dashboard()
    with c2:
        if st.button("Go Back To Home", type='secondary', key='backbtn', shortcut='control+backspace'):
            st.session_state['login_type'] = None
            st.session_state['teacher_login_type'] = 'login'
            st.rerun()

    st.header('Login using password', text_alignment='center')

    st.space()
    st.space()

    username = st.text_input("Enter Username", placeholder='@username')
    password = st.text_input("Enter Password", type='password', placeholder="Enter Password")

    st.divider()

    btn1, btn2 = st.columns(2)

    with btn1:
        st.button("Login", icon=':material/passkey:', shortcut="control+enter", width='stretch')

    with btn2:
        if st.button("Register Instead", type='primary', icon=':material/passkey:', width="stretch"):
            st.session_state.teacher_login_type = 'register'
            st.rerun()

    footer_dashboard()



def teacher_scrn_register():
    c1, c2 = st.columns(2, vertical_alignment="center", gap="xxlarge")
    with c1:
        header_dashboard()
    with c2:
        if st.button("Go Back To Home", type='secondary', key='backbtn', shortcut='control+backspace'):
            st.session_state['login_type'] = None
            st.session_state['teacher_login_type'] = 'login'
            st.rerun()

    st.header('Register your teacher profile')

    st.space()
    st.space()

    username = st.text_input("Enter Username", placeholder='@username')
    name = st.text_input("Enter name", placeholder='Name')
    password = st.text_input("Enter Password", type='password', placeholder="Enter Password")
    pass_conf = st.text_input("Confirm your Password", type='password', placeholder="Confirm Password")

    st.divider()

    btn1, btn2 = st.columns(2)

    with btn1:
        st.button("Register Now", icon=':material/passkey:', shortcut="control+enter", width='stretch')

    with btn2:
        if st.button("Login Instead", type='primary', icon=':material/passkey:', width="stretch"):
            st.session_state.teacher_login_type = 'login'
            st.rerun()

    footer_dashboard()