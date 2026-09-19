import streamlit as st
import time
from src.database.db import enroll_student_to_subject
from src.database.config import supabase

@st.dialog("Quick Enrollment")
def auto_enroll(sub_code):
    stud_id = st.session_state.student_data['student_id']
    res = supabase.table('subjects').select('subject_id, name').eq('subject_code', sub_code).execute()
    if not res.data:
        st.error("Subjet code not found!")
        if st.button('Close'):
            st.query_params.clear()
            st.rerun()
        return

    subject = res.data[0]
    chk = supabase.table('subject_students').select("*").eq('subject_id', subject['subject_id']).eq('student_id', stud_id).execute()

    if chk.data:
        st.info("You are already Enrolled!")
        if st.button("Got it!"):
            st.query_params.clear()
            st.rerun()
        return

    st.markdown(f"Would you like to Enroll in **{subject['name']}** ?")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("No Thanks"):
            st.query_params.clear()
            st.rerun()
    with col2:
        if st.button("Yes Enroll Now!", type='primary', width='stretch'):
            enroll_student_to_subject(stud_id, subject['subject_id'])
            st.success("Joined Successfully!")
            st.query_params.clear()
            time.sleep(1)
            st.rerun()
    