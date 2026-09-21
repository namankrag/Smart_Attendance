import streamlit as st
from src.database.config import supabase
from src.database.db import enroll_student_to_subject
from src.components.dialog_utils import dialog_banner
from src.ui.base_layout import is_dark_theme
import time

@st.dialog("Enroll in Subject", width="medium")
def enroll_dilog():
    dialog_banner(
        "Join a Subject",
        subtitle="Enter the code shared by your teacher",
        theme="teal"
    )
    dark = is_dark_theme()

    box_bg = "rgba(6, 95, 70, 0.25)" if dark else "linear-gradient(135deg, #d1fae522, #a7f3d022)"
    box_border = "#059669" if dark else "#43e97b"
    box_text = "#6ee7b7" if dark else "#065f46"

    st.markdown(f"""
        <div style="
            background: {box_bg};
            border-left: 4px solid {box_border};
            border-radius: 12px;
            padding: 10px 14px;
            margin-bottom: 14px;
            font-family: Outfit, sans-serif;
            font-size: 0.9rem;
            color: {box_text};
        ">
            🔑 Ask your teacher for the <b>Subject Code</b> to enroll instantly.
        </div>
    """, unsafe_allow_html=True)

    join_code = st.text_input("Subject Code", placeholder="e.g. MPW")

    if st.button("🚀  Enroll Now", type='primary', width='stretch'):
        if join_code:
            res = supabase.table('subjects').select('subject_id, name, subject_code').eq('subject_code', join_code).execute()
            if res.data:
                sub = res.data[0]
                stud_id = st.session_state.student_data['student_id']
                chk = supabase.table('subject_students').select('*').eq('subject_id', sub['subject_id']).eq('student_id', stud_id).execute()
                if chk.data:
                    st.warning("⚠️ You are already enrolled in this subject!")
                else:
                    enroll_student_to_subject(stud_id, sub['subject_id'])
                    st.success(f"🎉 Successfully enrolled in **{sub['name']}**!")
                    time.sleep(1)
                    st.rerun()
            else:
                st.error("❌ Subject code not found. Double-check with your teacher.")
        else:
            st.warning("⚠️ Please enter a subject code!")
