import streamlit as st
from src.database.db import create_subject
from src.components.dialog_utils import dialog_banner

@st.dialog("Create New Subject")
def create_subject_dialog(teach_id):
    dialog_banner(
        "New Subject",
        subtitle="Fill in the details to create a new class",
        theme="purple"
    )

    st.markdown("""
        <style>
            div[data-testid="stTextInput"] label {
                font-family: Outfit, sans-serif;
                font-weight: 600;
                color: #5144d3;
                font-size: 0.92rem;
                letter-spacing: 0.5px;
            }
        </style>
    """, unsafe_allow_html=True)

    sub_id      = st.text_input("📌 Subject Code",  placeholder="e.g. CS101")
    sub_name    = st.text_input("📚 Subject Name",  placeholder="e.g. Data Structures")
    sub_section = st.text_input("🏷️  Section",       placeholder="e.g. A")

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    if st.button("✨  Create Subject", type='primary', width='stretch'):
        if sub_id and sub_name and sub_section:
            try:
                create_subject(sub_id, sub_name, sub_section, teach_id)
                st.toast("🎉 Subject created successfully!")
                st.rerun()
            except Exception as e:
                st.error(f"❌ {str(e)}")
        else:
            st.warning("⚠️ Please fill in all fields.")
