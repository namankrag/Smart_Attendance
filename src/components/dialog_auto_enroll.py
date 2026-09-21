import streamlit as st
import time
from src.database.db import enroll_student_to_subject
from src.database.config import supabase
from src.components.dialog_utils import dialog_banner
from src.ui.base_layout import is_dark_theme

@st.dialog("Quick Enrollment", width="medium")
def auto_enroll(sub_code):
    stud_id = st.session_state.student_data['student_id']
    res = supabase.table('subjects').select('subject_id, name').eq('subject_code', sub_code).execute()
    dark = is_dark_theme()

    if not res.data:
        dialog_banner("Not Found", subtitle="This subject code does not exist", theme="pink")
        st.error("❌ Subject code not found!")
        if st.button('Close'):
            st.query_params.clear()
            st.rerun()
        return

    subject = res.data[0]
    chk = supabase.table('subject_students').select("*").eq('subject_id', subject['subject_id']).eq('student_id', stud_id).execute()

    if chk.data:
        dialog_banner("Already Enrolled", subtitle=subject['name'], theme="teal")
        st.info("✅ You are already enrolled in this subject!")
        if st.button("Got it!"):
            st.query_params.clear()
            st.rerun()
        return

    dialog_banner("Quick Enrollment", subtitle="You received a class invitation", theme="purple")

    card_bg = "linear-gradient(135deg, #312e81, #1e1b4b)" if dark else "linear-gradient(135deg, #ede9fe, #e0e7ff)"
    sub_title_col = "#a5b4fc" if dark else "#5144d3"
    sub_text_col = "#cbd5e1" if dark else "#64748b"

    st.markdown(f"""
        <div style="
            background: {card_bg};
            border-radius: 16px;
            padding: 20px;
            text-align: center;
            margin: 10px 0 20px;
        ">
            <div style="font-size: 2.5rem;">🎓</div>
            <p style="
                font-family: Outfit, sans-serif;
                font-size: 1.1rem;
                font-weight: 700;
                color: {sub_title_col};
                margin: 8px 0 4px;
            ">{subject['name']}</p>
            <p style="
                font-family: Outfit, sans-serif;
                font-size: 0.88rem;
                color: {sub_text_col};
                margin: 0;
            ">Would you like to join this class?</p>
        </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✕  No Thanks", width='stretch'):
            st.query_params.clear()
            st.rerun()
    with col2:
        if st.button("🚀  Yes, Enroll!", type='primary', width='stretch'):
            enroll_student_to_subject(stud_id, subject['subject_id'])
            st.success("🎉 Joined successfully!")
            st.query_params.clear()
            time.sleep(1)
            st.rerun()
