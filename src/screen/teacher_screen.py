import streamlit as st
import time

from src.ui.base_layout import style_bg_dashboard, style_base_layout
from src.components.header import header_dashboard
from src.components.footer import footer_dashboard
from src.database.db import check_teacher_exists, create_teacher, teacher_login, get_teacher_subjects
from src.components.dilog_create_subject import create_subject_dilog
from src.components.subject_card import subject_card


def teacher_screen():

    style_bg_dashboard()
    style_base_layout()

    if "teacher_data" in st.session_state:
        teacher_dashboard()
    elif 'teacher_login_type' not in st.session_state or st.session_state.teacher_login_type == 'login':
        teacher_scrn_login()
    elif st.session_state.teacher_login_type == 'register':
        teacher_scrn_register()


def teacher_dashboard():
    data = st.session_state.teacher_data
    c1, c2 = st.columns(2, vertical_alignment='center', gap='xxlarge')
    with c1:
        header_dashboard()
    with c2:
        st.subheader(f"""Welcome, {data['name']} """)
        
        if st.button("Logout", type='secondary', key='backbtn', shortcut='control+backspace'):
            st.session_state['is_logged_in'] = False
            del st.session_state.teacher_data
            st.rerun()
    st.space()

    if "current_teacher_tab" not in st.session_state:
        st.session_state.current_teacher_tab = 'take_attendance'

    tab1, tab2, tab3 = st.columns(3)

    with tab1:
        type1 = 'primary' if st.session_state.current_teacher_tab == "take_attendance" else 'tertiary'
        if st.button("Take Attendance", type = type1, width = 'stretch', icon = ":material/ar_on_you:"):
            st.session_state.current_teacher_tab = "take_attendance"
            st.rerun()

    with tab2:
        type2 = 'primary' if st.session_state.current_teacher_tab == "manage_subjects" else 'tertiary'
        if st.button("Manage Subjects", type = type2, width = 'stretch', icon = ":material/book_ribbon:"):
            st.session_state.current_teacher_tab = "manage_subjects"
            st.rerun()

    with tab3:
        type3 = 'primary' if st.session_state.current_teacher_tab == "attendance_records" else 'tertiary'
        if st.button("Attendance Records", type = type3, width = 'stretch', icon = ":material/cards_stack:"):
            st.session_state.current_teacher_tab = "attendance_records"
            st.rerun()

    st.divider()
    if st.session_state.current_teacher_tab == 'take_attendance':
        take_attendance()
    if st.session_state.current_teacher_tab == 'manage_subjects':
        manage_subjects()
    if st.session_state.current_teacher_tab == 'attendance_records':
        attendance_records()

    footer_dashboard()

def take_attendance():
    st.header("Take AI Attendance")


def manage_subjects():
    teach_id = st.session_state.teacher_data['teacher_id']
    col1, col2 = st.columns(2)
    with col1:
        st.header("Manage Subjects", width = 'stretch')
    with col2:
        if st.button("Create New Subject", width = 'stretch'):
            create_subject_dilog(teach_id)

    subjects = get_teacher_subjects(teach_id)
    if subjects:
        for sub in subjects:
            stats = [
                ("🫂", "Students", sub['total_students']),
                ("🕰️", "Classes", sub['total_classes'])
            ]
        def share_btn():
            if st.button(f"Share Code : {sub['name']}", key = f"share_{sub['subject_code']}", icon=":material/share:"):
                share_subject_dialog(sub['name'], sub['subject_code'])
            st.space()
        
        subject_card(
            name = sub['name'],
            code = sub['subject_code'],
            section = sub['section'],
            stats = stats,
            footer_callback = share_btn
        )


def attendance_records():
    st.header("Attendance Records")


def register_teacher(username, name, pswrd, pswrd_cnfrm):
    if not username or not name or not pswrd:
        return False, "All Feilds are required!"
    elif check_teacher_exists(username):
        return False, "Username already Taken"
    elif pswrd != pswrd_cnfrm:
        return False, "Password doesn't match"

    try:
        create_teacher(username, pswrd, name)
        return True, "Sucessfully Created! Login now"
    except Exception as e:
        return False, "Unexpected Error!"


def login(username, pswrd):
    if not username or not pswrd:
        return False

    teach = teacher_login(username, pswrd)

    if teach:
        st.session_state.user_role = 'teacher'
        st.session_state.teacher_data = teach
        st.session_state.is_logged_in = True
        return True


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
        if st.button("Login", icon=':material/passkey:', shortcut="control+enter", width='stretch'):
            if login(username, password):
                st.toast("Welcome Back", icon="👋")
                time.sleep(2)
                st.rerun()
            else:
                st.error("Invalid Username or Password")

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
        if st.button("Register Now", icon=':material/passkey:', shortcut="control+enter", width='stretch'):
            succ, msg = register_teacher(username, name, password, pass_conf)
            if succ:
                st.success(msg)
                time.sleep(2)
                st.session_state.teacher_login_type = 'login'
                st.rerun()
            else:
                st.error(msg)

    with btn2:
        if st.button("Login Instead", type='primary', icon=':material/passkey:', width="stretch"):
            st.session_state.teacher_login_type = 'login'
            st.rerun()

    footer_dashboard()

