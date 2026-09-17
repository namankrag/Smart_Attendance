import streamlit as st
from PIL import Image
import numpy as np
import time

from src.ui.base_layout import style_base_layout, style_bg_dashboard
from src.components.header import header_dashboard
from src.components.footer import footer_dashboard
from src.pipelines.face_pipeline import predict_attendance, get_face_embeddings, train_classifier
from src.pipelines.voice_pipeline import get_voice_embedding
from src.database.db import get_all_students, create_student

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
            del st.session_state.student_data
            st.rerun()

    st.space()
    c1, c2 = st.columns(2)
    with c1:
        st.header("Your Enrolled Subject!")
    with c2:
        st.button("Enroll in subject", type='primary', width='stretch')
            



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

    show_reg = False
    photo_src = st.camera_input("Position your face in the center")
    if photo_src:
        img = np.array(Image.open(photo_src))
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
                        img = np.array(Image.open(photo_src))
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