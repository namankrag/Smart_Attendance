import streamlit as st
from PIL import Image
import numpy as np
import time

from src.ui.base_layout import style_base_layout, style_bg_dashboard, is_dark_theme
from src.components.header import header_dashboard, theme_toggle
from src.components.footer import footer_dashboard
from src.pipelines.face_pipeline import predict_attendance, get_face_embeddings, train_classifier
from src.pipelines.voice_pipeline import get_voice_embedding
from src.database.db import get_all_students, create_student, get_student_subjects, get_student_attendance, unenroll_student_to_subject
from src.components.dialog_enroll import enroll_dilog
from src.components.subject_card import subject_card
from src.components.dialog_student_attendance import student_attendance_history

def student_dashboard():
    stud_data = st.session_state.student_data
    stud_id = stud_data['student_id']

    c1, c2 = st.columns(2, vertical_alignment='center', gap='xxlarge')
    with c1:
        header_dashboard()
    with c2:
        st.subheader(f"""Welcome, {stud_data['name']}""")
        b1, b2 = st.columns(2, vertical_alignment='center')
        with b1:
            if st.button("Logout", type='secondary', key='backbtn', width='stretch'):
                st.session_state.is_logged_in = False
                st.session_state.camera_active = False
                del st.session_state.student_data
                st.rerun()
        with b2:
            theme_toggle("student_dash")

    st.space()
    c1, c2 = st.columns(2)
    with c1:
        st.header("Your Enrolled Subject!")
    with c2:
        if st.button("Enroll in subject", type='primary', width='stretch'):
            enroll_dilog()

    st.divider()

    with st.spinner("Loading your enrolled subjects :"):
        subjects = get_student_subjects(stud_id)
        logs = get_student_attendance(stud_id)

    attended_map = {}
    absent_map = {}
    logs_by_subject = {}
    for log in logs:
        sid = log['subject_id']
        logs_by_subject.setdefault(sid, []).append(log)
        if log.get('is_present'):
            attended_map[sid] = attended_map.get(sid, 0) + 1
        else:
            absent_map[sid] = absent_map.get(sid, 0) + 1

    cols = st.columns(2)
    for i, sub_node in enumerate(subjects):
        sub = sub_node['subjects']
        sid = sub['subject_id']
        total_classes = sub.get('total_classes', 0)
        attended_classes = attended_map.get(sid, 0)
        subject_logs = list(logs_by_subject.get(sid, []))

        # Existing users enrolled before backfill support may not yet have a
        # false row per historic session. Build display-only absences so their
        # card and history are accurate; future enrollments are persisted in DB.
        recorded_timestamps = {str(log.get('timestamp')) for log in subject_logs if log.get('timestamp')}
        for timestamp in sub.get('session_timestamps', []):
            if str(timestamp) not in recorded_timestamps:
                subject_logs.append({'timestamp': timestamp, 'is_present': False})

        absent_classes = max(total_classes - attended_classes, 0)

        def attendance_actions(bound_name=sub['name'], bound_logs=subject_logs, bound_sid=sid,
                               attended=attended_classes, absent=absent_classes):
            present_col, absent_col = st.columns(2)
            with present_col:
                if st.button(
                    f"✓  {attended} Attended",
                    type='primary',
                    width='stretch',
                    key=f"attended_history_{bound_sid}",
                    icon=":material/calendar_month:",
                ):
                    student_attendance_history(bound_name, bound_logs, 'present')
            with absent_col:
                if st.button(
                    f"{absent} Absent",
                    type='secondary',
                    width='stretch',
                    key=f"absent_history_{bound_sid}",
                    icon=":material/event_busy:",
                ):
                    student_attendance_history(bound_name, bound_logs, 'absent')

        def unenrolled(bound_sid=sid, bound_sub=sub):
            if st.button("Unenroll from the course", type='primary', width='stretch',
                         icon=":material/delete_forever:", key=f"unenroll_{bound_sid}"):
                result = unenroll_student_to_subject(stud_id, bound_sid)
                if result.get("success"):
                    st.toast(f"✅ Unenrolled from {bound_sub['name']}! Deleted {result.get('logs_deleted', 0)} attendance records.")
                else:
                    st.error(f"Failed to unenroll: {result.get('error')}")
                time.sleep(1)
                st.rerun()

        with cols[i % 2]:
            subject_card(name = sub['name'],
                         code = sub['subject_code'],
                         section = sub['section'],
                         stats = [('📅', 'Total classes', total_classes)],
                         action_callback = attendance_actions,
                         footer_callback = unenrolled
                        )
    footer_dashboard()


def student_screen():

    style_bg_dashboard()
    style_base_layout()
    dark = is_dark_theme()

    if "student_data" in st.session_state:
        student_dashboard()
        return

    c1, c2 = st.columns(2, vertical_alignment='center', gap='xxlarge')
    with c1:
        header_dashboard()
    with c2:
        b1, b2 = st.columns(2, vertical_alignment='center')
        with b1:
            if st.button("Go to Home", type='secondary', key='backbtn', width='stretch'):
                st.session_state['login_type'] = None
                st.rerun()
        with b2:
            theme_toggle("student_login")

    st.header('Login using FaceID', text_alignment='center')

    st.space()
    st.space()

    accent_col = "#818cf8" if dark else "#667eea"

    st.markdown(f"""
        <div style="
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 12px;
        ">
            <span style="
                width: 10px; height: 10px;
                background: {accent_col};
                border-radius: 50%;
                display: inline-block;
                animation: pulse-dot 1.5s ease-in-out infinite;
                box-shadow: 0 0 8px {accent_col};
            "></span>
            <span style="
                font-family: 'Outfit', sans-serif;
                font-size: 0.95rem;
                font-weight: 600;
                color: {accent_col};
                letter-spacing: 1px;
                text-transform: uppercase;
            ">Face Scanner Active</span>
        </div>

        <style>
            @keyframes pulse-dot {{
                0%, 100% {{ transform: scale(1);   opacity: 1;   }}
                50%       {{ transform: scale(1.6); opacity: 0.4; }}
            }}
        </style>
    """, unsafe_allow_html=True)

    show_reg = False

    # Gate the camera — only activate when user explicitly clicks
    if 'camera_active' not in st.session_state:
        st.session_state.camera_active = False

    if not st.session_state.camera_active:
        box_bg = "#1e293b" if dark else "white"
        box_border = "border:1px solid #334155;" if dark else ""
        box_shadow = "box-shadow:0 4px 20px rgba(0,0,0,0.4);" if dark else "box-shadow:0 4px 20px rgba(102,126,234,0.1);"
        txt1_col = "#e2e8f0" if dark else "#64748b"
        txt2_col = "#94a3b8"

        st.html(
            f'<div style="text-align:center;padding:40px 20px;background:{box_bg};{box_border}border-radius:20px;'
            f'{box_shadow}margin-bottom:16px;">'
            '<div style="font-size:3rem;margin-bottom:12px;">📷</div>'
            f'<p style="font-family:Outfit,sans-serif;color:{txt1_col};font-size:0.95rem;margin:0 0 4px;">'
            'Camera is off to protect your privacy.</p>'
            f'<p style="font-family:Outfit,sans-serif;color:{txt2_col};font-size:0.85rem;margin:0;">'
            'Click below to activate the face scanner.</p>'
            '</div>'
        )
        if st.button("🔓  Activate Face Scanner", type='primary', width='stretch'):
            st.session_state.camera_active = True
            st.rerun()
        footer_dashboard()
        return

    # Camera is active — show it and a way to turn it off
    col_cam, col_off = st.columns([5, 1], vertical_alignment='bottom')
    with col_off:
        if st.button("Turn Off", type='secondary'):
            st.session_state.camera_active = False
            st.rerun()

    with col_cam:
        photo_src = st.camera_input("Position your face in the center")

    if photo_src:
        img = np.array(Image.open(photo_src).convert("RGB"))
        with st.spinner("AI is scanning..."):
            detected, all_ids, num_faces = predict_attendance(img)

            if detected:
                stud_id = list(detected.keys())[0]
                all_stud = get_all_students()
                stud = next((s for s in all_stud if s['student_id'] == stud_id), None)
                if stud:
                    st.session_state.camera_active = False
                    st.session_state.is_logged_in = True
                    st.session_state.user_role = 'student'
                    st.session_state.student_data = stud
                    st.toast(f"Welcome Back {stud['name']}!")
                    time.sleep(1)
                    st.rerun()
            elif num_faces == 0:
                st.warning("Face not Found! Please position your face clearly in the camera.")
            elif num_faces > 1:
                st.warning("Multiple Faces Found! Please ensure only one person is in the frame.")
            else:
                st.info("Face not recognized! You might be a new student.")
                show_reg = True

    if show_reg:
        with st.container(border=True):
            st.header("Register Your Profile")
            new_name = st.text_input("Enter you name", placeholder="Enter Name")
            st.subheader("Optional : Voice Enrollment")
            st.info("Enroll for voice only attendance!")
            audio_data = None
            try:
                audio_data = st.audio_input("Record a short phase like I am present, My name is Naman")
            except Exception:
                st.error("Audio data failed!")

            if st.button("Create Account", type='primary'):
                if new_name:
                    with st.spinner("Creating Profile..."):
                        img = np.array(Image.open(photo_src).convert("RGB"))
                        encodings = get_face_embeddings(img)
                        if encodings:
                            face_emb = encodings[0].tolist()
                            voice_emb = None
                            if audio_data:
                                voice_emb = get_voice_embedding(audio_data.read())
                            response_data = create_student(new_name, face_emb, voice_emb)
                            if response_data:
                                train_classifier()
                                st.session_state.is_logged_in = True
                                st.session_state.user_role = 'student'
                                st.session_state.student_data = response_data[0]
                                st.toast(f"Profile Created! Hi {new_name}")
                                time.sleep(1)
                                st.rerun()
                else:
                    st.warning("Please Enter your name!")

    footer_dashboard()
