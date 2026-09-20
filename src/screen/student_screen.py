import streamlit as st
from PIL import Image
import numpy as np
import time

from src.ui.base_layout import style_base_layout, style_bg_dashboard
from src.components.header import header_dashboard
from src.components.footer import footer_dashboard
from src.pipelines.face_pipeline import predict_attendance, get_face_embeddings, train_classifier
from src.pipelines.voice_pipeline import get_voice_embedding
from src.database.db import get_all_students, create_student, get_student_subjects, get_student_attendance, unenroll_student_to_subject
from src.components.dialog_enroll import enroll_dilog
from src.components.subject_card import subject_card

def student_dashboard():
    stud_data = st.session_state.student_data
    stud_id = stud_data['student_id']

    c1, c2 = st.columns(2, vertical_alignment='center', gap='xxlarge')
    with c1:
        header_dashboard()
    with c2:
        st.subheader(f"""Welcome, {stud_data['name']}""")
        if st.button("Logout", type='secondary', key='backbtn', shortcut="control+backspace"):
            st.session_state.is_logged_in = False
            st.session_state.camera_active = False
            del st.session_state.student_data
            st.rerun()

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

    stats_map = {}

    for log in logs:
        sid = log['subject_id']

        if sid not in stats_map:
            stats_map[sid] = {'Total' : 0, 'Attended' : 0}

        stats_map[sid]['Total'] += 1
        if log.get('is_present'):
            stats_map[sid]['Attended'] += 1

    cols = st.columns(2)
    for i, sub_node in enumerate(subjects):
        sub = sub_node['subjects']
        sid = sub['subject_id']
        stats = stats_map.get(sid, {'Total' : 0, 'Attended' : 0})

        def unenrolled(bound_sid=sid, bound_sub=sub):
            if st.button("Unenroll from the course", type='primary', width='stretch',
                         icon=":material/delete_forever:", key=f"unenroll_{bound_sid}"):
                unenroll_student_to_subject(stud_id, bound_sid)
                st.toast(f"Unenrolled from {bound_sub['name']} successfully!")
                st.rerun()

        with cols[i % 2]:
            subject_card(name = sub['name'],
                         code = sub['subject_code'],
                         section = sub['section'],
                         stats = [('📅', 'Total', stats['Total']), ('✅', 'Attended', stats['Attended'])],
                         footer_callback = unenrolled
                        )
    footer_dashboard()


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

    st.markdown("""
        <div style="
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 12px;
        ">
            <span style="
                width: 10px; height: 10px;
                background: #667eea;
                border-radius: 50%;
                display: inline-block;
                animation: pulse-dot 1.5s ease-in-out infinite;
                box-shadow: 0 0 8px rgba(102, 126, 234, 0.8);
            "></span>
            <span style="
                font-family: 'Outfit', sans-serif;
                font-size: 0.95rem;
                font-weight: 600;
                color: #667eea;
                letter-spacing: 1px;
                text-transform: uppercase;
            ">Face Scanner Active</span>
        </div>

        <style>
            @keyframes pulse-dot {
                0%, 100% { transform: scale(1);   opacity: 1;   }
                50%       { transform: scale(1.6); opacity: 0.4; }
            }
        </style>
    """, unsafe_allow_html=True)

    show_reg = False

    # Gate the camera — only activate when user explicitly clicks
    if 'camera_active' not in st.session_state:
        st.session_state.camera_active = False

    if not st.session_state.camera_active:
        st.html(
            '<div style="text-align:center;padding:40px 20px;background:white;border-radius:20px;'
            'box-shadow:0 4px 20px rgba(102,126,234,0.1);margin-bottom:16px;">'
            '<div style="font-size:3rem;margin-bottom:12px;">📷</div>'
            '<p style="font-family:Outfit,sans-serif;color:#64748b;font-size:0.95rem;margin:0 0 4px;">'
            'Camera is off to protect your privacy.</p>'
            '<p style="font-family:Outfit,sans-serif;color:#94a3b8;font-size:0.85rem;margin:0;">'
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

            if num_faces == 0:
                st.warning("Face not Found!")
            elif num_faces > 1:
                st.warning("Multiple Faces Found")
            else:
                if detected:
                    stud_id = list(detected.keys())[0]
                    all_stud = get_all_students()
                    stud = next((s for s in all_stud if s['student_id'] == stud_id), None)
                    if stud:
                        st.session_state.camera_active = False
                        st.session_state.is_logged_in = True
                        st.session_state.user_role = 'student'
                        st.session_state.student_data = stud
                        st.toast(f"Welcome Back {stud['name']}")
                        time.sleep(1)
                        st.rerun()
                else:
                    st.info("Face not recognized! You might be a new student!")
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

