"""Create a new subject.

Validation (Phase 0): subject_code must be non-empty after stripping
whitespace and 3-20 characters; name must be non-empty and at most 100
characters. ``create_subject`` generates a separate random URL-safe
join_code when ``join_code=None`` is passed (db agent); the returned
join_code, when present, is shown to the teacher once.

Note: this dialog has no PIN input, so no PIN validation applies here.
"""

import logging

import streamlit as st

from src.database.db import create_subject
from src.components.dialog_utils import dialog_banner
from src.ui.base_layout import is_dark_theme

logger = logging.getLogger(__name__)

SUBJECT_CODE_MIN_LEN = 3
SUBJECT_CODE_MAX_LEN = 20
SUBJECT_NAME_MAX_LEN = 100


def validate_subject_fields(sub_code: str, sub_name: str, sub_section: str) -> str | None:
    """Return an error message, or None if the fields are valid."""
    code = (sub_code or "").strip()
    name = (sub_name or "").strip()
    section = (sub_section or "").strip()
    if not code:
        return "Subject code is required."
    if not (SUBJECT_CODE_MIN_LEN <= len(code) <= SUBJECT_CODE_MAX_LEN):
        return f"Subject code must be {SUBJECT_CODE_MIN_LEN}-{SUBJECT_CODE_MAX_LEN} characters."
    if not name:
        return "Subject name is required."
    if len(name) > SUBJECT_NAME_MAX_LEN:
        return f"Subject name must be {SUBJECT_NAME_MAX_LEN} characters or fewer."
    if not section:
        return "Section is required."
    return None


@st.dialog("Create New Subject", width="medium")
def create_subject_dialog(teach_id):
    dialog_banner(
        "New Subject", subtitle="Fill in the details to create a new class", theme="purple"
    )
    dark = is_dark_theme()
    lbl_color = "#818cf8" if dark else "#5144d3"

    st.markdown(
        f"""
        <style>
            div[data-testid="stTextInput"] label {{
                font-family: Outfit, sans-serif;
                font-weight: 600;
                color: {lbl_color};
                font-size: 0.92rem;
                letter-spacing: 0.5px;
            }}
        </style>
    """,
        unsafe_allow_html=True,
    )

    sub_id = st.text_input(
        "📌 Subject Code", placeholder="e.g. CS101", max_chars=SUBJECT_CODE_MAX_LEN
    )
    sub_name = st.text_input(
        "📚 Subject Name", placeholder="e.g. Data Structures", max_chars=SUBJECT_NAME_MAX_LEN
    )
    sub_section = st.text_input("🏷️  Section", placeholder="e.g. A")

    st.markdown("<div style='margin-top:8px'></div>", unsafe_allow_html=True)

    if st.button("✨  Create Subject", type="primary", width="stretch"):
        error = validate_subject_fields(sub_id, sub_name, sub_section)
        if error:
            st.warning(f"⚠️ {error}")
            return
        try:
            try:
                created = create_subject(
                    sub_id.strip(),
                    sub_name.strip(),
                    sub_section.strip(),
                    teach_id,
                    join_code=None,
                )
            except TypeError:
                # Pre-Phase-0 db signature without join_code.
                logger.warning("create_subject has no join_code parameter yet")
                created = create_subject(
                    sub_id.strip(), sub_name.strip(), sub_section.strip(), teach_id
                )
        except Exception:
            logger.exception("Create subject failed")
            st.error("❌ Could not create the subject. Please try again.")
            return
        join_code = None
        if created:
            first = created[0] if isinstance(created, list) else created
            if isinstance(first, dict):
                join_code = first.get("join_code")
        st.toast("🎉 Subject created successfully!")
        if join_code:
            st.success("Subject created. Share this join code with students:")
            st.code(join_code, language="text")
        st.rerun()
