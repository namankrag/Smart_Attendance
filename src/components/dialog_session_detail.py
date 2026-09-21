import streamlit as st
from src.database.db import get_session_details, update_attendance_status
from src.components.dialog_utils import dialog_banner
from src.ui.base_layout import is_dark_theme


@st.dialog("Session Details", width="large")
def session_detail_dialog(subject_id, timestamp, subject_name, filter_type):
    """
    Show present or absent students for a specific attendance session,
    with a toggle button beside each student.

    Parameters
    ----------
    subject_id : int
        Subject whose session we are inspecting.
    timestamp : str
        Session timestamp (second-precision, e.g. '2025-09-20T10:30:00').
    subject_name : str
        Human-readable subject name shown in the banner.
    filter_type : str
        'present' → show present students with Mark-Absent buttons.
        'absent'  → show absent students with Mark-Present buttons.
    """
    is_present_view = filter_type == "present"
    theme = "teal" if is_present_view else "pink"
    title = "Present Students" if is_present_view else "Absent Students"
    dialog_banner(title, subtitle=subject_name, theme=theme)

    dark = is_dark_theme()
    details = get_session_details(subject_id, timestamp)

    filtered = [d for d in details if d.get('is_present') == is_present_view]

    # ── Empty state ───────────────────────────────────────────────
    if not filtered:
        lbl = "present" if is_present_view else "absent"
        st.info(f"No {lbl} students for this session.")
        return

    # ── Count badge ───────────────────────────────────────────────
    n = len(filtered)
    lbl_col = "#94a3b8"
    accent = "#4ade80" if (is_present_view and dark) else "#22c55e" if is_present_view else "#f87171" if dark else "#ef4444"
    st.html(
        f'<p style="font-family:Outfit,sans-serif;font-size:0.88rem;color:{lbl_col};margin:0 0 10px 0;">'
        f'<span style="font-weight:700;color:{accent};font-size:1.1rem;">{n}</span>'
        f' student{"s" if n != 1 else ""}'
        f'</p>'
    )

    # ── Student rows ──────────────────────────────────────────────
    row_bg = "rgba(34,197,94,0.08)" if is_present_view else "rgba(239,68,68,0.08)"
    divider_col = "#1e293b" if dark else "#f1f5f9"

    for idx, record in enumerate(filtered):
        student = record.get('students') or {}
        name = student.get('name', 'Unknown')
        log_id = record.get('id')

        col1, col2 = st.columns([3, 1], vertical_alignment='center')
        with col1:
            icon = "✅" if is_present_view else "❌"
            st.html(
                f'<div style="padding:10px 16px;border-radius:12px;background:{row_bg};'
                f'font-family:Outfit,sans-serif;font-weight:600;font-size:0.95rem;">'
                f'{icon}  {name}</div>'
            )
        with col2:
            if is_present_view:
                if st.button("Mark Absent", key=f"toggle_{log_id}", type="secondary", width="stretch"):
                    update_attendance_status(log_id, False)
                    st.toast(f"📝 {name} marked absent", icon="✅")
                    st.rerun()
            else:
                if st.button("Mark Present", key=f"toggle_{log_id}", type="primary", width="stretch"):
                    update_attendance_status(log_id, True)
                    st.toast(f"📝 {name} marked present", icon="✅")
                    st.rerun()

        # subtle divider between rows
        if idx < n - 1:
            st.html(f'<hr style="margin:4px 0;border:none;height:1px;background:{divider_col};" />')
