import streamlit as st
from src.database.db import enroll_student_to_subject
from src.database.config import supabase
from PIL import Image
import time

@st.dialog("Capture or upload photos")
def add_photos_dilog():
    st.write("Add classroom photo to scan attendance")
    if 'photo_tab' not in st.session_state:
        st.session_state.photo_tab = 'camera'
    t1, t2 = st.columns(2)
    with t1:
        type_upload = 'primary' if st.session_state.photo_tab == 'camera' else 'tertiary'
        if st.button('camera', type=type_upload, width='stretch'):
            st.session_state.photo_tab = 'camera'

    with t2:
        type_upload = 'primary' if st.session_state.photo_tab == 'upload' else 'tertiary'
        if st.button('Upload photos', type=type_upload, width='stretch'):
            st.session_state.photo_tab = 'upload'

    if st.session_state.photo_tab == 'camera':
        cam_photo = st.camera_input('Take Snapshot', key='dilog_cam')
        if cam_photo:
            st.session_state.attendance_images.append(Image.open(cam_photo))
            st.toast('Photo Captured')
            st.rerun()

    if st.session_state.photo_tab == 'upload':
        uploaded_file = st.file_uploader('choose image file',
                                         type=['jpg', 'png', 'jpeg'],
                                         accept_multiple_files = True,
                                         key = 'dialog_upload')
        if uploaded_file:
            for f in uploaded_file:
                st.session_state.attendance_images.append(Image.open(f))
            st.toast("Photo Uploaded Successfully")
            st.rerun()

    st.divider()
    if st.button('Done', type='primary', width='stretch'):
        st.rerun()