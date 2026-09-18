import streamlit as st
from src.database.config import supabase
from src.database.db import enroll_student_to_subject
import time

@st.dialog("Enroll in Subject")
def enroll_dilog():
    st.write("Enter subject code provided by your teacher to enroll")
    join_code = st.text_input("Subject_code", placeholder="MPW")

    if st.button("Enroll Now", type='primary', width='stretch'):
        if join_code:
            res = supabase.table('subjects').select('subject_id, name, subject_code').eq('subject_code', join_code).execute()
            if res.data:
                sub = res.data[0]
                stud_id = st.session_state.student_data['student_id']
                chk = supabase.table('subject_students').select('*').eq('subject_id', sub['subject_id']).eq('student_id', stud_id).execute()
                if chk.data:
                    st.warning("You are already enrolled in this program!")
                else:
                    enroll_student_to_subject(stud_id, sub['subject_id'])
                    st.success("Successfully Enrolled!")
                    time.sleep(1)
                    st.rerun()
        else:
            st.warning("Please enter a subject code!")