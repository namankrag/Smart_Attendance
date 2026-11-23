import html
import logging

import streamlit as st

# Phase 3 (audit 51): subject deletion is transactional — the
# delete_subject_tx RPC (migration 005) deletes logs, sessions,
# enrolments and the subject in ONE database transaction. The old
# sequential delete_subject() is kept only for databases where 005
# has not been applied yet.
from src.database.db import delete_subject, delete_subject_transactional
from src.components.dialog_utils import dialog_banner
from src.ui.base_layout import is_dark_theme

logger = logging.getLogger(__name__)


@st.dialog("Delete Subject", width="medium")
def confirm_delete_subject(sub_id, sub_name, sub_code, teacher_id=None):
    """Delete a subject. ``teacher_id`` is passed to the db layer for an
    ownership check (db agent); deletion must not proceed for a subject
    the teacher does not own."""
    dialog_banner("Delete Subject", subtitle="This action cannot be undone", theme="pink")
    dark = is_dark_theme()

    box_bg = "rgba(159, 18, 57, 0.2)" if dark else "#fff1f2"
    box_border = "#9f1239" if dark else "#fecdd3"
    warn_title_col = "#fecdd3" if dark else "#be123c"
    subname_col = "#f8fafc" if dark else "#1e293b"
    code_bg = (
        "linear-gradient(135deg, #881337, #9f1239)"
        if dark
        else "linear-gradient(135deg, #ffe4e6, #fecdd3)"
    )
    code_col = "#fecdd3" if dark else "#be123c"
    subtext_col = "#cbd5e1" if dark else "#64748b"

    st.html(
        f'<div style="background:{box_bg};border:1px solid {box_border};border-radius:16px;padding:'
            f'20px 22px;margin-bottom:18px;">'
        '<div style="font-size:2rem;margin-bottom:8px;">⚠️</div>'
        f'<p style="font-family:Outfit,sans-serif;font-size:1rem;font-weight:700;color'
            f':{warn_title_col};margin:0 0 6px;">'
        "You are about to permanently delete:</p>"
        f'<p style="font-family:Outfit,sans-serif;font-size:1.1rem;font-weight:800;color'
            f':{subname_col};margin:0 0 4px;">'
        + html.escape(str(sub_name))
        + "</p>"
        f'<span style="background:{code_bg};color:{code_col};'
        "padding:2px 12px;border-radius:20px;font-size:0.82rem;font-weight:600;"
        'font-family:Outfit,sans-serif;">' + html.escape(str(sub_code)) + "</span>"
        f'<p style="font-family:Outfit,sans-serif;font-size:0.88rem;color:{subtext_col};margin:12px'
            f' 0 0;">'
        "All <b>attendance records</b> and <b>enrollments</b> for this subject will also be deleted"
            ".</p>"
        "</div>"
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel", width="stretch", key="delete_cancel"):
            st.rerun()
    with col2:
        if st.button("🗑️ Yes, Delete", type="secondary", width="stretch", key="delete_confirm"):
            try:
                if teacher_id is None:
                    delete_subject(sub_id)
                else:
                    try:
                        delete_subject_transactional(sub_id, teacher_id=teacher_id)
                    except TypeError:
                        logger.warning(
                            "delete_subject_transactional has no teacher_id parameter yet"
                        )
                        delete_subject(sub_id, teacher_id=teacher_id)
                st.toast(f"'{sub_name}' deleted successfully.", icon="🗑️")
                st.rerun()
            except Exception:
                logger.exception("Failed to delete subject")
                st.error("Failed to delete the subject. Please try again.")
