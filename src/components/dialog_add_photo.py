import streamlit as st
from PIL import Image
from src.components.dialog_utils import dialog_banner
from src.ui.base_layout import is_dark_theme

@st.dialog("Add Classroom Photos")
def add_photos_dialog():
    dialog_banner(
        "Add Photos",
        subtitle="Capture or upload photos to scan for attendance",
        theme="orange"
    )
    dark = is_dark_theme()

    if 'photo_tab' not in st.session_state:
        st.session_state.photo_tab = 'upload'

    t1, t2 = st.columns(2)
    with t1:
        typ = 'primary' if st.session_state.photo_tab == 'camera' else 'tertiary'
        if st.button('📷  Camera', type=typ, width='stretch'):
            st.session_state.photo_tab = 'camera'
    with t2:
        typ = 'primary' if st.session_state.photo_tab == 'upload' else 'tertiary'
        if st.button('🖼️  Upload', type=typ, width='stretch'):
            st.session_state.photo_tab = 'upload'

    st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

    if st.session_state.photo_tab == 'camera':
        count = len(st.session_state.get('attendance_images', []))
        if count:
            pill_bg = "linear-gradient(135deg, #7c2d12 0%, #451a03 100%)" if dark else "linear-gradient(135deg, #fff7ed, #ffedd5)"
            border_col = "#f97316" if dark else "#fa8231"
            text_col = "#ffedd5" if dark else "#c2410c"

            st.markdown(f"""
                <div style="
                    background: {pill_bg};
                    border-left: 4px solid {border_col};
                    border-radius: 10px;
                    padding: 8px 14px;
                    margin-bottom: 10px;
                    font-family: Outfit, sans-serif;
                    font-size: 0.88rem;
                    color: {text_col};
                ">📸 {count} photo{'s' if count != 1 else ''} added so far</div>
            """, unsafe_allow_html=True)

        cam_photo = st.camera_input('Take Snapshot', key='dilog_cam')
        if cam_photo:
            st.session_state.attendance_images.append(Image.open(cam_photo))
            st.toast('📸 Photo captured!')
            st.rerun()

    if st.session_state.photo_tab == 'upload':
        uploaded_files = st.file_uploader(
            'Choose image files',
            type=['jpg', 'png', 'jpeg'],
            accept_multiple_files=True,
            key='dialog_upload'
        )
        if uploaded_files:
            for f in uploaded_files:
                st.session_state.attendance_images.append(Image.open(f))
            st.toast(f"🖼️ {len(uploaded_files)} photo(s) uploaded!")
            st.rerun()

    st.divider()
    if st.button('✅  Done', type='primary', width='stretch'):
        st.rerun()
