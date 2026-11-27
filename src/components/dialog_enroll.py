"""Enroll in a subject by its separate, URL-safe join_code.

The join_code is NOT the human subject_code: subject_code is a display
code (e.g. CS101) that sections can share, while join_code is the
unguessable enrolment secret. Join codes are case-sensitive and are never
upper-cased. All lookups go through ``src.database.db`` — no direct
Supabase calls from this dialog.
"""

import streamlit as st

from src.database.rest_db import (
    is_student_enrolled,
    join_subject_by_code,
    lookup_subject_by_join_code,
)
from src.components.dialog_utils import dialog_banner
from src.ui.base_layout import is_dark_theme
from src.ui.join_codes import validate_join_code as _validate_join_code_v2

def validate_join_code(raw: str) -> str | None:
    """URL-decode and validate a join code. Returns the clean code or None.

    Delegates to ``src.ui.join_codes`` (time-limited v1 codes + legacy
    bare-token codes); kept here so existing imports keep working.
    """
    return _validate_join_code_v2(raw)


@st.dialog("Enroll in Subject", width="medium")
def enroll_dialog():
    dialog_banner(
        "Join a Subject", subtitle="Enter the join code shared by your teacher", theme="teal"
    )
    dark = is_dark_theme()

    box_bg = "rgba(6, 95, 70, 0.25)" if dark else "linear-gradient(135deg, #d1fae522, #a7f3d022)"
    box_border = "#059669" if dark else "#43e97b"
    box_text = "#6ee7b7" if dark else "#065f46"

    st.markdown(
        f"""
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
            🔑 Ask your teacher for the <b>Join Code</b> to enroll instantly.
            This is separate from the subject code (e.g. CS101).
        </div>
    """,
        unsafe_allow_html=True,
    )

    join_code_input = st.text_input(
        "Join Code", placeholder="e.g. Ab3dEf9GhJkL", key="input_join_code"
    )

    if st.button("🚀  Enroll Now", type="primary", width="stretch", key="btn_enroll_submit"):
        clean_code = validate_join_code(join_code_input or "")
        if not clean_code:
            st.warning("⚠️ Please enter a valid join code.")
            return
        try:
            subject = lookup_subject_by_join_code(clean_code)
        except Exception:
            st.error("Could not look up that join code. Please try again.")
            return
        if not subject:
            st.error("❌ Join code not found. Double-check with your teacher.")
            return
        stud_id = st.session_state.student_data["student_id"]
        try:
            already = (
                is_student_enrolled(stud_id, subject["subject_id"])
                if is_student_enrolled is not None
                else None
            )
        except Exception:
            already = None
        if already:
            st.warning("⚠️ You are already enrolled in this subject!")
            return
        try:
            join_subject_by_code(clean_code)
        except Exception:
            st.error("Could not enroll you. Please try again.")
            return
        st.success(f"🎉 Successfully enrolled in {subject.get('name', 'the subject')}!")
        st.rerun()


# Legacy alias
enroll_dilog = enroll_dialog
