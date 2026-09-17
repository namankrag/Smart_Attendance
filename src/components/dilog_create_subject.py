import streamlit as st
from src.database.db import create_subject

@st.dialog("Create New Subject")
def create_subject_dilog(teach_id):
    st.write("Enter details of new subject")
    sub_id = st.text_input("Subject Code", placeholder = "MPW")
    sub_name  = st.text_input("Subject Name", placeholder = "Mini Project Work")
    sub_section = st.text_input("Section", placeholder = "C")

    if st.button("Create Subject Now", type='primary', width='stretch'):
        if sub_id and sub_name and sub_section:
            try:
                create_subject(sub_id, sub_name, sub_section, teach_id)
                st.toast("Subject Created Successfully")
                st.rerun()
            except Exception as e:
                st.error(f"Error : {str(e)}")
        else:
            st.warning("Please fill all the fields")