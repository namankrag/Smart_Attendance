"""Student screen — Phase 0.

Login is 1:1 only: a face login first claims a Student ID / USN and is then
verified against ONLY that student's template. There is no 1:N face login
here and no bulk student fetch for login.

PIN login is fail-closed: a missing ``pin_hash`` never auto-logs a student
in. Only ``student_id`` (UUID str), ``usn`` and ``name`` are ever stored in
``st.session_state.student_data`` — never ``pin_hash`` or embeddings.

Liveness wording is honest: the checks are heuristic only. Printed-photo /
replay blocking is not guaranteed until Phase 2 PAD is deployed and
evaluated.
"""

import html
import io
import logging
from datetime import date
from typing import Any, Dict, List

import streamlit as st
from PIL import Image

from src.ui.base_layout import style_base_layout, style_bg_dashboard, is_dark_theme
from src.components.header import header_dashboard, theme_toggle
from src.components.footer import footer_dashboard
from src.pipelines.face_pipeline import (
    get_face_embeddings,
    train_classifier,
    validate_liveness,
)
from src.database.rest_db import (
    authenticate_student,
    create_student,
    get_student_subjects,
    get_student_attendance,
)
from src.database.rest_db import leave_subject
from src.ui.data_api import DataApiError, data_api_url

# --- Phase 0 collaborators (provided by the db / pipeline agents) --------
# Imported defensively: if any of these is not present yet, the handlers
# below fail closed (generic error, no login) instead of falling back to
# an insecure path. Do NOT replace these with a local stub.
try:
    from src.database.rest_db import (
        get_student_for_login,
        check_login_allowed,
        record_login_attempt,
    )
except ImportError:  # pragma: no cover - db agent has not landed yet
    get_student_for_login = None  # type: ignore[assignment]
    check_login_allowed = None  # type: ignore[assignment]
    record_login_attempt = None  # type: ignore[assignment]

try:
    from src.database.auth import verify_credential, validate_pin, hash_pin
except ImportError:  # pragma: no cover - auth module has not landed yet
    verify_credential = None  # type: ignore[assignment]
    validate_pin = None  # type: ignore[assignment]
    hash_pin = None  # type: ignore[assignment]

try:
    # Phase 1 rehash write-back helper (db agent).
    from src.database.rest_db import update_student_pin_hash
except ImportError:  # pragma: no cover
    update_student_pin_hash = None  # type: ignore[assignment]

try:
    # Phase 1 Google-first gate (auth_session agent).
    from src.database.auth_session import (
        SupabaseNonceMismatchError,
        require_google_login,
        require_supabase_auth,
    )
except ImportError:  # pragma: no cover
    require_google_login = None  # type: ignore[assignment]
    require_supabase_auth = None  # type: ignore[assignment]
    SupabaseNonceMismatchError = RuntimeError  # type: ignore[assignment,misc]

# Phase 1: one shared ISO-parsing helper (never crashes on bad input).
# Kept deliberately even though unused here: test_student_screen_uses_shared_parser
# guards that this screen imports the shared parser instead of datetime.fromisoformat.
from src.database.timeutil import parse_iso_timestamp  # noqa: F401
# Phase 1: structured server-side error logging with correlation IDs.
from src.database.logging_utils import log_exception

try:
    # Preferred name for the 1:1 check (pipeline agent).
    from src.pipelines.face_pipeline import predict_one_to_one
except ImportError:  # pragma: no cover
    predict_one_to_one = None  # type: ignore[assignment]

try:
    # Fallback name for the same 1:1 check — use only if
    # predict_one_to_one is unavailable.
    from src.pipelines.face_pipeline import verify_face_1to1
except ImportError:  # pragma: no cover
    verify_face_1to1 = None  # type: ignore[assignment]

try:
    from src.pipelines.face_pipeline import find_duplicate_face_owner
except ImportError:  # pragma: no cover
    try:
        from src.database.rest_db import find_duplicate_face_owner  # type: ignore[assignment]
    except ImportError:
        find_duplicate_face_owner = None  # type: ignore[assignment]

try:
    # Phase 3 privacy helpers (DPDP Act 2023): consent recording,
    # under-18 parental-consent gate, access summary, withdrawal and
    # "Delete My Biometric Data". Imported defensively: if the module
    # is unavailable the privacy UI degrades to an error message
    # instead of silently enrolling without consent.
    from src.database.rest_db import (
        PRIVACY_NOTICE_TEXT,
        PRIVACY_NOTICE_VERSION,
        GRIEVANCE_CONTACT,
        record_consent,
        require_biometric_enrolment_allowed,
        is_under_18,
        get_access_summary,
        withdraw_consent,
        delete_my_biometric_data,
    )
except ImportError:  # pragma: no cover - privacy module not present
    PRIVACY_NOTICE_TEXT = ""
    PRIVACY_NOTICE_VERSION = "unknown"
    GRIEVANCE_CONTACT = {"email": "", "response_within_days": 90}
    record_consent = None  # type: ignore[assignment]
    require_biometric_enrolment_allowed = None  # type: ignore[assignment]
    is_under_18 = None  # type: ignore[assignment]
    get_access_summary = None  # type: ignore[assignment]
    withdraw_consent = None  # type: ignore[assignment]
    delete_my_biometric_data = None  # type: ignore[assignment]

from src.components.dialog_enroll import enroll_dialog
from src.components.subject_card import subject_card
from src.components.dialog_student_attendance import student_attendance_history

logger = logging.getLogger(__name__)

try:
    from src.pipelines.voice_pipeline import get_voice_embedding
except ImportError:  # pragma: no cover - voice pipeline not available
    get_voice_embedding = None  # type: ignore[assignment]

# Phase 2 split: auth/session helpers live in student_auth.py and remain
# re-exported here so existing imports keep working.
from src.screen.student_auth import (  # noqa: E402, F401
    FACE_UPDATE_REAUTH_KEY,
    GENERIC_LOCKOUT_ERROR,
    GENERIC_LOGIN_ERROR,
    LIVENESS_NOTE,
    REG_VALIDATED_FRAME_KEY,
    _find_duplicate_owner,
    _login_allowed,
    _lookup_student_for_login,
    _parse_ts,
    _record_login_attempt,
    _set_student_session,
    _validate_pin,
    _verify_face_1to1,
    _verify_pin,
    clear_student_session,
)


def _log_session_timestamp(log: Dict[str, Any]) -> Any:
    session = log.get("attendance_sessions") or {}
    if isinstance(session, list):
        session = session[0] if session else {}
    if isinstance(session, dict) and session.get("started_at"):
        return session["started_at"]
    return log.get("timestamp")


def _classes_needed_for_target(present: int, total: int, target_percent: int) -> int:
    """Minimum consecutive attended classes needed to reach a target rate."""
    if total <= 0:
        return 1
    deficit = target_percent * total - 100 * present
    if deficit <= 0:
        return 0
    denominator = 100 - target_percent
    return (deficit + denominator - 1) // denominator


def student_dashboard():
    stud_data = st.session_state.student_data
    stud_id = stud_data["student_id"]

    header_dashboard()

    # ── Sidebar Navigation ──
    with st.sidebar:
        st.markdown(
            f"""<div style="padding:.4rem 0 1rem;">
              <div style="font-size:1.1rem;font-weight:800;letter-spacing:.03em;">🎓 SmartClass</div>
              <div style="font-size:.82rem;opacity:.6;margin-top:2px;">Welcome, {html.escape(str(stud_data.get("name", "Student")))}</div>
            </div>""",
            unsafe_allow_html=True,
        )
        st.divider()
        st.caption("ACCOUNT")
        if st.button(
            "Logout",
            type="secondary",
            icon=":material/logout:",
            width="stretch",
            key="sidebar_logout",
        ):
            clear_student_session()
            st.rerun()
        theme_toggle("sidebar_student")

    st.space()
    c1, c2 = st.columns(2)
    with c1:
        st.header("Enrolled Subjects")
    with c2:
        if st.button(
            "Enroll in subject",
            type="primary",
            width="stretch",
            icon=":material/add_circle:",
            key="btn_open_enroll",
        ):
            enroll_dialog()

    st.divider()

    with st.spinner("Loading enrolled classes..."):
        try:
            enrollments = get_student_subjects(stud_id)
            raw_logs = get_student_attendance(stud_id, limit=1000)
        except Exception:
            logger.exception("Failed to load student dashboard data")
            st.error("Could not load your subjects. Please try again.")
            footer_dashboard()
            return

    if not enrollments:
        dark = is_dark_theme()
        empty_bg = "#1e293b" if dark else "white"
        st.html(
            f'<div style="text-align:center;padding:50px 20px;background:{empty_bg};border-radius:2'
                f'0px;margin-top:10px;">'
            '<div style="font-size:3rem;margin-bottom:10px;">📚</div>'
            '<p style="font-family:Outfit,sans-serif;font-size:1.1rem;font-weight:600;">'
            "You are not enrolled in any subjects yet.<br/>"
            '<span style="font-weight:400;font-size:0.9rem;color:#94a3b8;">Click "Enroll in subject'
                '" to join a class using your teacher\'s code.</span>'
            "</p></div>"
        )
        footer_dashboard()
        return

    st.caption("Target estimates assume you attend every upcoming class.")

    # Index raw logs by subject_id
    logs_by_subject: Dict[Any, List[Dict[str, Any]]] = {}
    for log in raw_logs:
        sid = log.get("subject_id")
        if sid:
            logs_by_subject.setdefault(sid, []).append(log)

    cols = st.columns(2)
    for i, item in enumerate(enrollments):
        sub = item.get("subjects") or {}
        sid = sub.get("subject_id")
        sub_name = sub.get("name", "Unknown Subject")
        sub_code = sub.get("subject_code", "N/A")
        sub_section = sub.get("section", "A")

        # Keep saved records from an earlier enrollment, but only count
        # sessions without a saved record during the current enrollment.
        enrolled_at = _parse_ts(item.get("enrolled_at"))
        all_session_timestamps = list(sub.get("session_timestamps", []))
        all_user_logs = logs_by_subject.get(sid, [])

        history_logs: List[Dict[str, Any]] = []
        current_logs: List[Dict[str, Any]] = []
        if enrolled_at is None:
            current_logs = list(all_user_logs)
            current_session_timestamps = all_session_timestamps
        else:
            for log in all_user_logs:
                log_session_at = _log_session_timestamp(log)
                log_session_date = _parse_ts(log_session_at)
                if log_session_date is not None and log_session_date < enrolled_at:
                    history_logs.append(log)
                else:
                    current_logs.append(log)
            current_session_timestamps = [
                ts for ts in all_session_timestamps
                if (_parse_ts(ts) or enrolled_at) >= enrolled_at
            ]

        history_session_keys = {
            str(_log_session_timestamp(log))
            for log in history_logs
            if _log_session_timestamp(log)
        }
        current_session_keys = {
            str(ts) for ts in current_session_timestamps if ts
        }
        current_session_keys.update(
            str(_log_session_timestamp(log))
            for log in current_logs
            if _log_session_timestamp(log)
        )
        total_classes = len(history_session_keys) + len(current_session_keys)
        user_logs = history_logs + current_logs
        attended_classes = sum(1 for log in user_logs if log.get("is_present"))
        absent_classes = max(0, total_classes - attended_classes)
        attendance_pct = (
            min(100.0, attended_classes * 100.0 / total_classes)
            if total_classes
            else None
        )
        attendance_pct_display = (
            f"{attendance_pct:.1f}%" if attendance_pct is not None else "N/A"
        )
        classes_to_75 = _classes_needed_for_target(attended_classes, total_classes, 75)
        classes_to_85 = _classes_needed_for_target(attended_classes, total_classes, 85)

        def target_stat(target: int, needed: int):
            if needed == 0:
                return ("🎯", f"{target}% target", "Reached")
            noun = "class" if needed == 1 else "classes"
            return ("🎯", f"{noun} to reach {target}%", needed)

        # Build history from saved records across all enrollments. Synthesize
        # absences only for sessions in the current enrollment period.
        subject_logs: List[Dict[str, Any]] = list(user_logs)
        recorded_timestamps = {
            str(_log_session_timestamp(log))
            for log in current_logs
            if _log_session_timestamp(log)
        }
        for ts in current_session_timestamps:
            if str(ts) not in recorded_timestamps:
                subject_logs.append({"timestamp": ts, "is_present": False})

        def attendance_actions(
            bound_name=sub_name,
            bound_logs=subject_logs,
            bound_sid=sid,
            attended=attended_classes,
            absent=absent_classes,
        ):
            present_col, absent_col = st.columns(2)
            with present_col:
                if st.button(
                    f"✓  {attended} Attended",
                    type="primary",
                    width="stretch",
                    key=f"attended_history_{bound_sid}",
                    icon=":material/calendar_month:",
                ):
                    student_attendance_history(bound_name, bound_logs, "present")
            with absent_col:
                if st.button(
                    f"✕  {absent} Absent",
                    type="secondary",
                    width="stretch",
                    key=f"absent_history_{bound_sid}",
                    icon=":material/event_busy:",
                ):
                    student_attendance_history(bound_name, bound_logs, "absent")

        def unenrolled(bound_sid=sid, bound_name=sub_name):
            # Phase 3 (audit 51): unenrol needs a confirmation step —
            # the old code unenrolled on a single click, with no way
            # back (attendance history for the subject stays, but the
            # enrolment is gone). First click arms the confirmation;
            # only the explicit "Yes, unenroll" click performs it.
            confirm_key = f"confirm_unenroll_{bound_sid}"
            if not st.session_state.get(confirm_key):
                if st.button(
                    "Unenroll from course",
                    type="tertiary",
                    width="stretch",
                    icon=":material/delete_forever:",
                    key=f"unenroll_{bound_sid}",
                ):
                    st.session_state[confirm_key] = True
                    st.rerun()
                return
            st.warning(
                f"Unenroll from {bound_name}? You will stop being marked "
                "in future classes for this subject."
            )
            col_yes, col_no = st.columns(2)
            with col_yes:
                if st.button(
                    "Yes, unenroll",
                    type="primary",
                    width="stretch",
                    key=f"unenroll_confirm_{bound_sid}",
                ):
                    try:
                        result = leave_subject(bound_sid)
                    except Exception:
                        logger.exception("Unenroll failed for student %s", stud_id)
                        st.error("Could not unenroll. Please try again.")
                        return
                    st.session_state.pop(confirm_key, None)
                    if result.get("success"):
                        st.toast(f"✅ Unenrolled from {bound_name}!")
                    else:
                        logger.warning(
                            "Unenroll failed for student %s: %s", stud_id, result.get("error")
                        )
                        st.error("Could not unenroll. Please try again.")
                    st.rerun()
            with col_no:
                if st.button(
                    "Keep me enrolled",
                    type="secondary",
                    width="stretch",
                    key=f"unenroll_cancel_{bound_sid}",
                ):
                    st.session_state.pop(confirm_key, None)
                    st.rerun()

        with cols[i % 2]:
            subject_card(
                name=sub_name,
                code=sub_code,
                section=sub_section,
                stats=[
                    ("📅", "Total classes", total_classes),
                    ("📊", "Current attendance", attendance_pct_display),
                    target_stat(75, classes_to_75),
                    target_stat(85, classes_to_85),
                ],
                action_callback=attendance_actions,
                footer_callback=unenrolled,
            )

    # --- Phase 3: My data & privacy (DPDP Act Sec. 11/12/13) -----------
    # Access summary, correction, consent withdrawal and "Delete My
    # Biometric Data" self-service. Attendance logs are NOT deleted
    # here — they are the academic record; template deletion is what
    # the student controls directly.
    st.divider()
    st.subheader("My data & privacy")
    st.caption(
        "See what data we hold about you, withdraw your biometric "
        "consent, or delete your face/voice templates at any time. "
        "Deleting your templates does not delete your attendance record."
    )
    if get_access_summary is None:
        st.warning("Privacy tools are unavailable right now. Please ask your teacher.")
    else:
        try:
            summary = get_access_summary(stud_id)
        except Exception:
            logger.exception("Access summary failed for student %s", stud_id)
            st.error("Could not load your data summary. Please try again.")
            summary = None
        if summary is not None:
            st.write(f"**Name:** {html.escape(str(summary['student'].get('name', '')))}")
            st.write(f"**USN:** {html.escape(str(summary['student'].get('usn', '')))}")
            st.write(
                f"**Face templates:** {summary['face_templates']['count']} stored | "
                f"**Voice templates:** {summary['voice_templates']['count']} stored | "
                f"**Attendance records:** {summary['attendance']['total_logs']}"
            )
            consent = summary.get("consent")
            if consent:
                st.write(
                    f"**Biometric consent:** {'given' if consent.get('granted') else 'withdrawn'} "
                    f"(notice v{consent.get('notice_version')}, {consent.get('granted_at')})"
                )
            with st.expander("Privacy notice"):
                st.write(PRIVACY_NOTICE_TEXT)
            st.write(
                "Questions or complaints? Contact the grievance officer: "
                f"{html.escape(str(GRIEVANCE_CONTACT.get('email', '')))} "
                f"(reply within {GRIEVANCE_CONTACT.get('response_within_days', 90)} days)."
            )
            col_wd, col_del = st.columns(2)
            with col_wd:
                if st.button("Withdraw biometric consent", key="privacy_withdraw_consent"):
                    if withdraw_consent is None:
                        st.error("Consent withdrawal is unavailable right now.")
                    else:
                        try:
                            withdraw_consent(stud_id)
                            st.success(
                                "Consent withdrawn. Your templates will be deleted — "
                                "use 'Delete My Biometric Data' to delete them now."
                            )
                        except Exception:
                            logger.exception("Consent withdrawal failed for student %s", stud_id)
                            st.error("Could not withdraw consent. Please try again.")
            with col_del:
                if st.button(
                    "Delete My Biometric Data", type="primary", key="privacy_delete_biometrics"
                ):
                    if delete_my_biometric_data is None:
                        st.error("Biometric deletion is unavailable right now.")
                    else:
                        try:
                            result = delete_my_biometric_data(stud_id)
                            st.success(
                                f"Deleted {result['face_templates_deleted']} face template(s) "
                                f"and {result['voice_templates_deleted']} voice template(s). "
                                "You can still attend with your PIN or manual marking."
                            )
                            st.rerun()
                        except Exception:
                            logger.exception("Biometric deletion failed for student %s", stud_id)
                            st.error("Could not delete your biometric data. Please try again.")

    footer_dashboard()


def _handle_pin_login(identifier: str, pin: str) -> None:
    """PIN login: rate-limit first, then lookup, then Argon2 verify.

    Fails closed with a generic message on every failure path, including
    a missing ``pin_hash`` (never auto-login).
    """
    identifier = (identifier or "").strip()
    if not identifier or not pin:
        st.warning("Please fill in Student ID/USN and PIN.")
        return
    if data_api_url():
        try:
            student = authenticate_student(identifier, pin)
        except DataApiError as exc:
            if "too many failed attempts" in str(exc).lower():
                st.error(GENERIC_LOCKOUT_ERROR)
            else:
                logger.info("PIN login rejected for %s", identifier)
                st.error(GENERIC_LOGIN_ERROR)
            return
        _set_student_session(student)
        st.toast(f"Welcome back, {student.get('name', 'Student')}!")
        st.rerun()
        return
    try:
        allowed, _retry = _login_allowed(identifier, "pin")
    except Exception:
        # Live finding 2026-11-22: an unavailable rate-limit store
        # (missing secrets / DB down) raised uncaught
        # (StreamlitSecretNotFoundError) and crashed the app. Fail
        # closed with the generic login error instead — a login that
        # cannot be rate-limited must not proceed. Logged server-side
        # as structured JSON with a correlation ID (Phase 1 hygiene).
        log_exception(logger, "pin_login_rate_limit_check_failed", identifier=identifier)
        st.error(GENERIC_LOGIN_ERROR)
        return
    if not allowed:
        st.error(GENERIC_LOCKOUT_ERROR)
        return
    try:
        found = _lookup_student_for_login(identifier)
    except Exception:
        logger.exception("Student login lookup failed")
        st.error(GENERIC_LOGIN_ERROR)
        return
    if not found:
        _record_login_attempt(identifier, False, "pin")
        st.error(GENERIC_LOGIN_ERROR)
        return
    pin_hash = found.get("pin_hash")
    if not pin_hash:
        # Fail closed: an account without a PIN hash must not be logged in.
        _record_login_attempt(identifier, False, "pin")
        logger.warning("PIN login refused: student %s has no pin_hash", identifier)
        st.error(GENERIC_LOGIN_ERROR)
        return
    try:
        ok, needs_rehash = _verify_pin(pin, pin_hash)
    except Exception:
        logger.exception("PIN verification failed")
        _record_login_attempt(identifier, False, "pin")
        st.error(GENERIC_LOGIN_ERROR)
        return
    _record_login_attempt(identifier, ok, "pin")
    if not ok:
        st.error(GENERIC_LOGIN_ERROR)
        return
    if needs_rehash:
        # Phase 1 carry-over (a): transparent Argon2id rehash
        # write-back on successful login (OWASP Password Storage Cheat
        # Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).
        # The PIN just verified is re-hashed with current parameters and
        # stored, migrating legacy bcrypt hashes exactly once. A failed
        # write is logged and never blocks the login.
        try:
            if update_student_pin_hash is not None and hash_pin is not None:
                update_student_pin_hash(str(found["student_id"]), hash_pin(pin))
            else:
                logger.warning("Rehash helper unavailable; PIN hash not upgraded")
        except Exception:
            logger.exception("PIN rehash write-back failed for student %s", identifier)
    _set_student_session(found)
    st.toast(f"Welcome back, {found.get('name', 'Student')}!")
    st.rerun()


def student_screen():
    # Phase 1 Google-first (Option A): Google sign-in precedes any
    # USN + face/PIN step. Without a Google session this redirects to
    # st.login and stops; the screen body never runs logged-out.
    if require_google_login is None:
        logger.error("require_google_login is unavailable; refusing student screen")
        st.error("Sign-in is unavailable right now. Please try again later.")
        return
    require_google_login()
    if require_supabase_auth is None:
        st.error("Database sign-in is unavailable right now. Please try again later.")
        return
    try:
        require_supabase_auth()
    except SupabaseNonceMismatchError as exc:
        logger.exception("Could not establish the Supabase student session")
        st.error(str(exc))
        return
    except Exception:
        logger.exception("Could not establish the Supabase student session")
        st.error(
            "Could not connect your Google sign-in to the attendance database. "
            "Please check the Streamlit token settings and sign in again."
        )
        return

    style_bg_dashboard()
    style_base_layout()
    dark = is_dark_theme()

    if "student_data" in st.session_state:
        student_dashboard()
        return

    c1, c2 = st.columns(2, vertical_alignment="center", gap="xxlarge")
    with c1:
        header_dashboard()
    with c2:
        b1, b2 = st.columns(2, vertical_alignment="center")
        with b1:
            if st.button("Go to Home", type="secondary", key="backbtn", width="stretch"):
                st.session_state["login_type"] = None
                st.rerun()
        with b2:
            theme_toggle("student_login")

    st.header("Student Portal Access", text_alignment="center")
    st.space()

    tab_face, tab_pin = st.tabs(["📸 FaceID Scanner", "🔑 Student ID & PIN"])

    with tab_face:
        accent_col = "#818cf8" if dark else "#667eea"
        st.markdown(
            f"""
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
                <span style="
                    width: 10px; height: 10px;
                    background: {accent_col};
                    border-radius: 50%;
                    display: inline-block;
                "></span>
                <span style="
                    font-family: 'Outfit', sans-serif;
                    font-size: 0.92rem;
                    font-weight: 600;
                    color: {accent_col};
                    letter-spacing: 1px;
                    text-transform: uppercase;
                ">Instant Biometric Login</span>
            </div>
        """,
            unsafe_allow_html=True,
        )

        # 1:1 face login: the student must claim an identity FIRST.
        login_face_id = st.text_input(
            "Student ID or USN",
            placeholder="e.g. 1CS21CS001",
            key="login_face_usn",
            help="Enter your Student ID or USN first — your face is verified against only that stud"
                "ent's profile.",
        )

        if "camera_active" not in st.session_state:
            st.session_state.camera_active = False

        if not st.session_state.camera_active:
            box_bg = "#1e293b" if dark else "white"
            box_border = "border:1px solid #334155;" if dark else ""
            txt1_col = "#e2e8f0" if dark else "#64748b"

            st.html(
                f'<div style="text-align:center;padding:34px 20px;background:{box_bg};{box_border}b'
                    f'order-radius:18px;margin-bottom:14px;">'
                '<div style="font-size:2.6rem;margin-bottom:8px;">📷</div>'
                f'<p style="font-family:Outfit,sans-serif;color:{txt1_col};font-size:0.95rem;margin'
                    f':0 0 4px;">'
                "Camera is in standby mode.</p>"
                "</div>"
            )
            if st.button(
                "🔓  Activate Face Scanner",
                type="primary",
                width="stretch",
                key="btn_activate_scanner",
            ):
                if not (login_face_id or "").strip():
                    st.warning("Enter your Student ID or USN first.")
                else:
                    st.session_state.camera_active = True
                    st.rerun()
        else:
            col_cam, col_off = st.columns([5, 1], vertical_alignment="bottom")
            with col_off:
                if st.button("Turn Off", type="secondary", key="btn_deactivate_cam"):
                    st.session_state.camera_active = False
                    st.rerun()

            with col_cam:
                photo_src = st.camera_input(
                    "Center your face in the camera viewport", key="login_face_input"
                )

            if photo_src:
                st.caption(
                    "Keep your full face centered with no one else in frame. "
                    "After capture, choose Verify Face to sign in."
                )

            if photo_src and st.button(
                "Verify Face",
                type="primary",
                width="stretch",
                key="btn_verify_face_login",
            ):
                img = Image.open(photo_src).convert("RGB")
                with st.spinner("Verifying live presence & biometric signature..."):
                    is_live, liveness_msg = validate_liveness(img)
                    if not is_live:
                        st.error(f"Liveness check: {liveness_msg}")
                        st.caption(LIVENESS_NOTE)
                    else:
                        identifier = (login_face_id or "").strip()
                        if not identifier:
                            st.warning("Enter your Student ID or USN first.")
                        else:
                            allowed, _retry = _login_allowed(identifier, "face")
                            if not allowed:
                                st.error(GENERIC_LOCKOUT_ERROR)
                            else:
                                try:
                                    claimed = _lookup_student_for_login(identifier)
                                except Exception:
                                    logger.exception("Face login lookup failed")
                                    claimed = None
                                    st.error(GENERIC_LOGIN_ERROR)
                                if claimed is None:
                                    _record_login_attempt(identifier, False, "face")
                                    st.error(GENERIC_LOGIN_ERROR)
                                else:
                                    # 1:1 verification ONLY against the
                                    # claimed student's template. No 1:N
                                    # predict_attendance, no get_all_students.
                                    matched, num_faces = _verify_face_1to1(img, claimed)
                                    _record_login_attempt(identifier, bool(matched), "face")
                                    if matched:
                                        _set_student_session(claimed)
                                        st.toast(
                                            f"Welcome back, {claimed.get('name', 'Student')}! 👋"
                                        )
                                        st.rerun()
                                    elif num_faces == 0:
                                        st.warning(
                                            "⚠️ No face detected. Please position yourself clearly "
                                                "in good lighting."
                                        )
                                    elif num_faces is not None and num_faces > 1:
                                        st.warning(
                                            "⚠️ Multiple faces detected! Ensure only you are in the"
                                                " frame."
                                        )
                                    else:
                                        st.info(
                                            "Face did not match the record for that Student ID/USN."
                                                " Check the ID/USN or register below."
                                        )

        if st.button(
            "Register a new student profile",
            type="secondary",
            width="stretch",
            key="btn_show_student_reg",
        ):
            st.session_state.show_student_reg = True

        if st.session_state.get("show_student_reg"):
            with st.container(border=True):
                st.subheader("Register New Student Profile")
                reg_name = st.text_input(
                    "Full Name", placeholder="e.g. Alex Johnson", key="reg_stud_name"
                )
                reg_usn = st.text_input("USN", placeholder="e.g. 1CS21CS001", key="reg_stud_usn")
                reg_pin = st.text_input(
                    "Security PIN (4-6 digits)",
                    type="password",
                    max_chars=6,
                    placeholder="e.g. 1234",
                    key="reg_stud_pin",
                )
                # Phase 3 (DPDP Act Sec. 5/6/9): plain-language notice,
                # consent, and the under-18 check. Consent is a clear
                # affirmative action (Sec. 6(1)); without it, no
                # biometric template is ever made.
                with st.expander("Privacy notice — read before registering"):
                    st.write(PRIVACY_NOTICE_TEXT)
                reg_consent = st.checkbox(
                    "I have read the privacy notice and consent to my face/voice "
                    "being used only to mark my attendance. I know I can withdraw "
                    "this at any time and still attend with my PIN.",
                    key="reg_stud_consent",
                )
                reg_dob = st.date_input(
                    "Date of birth (to check whether a parent/guardian must also consent)",
                    value=None,
                    min_value=date(1990, 1, 1),
                    max_value=date.today(),
                    key="reg_stud_dob_1990",
                )
                reg_adult = st.checkbox(
                    "I confirm I am 18 or older",
                    key="reg_stud_adult",
                )
                st.caption("Optional: Voice Enrollment")
                audio_sample = st.audio_input(
                    "Record utterance (e.g. 'I am present')", key="reg_voice_sample"
                )
                # Registration uses its own camera capture so the handler
                # below always works on the exact frame being encoded.
                reg_photo = st.camera_input(
                    "Capture a face photo for registration",
                    key="smartclass_reg_camera",
                )

                if st.button(
                    "Create Student Account",
                    type="primary",
                    width="stretch",
                    key="btn_create_student_acc",
                ):
                    reg_name_clean = (reg_name or "").strip()
                    reg_usn_clean = (reg_usn or "").strip()
                    pin_ok, pin_err = _validate_pin(reg_pin or "")
                    if not reg_name_clean:
                        st.warning("Please enter your name.")
                    elif len(reg_name_clean) > 100:
                        st.warning("Name must be 100 characters or fewer.")
                    elif not reg_usn_clean:
                        st.warning("Please enter your USN.")
                    elif not pin_ok:
                        st.warning(pin_err or "PIN must be 4-6 digits.")
                    elif not reg_consent:
                        st.warning(
                            "Please read the privacy notice and tick the consent box "
                            "to use face/voice login. Without it you can still attend "
                            "with your PIN or manual marking — ask your teacher."
                        )
                    elif reg_dob is None and not reg_adult:
                        st.warning(
                            "Please enter your date of birth or confirm you are 18 or "
                            "older, so we know whether a parent/guardian must also consent."
                        )
                    elif is_under_18 is None or is_under_18(
                        reg_dob, is_minor=(False if reg_adult else None)
                    ):
                        # Phase 3 (DPDP Act Sec. 9(1)): under-18s need
                        # verifiable parental consent BEFORE any biometric
                        # template is made. A new student has no parental
                        # consent record yet (the teacher records it
                        # against the student row once it exists), so a
                        # minor registers PIN-only here and adds face/voice
                        # later, after the teacher records the parent's
                        # consent. PIN/manual attendance works with no
                        # penalty in the meantime. Unknown age (or a
                        # missing privacy module) fails closed the same way.
                        st.warning(
                            "You are under 18 (or your age could not be confirmed), "
                            "so no face/voice template can be stored until a parent "
                            "or guardian gives consent in person to your teacher. "
                            "Creating a PIN-only account instead. You can continue "
                            "using Student ID and PIN."
                        )
                        try:
                            _created = create_student(
                                reg_name_clean,
                                None,
                                None,
                                pin=reg_pin,
                                usn=reg_usn_clean,
                            )
                        except TypeError:
                            # Pre-Phase-0 db signature without a USN parameter.
                            _created = create_student(reg_name_clean, None, None, pin=reg_pin)
                        except Exception:
                            logger.exception("PIN-only registration failed")
                            st.error("Could not create your profile. Please try again.")
                            _created = None
                        if _created:
                            _set_student_session(_created[0])
                            st.toast("Profile created (PIN-only).")
                            st.rerun()
                    elif reg_photo is None:
                        st.warning("Please capture a face photo for registration first.")
                    else:
                        # Liveness runs INSIDE this handler, on the exact
                        # frame being encoded. A photo that fails liveness
                        # is never used. The validated frame is kept only
                        # as bytes in a namespaced key and cleared after use.
                        with st.spinner("Processing biometric enrolment..."):
                            try:
                                reg_img = Image.open(reg_photo).convert("RGB")
                                is_live, liveness_msg = validate_liveness(reg_img)
                                if not is_live:
                                    st.error(f"Liveness check: {liveness_msg}")
                                    st.caption(LIVENESS_NOTE)
                                else:
                                    _buf = io.BytesIO()
                                    reg_img.save(_buf, format="JPEG")
                                    st.session_state[REG_VALIDATED_FRAME_KEY] = _buf.getvalue()
                                    encodings = get_face_embeddings(
                                        reg_img, num_jitters=3, is_single_face=True
                                    )
                                    if not encodings:
                                        st.error(
                                            "❌ No face detected. Ensure good lighting "
                                            "and look directly into the camera."
                                        )
                                    elif len(encodings) > 1:
                                        st.warning(
                                            "⚠️ Multiple faces detected! Ensure only you are in the"
                                                " frame."
                                        )
                                    else:
                                        face_emb = encodings[0].tolist()
                                        duplicate = _find_duplicate_owner(face_emb)
                                        if duplicate:
                                            # Generic message: do not reveal
                                            # whose profile matched.
                                            st.error(
                                                "A face profile already exists for another student."
                                                    " Please contact your teacher."
                                            )
                                        else:
                                            voice_emb = None
                                            if audio_sample:
                                                voice_emb = (
                                                    get_voice_embedding(audio_sample.read())
                                                    if get_voice_embedding is not None
                                                    else None
                                                )
                                            try:
                                                created = create_student(
                                                    reg_name_clean,
                                                    face_emb,
                                                    voice_emb,
                                                    pin=reg_pin,
                                                    usn=reg_usn_clean,
                                                )
                                            except TypeError:
                                                # Pre-Phase-0 db signature
                                                # without a USN parameter.
                                                logger.warning(
                                                    "create_student has no usn parameter yet; USN n"
                                                        "ot persisted"
                                                )
                                                created = create_student(
                                                    reg_name_clean, face_emb, voice_emb, pin=reg_pin
                                                )
                                            if created:
                                                # Phase 3 (DPDP Sec. 6(10)):
                                                # record the consent grant
                                                # (notice version + timestamp)
                                                # now that the template exists.
                                                if record_consent is not None:
                                                    try:
                                                        record_consent(created[0]["student_id"])
                                                    except Exception:
                                                        logger.exception(
                                                            "Consent recording failed for student %"
                                                                "s",
                                                            created[0].get("student_id"),
                                                        )
                                                train_classifier()
                                                _set_student_session(created[0])
                                                st.toast(
                                                    f"🎉 Profile created! Welcome {reg_name_clean}"
                                                )
                                                st.rerun()
                                            else:
                                                st.error(
                                                    "Could not create your profile. Please try agai"
                                                        "n."
                                                )
                            except Exception:
                                logger.exception("Student registration failed")
                                st.error("Could not create your profile. Please try again.")
                            finally:
                                st.session_state.pop(REG_VALIDATED_FRAME_KEY, None)

    with tab_pin:
        st.subheader("Login with Student ID & PIN")
        # Phase 3 (GDPR Art. 9; AEPD biometric attendance guidelines;
        # DPDP Act Sec. 6(1)): consent to biometrics is only freely
        # given if there is a real non-biometric alternative. PIN login
        # (and teacher manual marking) is that alternative — a student
        # who never uses face or voice is marked exactly the same way,
        # with no penalty.
        st.info(
            "No face or voice needed: you can attend with your Student ID + PIN, "
            "or your teacher can mark you present manually — with no penalty "
            "and no difference in your attendance record."
        )
        login_sid = st.text_input(
            "Student ID or USN", placeholder="e.g. 1CS21CS001", key="login_pin_sid"
        )
        login_pin = st.text_input(
            "PIN", type="password", placeholder="Enter your PIN", key="login_pin_val"
        )

        if st.button(
            "Sign In with PIN", type="primary", width="stretch", key="btn_login_pin_submit"
        ):
            _handle_pin_login(login_sid, login_pin)

    footer_dashboard()
