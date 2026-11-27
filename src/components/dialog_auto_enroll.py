"""Quick enrollment from a join-code deep link (?join-code=...).

Enrols by the separate, URL-safe join_code — never by subject_code.
The code is URL-decoded and format-validated before the authenticated
enrollment RPC runs. There is no preliminary subjects-table lookup because
RLS hides classes from students who are not enrolled yet.

Phase 2.1: the ``?join-code`` query param is cleared as soon as this
dialog opens (audit 31) so the code does not linger in the URL or
re-trigger on refresh; validation (including expiry for v1 codes)
lives in ``src/ui/join_codes.py``.
"""

import streamlit as st

from src.database.rest_db import (
    join_subject_by_code,
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


@st.dialog("Quick Enrollment", width="medium")
def auto_enroll(join_code: str):
    # Phase 2.1 (audit 31): clear ?join-code as soon as the dialog
    # opens — before any lookup — so the code never lingers in the URL.
    try:
        st.query_params.clear()
    except Exception:
        pass
    clean_code = validate_join_code(join_code or "")
    dark = is_dark_theme()

    if not clean_code:
        dialog_banner("Not Found", subtitle="This join code does not exist", theme="pink")
        st.error("❌ Join code not found!")
        if st.button("Close", key="btn_close_not_found"):
            st.query_params.clear()
            st.rerun()
        return

    dialog_banner("Quick Enrollment", subtitle="You received a class invitation", theme="purple")

    card_bg = (
        "linear-gradient(135deg, #312e81, #1e1b4b)"
        if dark
        else "linear-gradient(135deg, #ede9fe, #e0e7ff)"
    )
    sub_title_col = "#a5b4fc" if dark else "#5144d3"
    sub_text_col = "#cbd5e1" if dark else "#64748b"

    st.markdown(
        f"""
        <div style="
            background: {card_bg};
            border-radius: 16px;
            padding: 20px;
            text-align: center;
            margin: 10px 0 20px;
        ">
            <div style="font-size: 2.5rem;">🎓</div>
            <p style="
                font-family: Outfit, sans-serif;
                font-size: 1.1rem;
                font-weight: 700;
                color: {sub_title_col};
                margin: 8px 0 4px;
            ">Join the class shared by your teacher</p>
            <p style="
                font-family: Outfit, sans-serif;
                font-size: 0.88rem;
                color: {sub_text_col};
                margin: 0;
            ">Would you like to join this class?</p>
        </div>
    """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✕  No Thanks", width="stretch", key="btn_auto_enroll_cancel"):
            st.query_params.clear()
            st.rerun()
    with col2:
        if st.button(
            "🚀  Yes, Enroll!", type="primary", width="stretch", key="btn_auto_enroll_confirm"
        ):
            try:
                subject = join_subject_by_code(clean_code)
            except Exception as exc:
                if "join code not found" in str(exc).lower():
                    st.error("❌ Join code not found. Ask your teacher for a fresh code.")
                    return
                st.error("Could not enroll you. Please try again.")
                return
            if not subject:
                st.error("❌ Join code not found. Ask your teacher for a fresh code.")
                return
            st.success(f"🎉 Joined {subject.get('name', 'the class')} successfully!")
            st.query_params.clear()
            st.rerun()
