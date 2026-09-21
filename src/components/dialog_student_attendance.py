"""Timestamped attendance history shown from a student's subject card."""

from datetime import datetime

import streamlit as st

from src.components.dialog_utils import dialog_banner
from src.ui.base_layout import is_dark_theme


def _format_timestamp(value) -> str:
    """Return a friendly local-looking display without failing on legacy values."""
    if not value:
        return "Time not recorded"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.strftime("%d %b %Y • %I:%M %p")
    except (TypeError, ValueError):
        return str(value)


@st.dialog("Attendance history", width="medium")
def student_attendance_history(subject_name: str, logs: list[dict], status: str) -> None:
    """Show the attended or absent sessions for one student and one subject."""
    present = status == "present"
    theme = "teal" if present else "pink"
    label = "Attended classes" if present else "Missed classes"
    dialog_banner(label, f"{subject_name} • class-by-class history", theme=theme)

    filtered = [log for log in logs if bool(log.get("is_present")) == present]
    filtered.sort(key=lambda log: str(log.get("timestamp") or ""), reverse=True)

    dark = is_dark_theme()
    accent = "#5eead4" if present and dark else "#0f766e" if present else "#fda4af" if dark else "#e11d48"
    surface = "#17253a" if dark else "#f8fafc"
    border = "#294058" if dark else "#dbe5f0"
    muted = "#d3deec" if dark else "#40566f"

    if not filtered:
        st.info(f"No {status} class records are available for this subject yet.")
        return

    st.html(
        f'<p style="color:{muted};font-size:.93rem;font-weight:700;margin:0 0 10px;">'
        f'{len(filtered)} {status} session{"s" if len(filtered) != 1 else ""}</p>'
    )
    for index, log in enumerate(filtered, start=1):
        timestamp = _format_timestamp(log.get("timestamp"))
        st.html(
            f'<div style="display:flex;align-items:center;gap:13px;background:{surface};border:1px solid {border};'
            f'border-left:4px solid {accent};border-radius:12px;padding:13px 15px;margin:8px 0;">'
            f'<div style="width:30px;height:30px;display:grid;place-items:center;border-radius:50%;background:{accent}20;color:{accent};font-weight:800;">{index}</div>'
            f'<div><div style="color:{accent};font-size:.78rem;font-weight:800;text-transform:uppercase;letter-spacing:.07em;">'
            f'{"Present" if present else "Absent"}</div>'
            f'<div style="color:{muted};font-size:.94rem;margin-top:2px;">{timestamp}</div></div></div>'
        )
