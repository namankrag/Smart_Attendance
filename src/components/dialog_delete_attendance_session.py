"""Confirm deletion of one attendance session and all its student records."""

import logging

import streamlit as st

from src.components.dialog_utils import dialog_banner
from src.database.rest_db import delete_attendance_session

logger = logging.getLogger(__name__)


@st.dialog("Delete Attendance Session", width="small")
def confirm_delete_attendance_session(session_id, subject_name, time_label, teacher_id):
    dialog_banner(
        "Delete Attendance Session",
        subtitle="This action cannot be undone",
        theme="pink",
    )
    st.write(f"Subject: {subject_name}")
    st.write(f"Class time: {time_label}")
    st.warning(
        "This removes the session and the attendance records for every student in it. "
        "The session will no longer count toward attendance totals."
    )

    cancel_col, delete_col = st.columns(2)
    with cancel_col:
        if st.button("Cancel", width="stretch", key="attendance_session_delete_cancel"):
            st.rerun()
    with delete_col:
        if st.button(
            "🗑️ Delete Session",
            type="secondary",
            width="stretch",
            key="attendance_session_delete_confirm",
        ):
            try:
                delete_attendance_session(session_id, teacher_id=teacher_id)
            except Exception:
                logger.exception("Failed to delete attendance session %s", session_id)
                st.error("Could not delete this attendance session. Please try again.")
                return

            st.session_state["smartclass_records_page"] = 0
            st.toast("Attendance session and all student records deleted.", icon="🗑️")
            st.rerun()
