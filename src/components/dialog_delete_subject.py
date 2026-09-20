import streamlit as st
from src.database.db import delete_subject
from src.components.dialog_utils import dialog_banner

@st.dialog("Delete Subject")
def confirm_delete_subject(sub_id, sub_name, sub_code):
    dialog_banner("Delete Subject", subtitle="This action cannot be undone", theme="pink")

    st.html(
        '<div style="background:#fff1f2;border:1px solid #fecdd3;border-radius:16px;padding:20px 22px;margin-bottom:18px;">'
        '<div style="font-size:2rem;margin-bottom:8px;">⚠️</div>'
        '<p style="font-family:Outfit,sans-serif;font-size:1rem;font-weight:700;color:#be123c;margin:0 0 6px;">'
        'You are about to permanently delete:</p>'
        '<p style="font-family:Outfit,sans-serif;font-size:1.1rem;font-weight:800;color:#1e293b;margin:0 0 4px;">'
        + sub_name +
        '</p>'
        '<span style="background:linear-gradient(135deg,#ffe4e6,#fecdd3);color:#be123c;'
        'padding:2px 12px;border-radius:20px;font-size:0.82rem;font-weight:600;'
        'font-family:Outfit,sans-serif;">' + sub_code + '</span>'
        '<p style="font-family:Outfit,sans-serif;font-size:0.88rem;color:#64748b;margin:12px 0 0;">'
        'All <b>attendance records</b> and <b>enrollments</b> for this subject will also be deleted.</p>'
        '</div>'
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", width='stretch', key='delete_cancel'):
            st.rerun()
    with col2:
        if st.button("🗑️ Yes, Delete", type='secondary', width='stretch', key='delete_confirm'):
            try:
                delete_subject(sub_id)
                st.toast(f"'{sub_name}' deleted successfully.", icon="🗑️")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to delete: {e}")
