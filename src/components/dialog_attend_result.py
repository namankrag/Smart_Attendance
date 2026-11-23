import logging

import streamlit as st
from datetime import datetime
from src.components.dialog_utils import dialog_banner
from src.database.logging_utils import log_exception
from src.ui.base_layout import is_dark_theme

logger = logging.getLogger(__name__)

# NOTE (Phase 0): attendance is saved ONLY via the upsert path in db.py —
#   create_session(subject_id, teacher_id, method='voice' | 'face')
#   create_attendance_upsert(logs, session_id)   # ON CONFLICT upsert
# The plain-insert create_attendance() must NOT be used for saves: a
# re-save of the same session would duplicate rows instead of updating
# them. Those two functions do not exist in db.py yet (Phase 1 adds
# them, together with the sessions table / session_id column); they are
# imported lazily inside _save_attendance() so that importing this
# module still works, and a save attempt before they land fails loudly
# with an explicit message instead of silently falling back to insert.
#
# Assumed db.py contracts (to be confirmed when Phase 1 lands them):
#   create_session(subject_id, teacher_id, method='voice'|'face')
#       -> a session record (dict with "session_id" or "id"), a list
#          containing one such record, or the session id itself (str/int).
#   create_attendance_upsert(logs, session_id)
#       -> upserts one attendance_logs row per log (ON CONFLICT on the
#          session/student key); each log is expected to carry
#          student_id / subject_id / timestamp / is_present, and this
#          module adds "session_id" to every log before calling it.


def _resolve_session_id(session):
    """Extract a session id from whatever shape create_session() returns."""
    if session is None:
        return None
    if isinstance(session, (str, int)):
        return session
    if isinstance(session, list):
        return _resolve_session_id(session[0]) if session else None
    if isinstance(session, dict):
        return session.get("session_id") or session.get("id")
    return getattr(session, "session_id", None) or getattr(session, "id", None)


def _save_attendance(logs, *, teacher_id, subject_id, method, session_id=None):
    """Create a session (if needed) and upsert attendance logs for it.

    Returns the session id used. Raises RuntimeError with a clear
    message if the db.py upsert helpers are not available yet, or if
    the teacher/subject needed to create a session cannot be determined.
    Never falls back to the plain-insert create_attendance().
    """
    try:
        from src.database.db import create_attendance_upsert, create_session
    except ImportError as exc:
        raise RuntimeError(
            "Cannot save attendance: db.py does not yet provide "
            "create_session() / create_attendance_upsert() (Phase 1). "
            "Saving via plain insert is disabled by design, so nothing "
            "was written."
        ) from exc

    if session_id is None:
        if teacher_id is None or subject_id is None:
            raise RuntimeError(
                "Cannot save attendance: teacher_id and subject_id are "
                "required to create a session, and at least one is missing."
            )
        session_id = _resolve_session_id(create_session(subject_id, teacher_id, method=method))
        if session_id is None:
            raise RuntimeError("create_session() did not return a session id.")

    logs_with_session = [dict(log, session_id=session_id) for log in logs]
    create_attendance_upsert(logs_with_session, session_id)
    return session_id


def _clear_result_state(results_session_key=None):
    """Clear staged attendance results (namespaced key + legacy keys)."""
    if results_session_key:
        st.session_state.pop(results_session_key, None)
        # Also clear the voice dialog's once-per-opening marker, so the
        # next opening clears stale state again (see dialog_voice_attend).
        st.session_state.pop(f"{results_session_key}_open", None)
    st.session_state.pop("voice_attendance_results", None)
    st.session_state.attendance_images = []


def show_attendance(
    df,
    logs,
    subject_name: str = "",
    teacher_id=None,
    subject_id=None,
    method: str = "face",
    session_id=None,
    missing_voiceprint_names=None,
    results_session_key: str = None,
):
    """Review strip + Save/Discard for an attendance run.

    Parameters
    ----------
    subject_name : str
        Subject NAME (not just id) shown in the saved banner.
    teacher_id / subject_id :
        Needed to create the session on save. When omitted they are
        derived from ``st.session_state.teacher_data`` and
        ``logs[0]["subject_id"]`` respectively.
    method : str
        'face' or 'voice'; recorded on the session created at save time.
    missing_voiceprint_names : list[str] | None
        Enrolled students with no voiceprint. When non-empty they are
        LISTED here with a warning — without a voiceprint they can never
        be detected, so saving would silently mark them absent — and
        saving requires an explicit confirmation checkbox.
    results_session_key : str | None
        Namespaced session-state key holding this run's results
        (e.g. f"smartclass_voice_{teacher_id}_{subject_id}"); cleared
        on both Discard and successful Save.
    """
    present = sum(1 for log in logs if log.get("is_present"))
    total = len(logs)
    pct = int(present / total * 100) if total else 0
    dark = is_dark_theme()
    missing_voiceprint_names = list(missing_voiceprint_names or [])

    p_bg = "rgba(34, 197, 94, 0.15)" if dark else "linear-gradient(135deg, #43e97b22, #38f9d722)"
    p_border = "rgba(34, 197, 94, 0.35)" if dark else "#43e97b55"
    p_col = "#4ade80" if dark else "#22c55e"

    a_bg = "rgba(239, 68, 68, 0.15)" if dark else "linear-gradient(135deg, #f5576c22, #f093fb22)"
    a_border = "rgba(239, 68, 68, 0.35)" if dark else "#f5576c55"
    a_col = "#f87171" if dark else "#ef4444"

    pct_bg = (
        "rgba(129, 140, 248, 0.15)" if dark else "linear-gradient(135deg, #667eea22, #764ba222)"
    )
    pct_border = "rgba(129, 140, 248, 0.35)" if dark else "#667eea55"
    pct_col = "#818cf8" if dark else "#667eea"

    lbl_col = "#94a3b8"

    # ── Stats strip ────────────────────────────────────────────────
    st.markdown(
        f"""
        <div style="
            display: flex;
            gap: 12px;
            margin-bottom: 16px;
        ">
            <div style="
                flex: 1;
                background: {p_bg};
                border: 1px solid {p_border};
                border-radius: 14px;
                padding: 14px;
                text-align: center;
            ">
                <div style="font-size:1.8rem; font-weight:800; color:{p_col};">
                    {present}
                </div>
                <div style="font-size:0.8rem; color:{lbl_col}; font-family:Outfit,sans-serif;">
                    Present
                </div>
            </div>
            <div style="
                flex: 1;
                background: {a_bg};
                border: 1px solid {a_border};
                border-radius: 14px;
                padding: 14px;
                text-align: center;
            ">
                <div style="font-size:1.8rem; font-weight:800; color:{a_col};">
                    {total - present}
                </div>
                <div style="font-size:0.8rem; color:{lbl_col}; font-family:Outfit,sans-serif;">
                    Absent
                </div>
            </div>
            <div style="
                flex: 1;
                background: {pct_bg};
                border: 1px solid {pct_border};
                border-radius: 14px;
                padding: 14px;
                text-align: center;
            ">
                <div style="font-size:1.8rem; font-weight:800; color:{pct_col};">
                    {pct}%
                </div>
                <div style="font-size:0.8rem; color:{lbl_col}; font-family:Outfit,sans-serif;">
                    Attendance
                </div>
            </div>
        </div>
    """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <p style="
            font-family: Outfit, sans-serif;
            font-size: 0.88rem;
            color: {lbl_col};
            margin-bottom: 6px;
        ">Review student status before confirming. Once saved, records will be logged into session history.</p>
    """,
        unsafe_allow_html=True,
    )

    # ── Students with no voiceprint: warn + list, require explicit confirm ──
    confirmed_missing = True
    if missing_voiceprint_names:
        names = ", ".join(missing_voiceprint_names)
        st.warning(
            f"⚠️ {len(missing_voiceprint_names)} enrolled student(s) have no voiceprint "
            f"and can never be detected by voice — saving will mark them absent: {names}. "
            "Ask them to record a voice sample (or use voice re-enrolment) before saving, "
            "or confirm explicitly to proceed anyway."
        )
        confirm_key = f"confirm_missing_voiceprint_{results_session_key or 'shared'}"
        confirmed_missing = st.checkbox(
            f"I understand {len(missing_voiceprint_names)} student(s) without a voiceprint "
            "will be marked absent if I save now.",
            key=confirm_key,
        )

    st.dataframe(df, hide_index=True, width="stretch")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🗑️  Discard & Close", width="stretch"):
            _clear_result_state(results_session_key)
            st.rerun()
    with col2:
        if st.button(
            "✅  Save and Confirm", type="primary", width="stretch", disabled=not confirmed_missing
        ):
            try:
                resolved_teacher_id = teacher_id
                if resolved_teacher_id is None:
                    teacher_data = st.session_state.get("teacher_data") or {}
                    resolved_teacher_id = teacher_data.get("teacher_id")
                resolved_subject_id = subject_id
                if resolved_subject_id is None and logs:
                    resolved_subject_id = logs[0].get("subject_id")
                saved_session_id = _save_attendance(
                    logs,
                    teacher_id=resolved_teacher_id,
                    subject_id=resolved_subject_id,
                    method=method,
                    session_id=session_id,
                )
                st.session_state.last_saved_attendance = {
                    "subject_name": subject_name,
                    "present": present,
                    "total": total,
                    "time": datetime.now().strftime("%I:%M %p"),
                    "session_id": saved_session_id,
                    "method": method,
                }
                _clear_result_state(results_session_key)
                st.toast("✅ Attendance saved successfully!", icon="🎉")
                st.rerun()
            except Exception:
                # Phase 1: structured server-side log with a correlation
                # ID; the UI gets a generic message + the reference,
                # never a stack trace or DB error text (audit 41).
                ref = log_exception(logger, "attendance_save_failed")
                st.error(f"❌ Could not save attendance. Please try again. (Ref: {ref})")


@st.dialog("Attendance Report", width="large")
def attend_result(
    df,
    logs,
    subject_name: str = "",
    teacher_id=None,
    subject_id=None,
    method: str = "face",
    session_id=None,
    missing_voiceprint_names=None,
    results_session_key: str = None,
):
    sub_title = f"Review before saving • {subject_name}" if subject_name else "Review before saving"
    dialog_banner("Attendance Report", subtitle=sub_title, theme="teal")
    show_attendance(
        df,
        logs,
        subject_name,
        teacher_id=teacher_id,
        subject_id=subject_id,
        method=method,
        session_id=session_id,
        missing_voiceprint_names=missing_voiceprint_names,
        results_session_key=results_session_key,
    )
