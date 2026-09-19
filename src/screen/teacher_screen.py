import streamlit as st
import time
import numpy as np
from datetime import datetime
import pandas as pd

from src.ui.base_layout import style_bg_dashboard, style_base_layout
from src.components.header import header_dashboard
from src.components.footer import footer_dashboard
from src.database.db import check_teacher_exists, create_teacher, teacher_login, get_teacher_subjects, get_attendance_for_teacher
from src.components.dialog_create_subject import create_subject_dialog
from src.components.subject_card import subject_card
from src.components.dialog_share_subject import share_subject
from src.components.dialog_add_photo import add_photos_dialog
from src.pipelines.face_pipeline import predict_attendance
from src.database.config import supabase
from src.components.dialog_attend_result import attend_result
from src.components.dialog_voice_attend import voice_attendance

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
    teach_id = st.session_state.teacher_data['teacher_id']
    st.header("Take AI Attendance")
    if 'attendance_images' not in st.session_state:
        st.session_state.attendance_images = []

    subjects = get_teacher_subjects(teach_id)
    if not subjects:
        st.warning("You have not created any subjects! Please create one to begin!")
        return

    sub_opt = {f"{s['name']} - {s['subject_code']}" : s['subject_id'] for s in subjects}
    col1, col2 = st.columns([3, 1], vertical_alignment = 'bottom')
    with col1:
        selected_sub_label = st.selectbox('Select Subjects', options = list(sub_opt.keys()))
    with col2:
        if st.button('Add Photos', type='primary', width='stretch', icon=":material/photo_prints:"):
            add_photos_dialog()

    selected_sub_id = sub_opt[selected_sub_label]
    st.divider()
    if st.session_state.attendance_images:
        st.header('Added Photos')
        gallery_cols = st.columns(4)

        for idx, img in enumerate(st.session_state.attendance_images):
            with gallery_cols[idx % 4]:
                st.image(img, width='stretch', caption=f"Photo {idx+1}")
    has_photos = bool(st.session_state.attendance_images)
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Clear all photos", type = 'primary', disabled = not has_photos, icon = ":material/delete:"):
            st.session_state.attendance_images = []
            st.rerun()
    with c2:
        if st.button("Run face analysis", type = 'secondary', disabled= not has_photos, icon = ":material/analytics:"):
            with st.spinner("Deep Scanning classroom photos..."):
                all_detected_ids = {}
                for idx, img in enumerate(st.session_state.attendance_images):
                    img_np = np.array(img.convert('RGB'))
                    detected, _, _ = predict_attendance(img_np)

                    if detected:
                        for sid in detected.keys():
                            stud_id = int(sid)
                            all_detected_ids.setdefault(stud_id, []).append(f"Photos {idx+1}")

                enrolled_res = supabase.table('subject_students').select("*, students(*)").eq('subject_id', selected_sub_id).execute()
                enrolled_stud = enrolled_res.data

                if not enrolled_stud:
                    st.warning("No student enrolled in this course!")
                else:
                    res, attend_logs = [], []
                    crnt_timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                    for node in enrolled_stud:
                        stud = node['students']
                        sources = all_detected_ids.get(int(stud['student_id']), [])
                        is_present = len(sources) > 0
                        res.append({
                            "Name" : stud['name'],
                            "ID" : stud['student_id'],
                            "Source" : ", ".join(sources) if is_present else "-",
                            "Status" : "✅ Present" if is_present else "❌ Absent"
                        })
                        attend_logs.append({
                            'student_id' : stud['student_id'],
                            'subject_id' : selected_sub_id,
                            'timestamp' : crnt_timestamp,
                            'is_present' : bool(is_present)
                        })

                attend_result(pd.DataFrame(res), attend_logs)
    with c3:
        if st.button("Use Voice Attendance", type='primary', width='stretch', icon=":material/mic:"):
            voice_attendance(selected_sub_id)


def manage_subjects():
    teach_id = st.session_state.teacher_data['teacher_id']
    col1, col2 = st.columns(2)
    with col1:
        st.header("Manage Subjects", width = 'stretch')
    with col2:
        if st.button("Create New Subject", width = 'stretch'):
            create_subject_dialog(teach_id)

    subjects = get_teacher_subjects(teach_id)
    if subjects:
        for sub in subjects:
            stats = [
                ("🫂", "Students", sub['total_students']),
                ("🕰️", "Classes", sub['total_classes'])
            ]
        def share_btn():
            if st.button(f"Share Code : {sub['name']}", key = f"share_{sub['subject_code']}", icon=":material/share:"):
                share_subject(sub['name'], sub['subject_code'])
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
    teach_id = st.session_state.teacher_data['teacher_id']
    records = get_attendance_for_teacher(teach_id)
    if not records:
        return
    data = []
    for r in records:
        ts = r.get('timestamp')
        data.append({
            "ts_group" : ts.split(".")[0] if ts else None,
            "Time" : datetime.fromisoformat(ts).strftime("%Y-%m-%d %I:%M %p") if ts else "N/A",
            "Subject" : r['subjects']['name'],
            "Subject Code" : r['subjects']['subject_code'],
            "is_present" : bool(r.get('is_present', False))
        })

    df = pd.DataFrame(data)
    summary = (
        df.groupby(['ts_group', 'Time', 'Subject', 'Subject Code'])
        .agg(
            Present_Count = ('is_present', 'sum'),
            Total_Count = ('is_present', 'count')
        ).reset_index()
    )
    summary['Attendance Stats'] = (
        "✅ " + summary['Present_Count'].astype(str) + " /" + summary['Total_Count'].astype(str) + ' Students'
    )
    display_df = (summary.sort_values(by='ts_group', ascending=False)
                  [['Time', 'Subject', 'Subject Code', 'Attendance Stats']]
                  )
    st.dataframe(display_df, width='stretch', hide_index=True)


def register_teacher(username, name, pswrd, pswrd_cnfrm):
    if not username or not name or not pswrd:
        return False, "All Fields are required!"
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

