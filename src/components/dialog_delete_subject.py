import streamlit as st
from src.database.db import delete_subject
from src.components.dialog_utils import dialog_banner
from src.ui.base_layout import is_dark_theme

@st.dialog("Delete Subject", width="medium")
def confirm_delete_subject(sub_id, sub_name, sub_code):
    dialog_banner("Delete Subject", subtitle="This action cannot be undone", theme="pink")
    dark = is_dark_theme()

    box_bg = "rgba(159, 18, 57, 0.2)" if dark else "#fff1f2"
    box_border = "#9f1239" if dark else "#fecdd3"
    warn_title_col = "#fecdd3" if dark else "#be123c"
    subname_col = "#f8fafc" if dark else "#1e293b"
    code_bg = "linear-gradient(135deg, #881337, #9f1239)" if dark else "linear-gradient(135deg, #ffe4e6, #fecdd3)"
    code_col = "#fecdd3" if dark else "#be123c"
    subtext_col = "#cbd5e1" if dark else "#64748b"

    st.html(
        f'<div style="background:{box_bg};border:1px solid {box_border};border-radius:16px;padding:20px 22px;margin-bottom:18px;">'
        '<div style="font-size:2rem;margin-bottom:8px;">⚠️</div>'
        f'<p style="font-family:Outfit,sans-serif;font-size:1rem;font-weight:700;color:{warn_title_col};margin:0 0 6px;">'
        'You are about to permanently delete:</p>'
        f'<p style="font-family:Outfit,sans-serif;font-size:1.1rem;font-weight:800;color:{subname_col};margin:0 0 4px;">'
        + sub_name +
        '</p>'
        f'<span style="background:{code_bg};color:{code_col};'
        'padding:2px 12px;border-radius:20px;font-size:0.82rem;font-weight:600;'
        'font-family:Outfit,sans-serif;">' + sub_code + '</span>'
        f'<p style="font-family:Outfit,sans-serif;font-size:0.88rem;color:{subtext_col};margin:12px 0 0;">'
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
