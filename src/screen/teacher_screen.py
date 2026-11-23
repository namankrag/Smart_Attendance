"""Teacher screen — Phase 0.

All data access goes through ``src.database.db`` functions (with
``limit``/``offset`` pagination) — never directly through Supabase, and
never with ``select('*')`` from this file. Ownership-sensitive calls
receive ``teacher_id`` so the db layer can enforce ownership. Raw
exceptions / DB details are logged, never shown in the UI.
"""

import html
import logging
from typing import Any, Dict

import streamlit as st
import pandas as pd

from src.ui.base_layout import style_bg_dashboard, style_base_layout, is_dark_theme
from src.components.header import header_dashboard, theme_toggle
from src.components.footer import footer_dashboard
from src.database.db import (
    get_teacher_subjects,
)

# Phase 1 collaborators. Imported defensively like the Phase 0 ones:
# a missing collaborator degrades to a generic UI message, not a crash
# or a direct-Supabase fallback.
try:
    from src.database.db import (
        teacher_login_with_rehash,
        update_teacher_password_hash,
        get_attendance_records,
        count_attendance_for_teacher,
        get_session_counts,
        iter_attendance_csv,
    )
except ImportError:  # pragma: no cover
    teacher_login_with_rehash = None  # type: ignore[assignment]
    update_teacher_password_hash = None  # type: ignore[assignment]
    get_attendance_records = None  # type: ignore[assignment]
    count_attendance_for_teacher = None  # type: ignore[assignment]
    get_session_counts = None  # type: ignore[assignment]
    iter_attendance_csv = None  # type: ignore[assignment]

try:
    from src.database.auth import hash_password
except ImportError:  # pragma: no cover
    hash_password = None  # type: ignore[assignment]

try:
    from src.database.auth_session import (
        require_google_login,
        clear_session_on_logout,
    )
except ImportError:  # pragma: no cover
    require_google_login = None  # type: ignore[assignment]
    clear_session_on_logout = None  # type: ignore[assignment]

# Phase 1: one shared ISO-parsing helper (never crashes on bad input).
from src.database.timeutil import format_iso_timestamp

# Phase 1: structured server-side error logging with correlation IDs.
from src.components.dialog_create_subject import create_subject_dialog
from src.components.subject_card import subject_card
from src.components.dialog_share_subject import share_subject
from src.components.dialog_add_photo import add_photos_dialog, staged_image_bytes
from src.pipelines.face_pipeline import predict_attendance_batch
from src.screen.teacher_jobs import (
    present_attendance_result,
    render_completed_worker_job,
    submit_face_jobs,
)
from src.ui.fragments import (
    PENDING_JOB_KEY,
    poll_pending_jobs_fragment,
)
from src.ui.worker_client import WorkerError, get_worker_client
from src.components.dialog_voice_attend import voice_attendance
from src.components.dialog_delete_subject import confirm_delete_subject
from src.components.dialog_session_detail import session_detail_dialog

# Phase 0 collaborators (db / roster agents). Imported defensively so a
# missing collaborator degrades to a generic UI message, not a crash or a
# direct-Supabase fallback.
try:
    from src.database.db import get_enrolled_students
except ImportError:  # pragma: no cover
    get_enrolled_students = None  # type: ignore[assignment]

try:
    from src.database.db import get_student_for_login
except ImportError:  # pragma: no cover
    get_student_for_login = None  # type: ignore[assignment]

try:
    from src.database.roster import parse_roster_csv
except ImportError:  # pragma: no cover - roster module has not landed yet
    parse_roster_csv = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Page sizes for the paginated db functions.
SUBJECTS_PAGE_SIZE = 100
ENROLLED_PAGE_SIZE = 500
RECORDS_PAGE_SIZE = 200


def _paginated(fn, *args, limit: int, offset: int = 0, **kwargs):
    """Call a db function with limit/offset; fall back to the unpaginated
    signature only if the db layer has not landed the paginated form yet."""
    try:
        return fn(*args, limit=limit, offset=offset, **kwargs)
    except TypeError:
        logger.warning("%s has no limit/offset parameters yet", getattr(fn, "__name__", fn))
        return fn(*args, **kwargs)


def _student_from_enrollment_node(node: Dict[str, Any]) -> Dict[str, Any]:
    """Enrolled-student rows may be nested (``{"students": {...}}``) or flat."""
    nested = node.get("students")
    if isinstance(nested, dict):
        return nested
    return node


def teacher_screen():
    # Phase 1 Google-first (Option A): Google sign-in precedes any
    # teacher username/password step. Without a Google session this
    # redirects to st.login and stops; the screen body never runs
    # logged-out.
    if require_google_login is None:
        logger.error("require_google_login is unavailable; refusing teacher screen")
        st.error("Sign-in is unavailable right now. Please try again later.")
        return
    require_google_login()

    style_bg_dashboard()
    style_base_layout()

    if "teacher_data" in st.session_state:
        teacher_dashboard()
    elif (
        "teacher_login_type" not in st.session_state
        or st.session_state.teacher_login_type == "login"
    ):
        teacher_scrn_login()
    elif st.session_state.teacher_login_type == "register":
        teacher_scrn_register()


def teacher_dashboard():
    header_dashboard()
    st.space()

    if "current_teacher_tab" not in st.session_state:
        st.session_state.current_teacher_tab = "take_attendance"

    teacher_navigation()
    if st.session_state.current_teacher_tab == "take_attendance":
        take_attendance()
    elif st.session_state.current_teacher_tab == "manage_subjects":
        manage_subjects()
    elif st.session_state.current_teacher_tab == "attendance_records":
        attendance_records()

    footer_dashboard()


def teacher_navigation():
    """Render sidebar navigation controls."""
    tabs = (
        ("take_attendance", "Take Attendance", ":material/ar_on_you:"),
        ("manage_subjects", "Manage Subjects", ":material/book_ribbon:"),
        ("attendance_records", "Attendance Records", ":material/cards_stack:"),
    )
    data = st.session_state.teacher_data

    with st.sidebar:
        st.markdown(
            f"""<div style="padding:.4rem 0 1rem;">
              <div style="font-size:1.1rem;font-weight:800;letter-spacing:.03em;">🎓 SmartClass</div>
              <div style="font-size:.82rem;opacity:.6;margin-top:2px;">Welcome, {html.escape(str(data.get("name", "Teacher")))}</div>
            </div>""",
            unsafe_allow_html=True,
        )
        st.divider()
        st.caption("NAVIGATION")
        for tab_id, label, icon in tabs:
            if st.button(
                label,
                key=f"teacher_nav_{tab_id}",
                type="primary" if st.session_state.current_teacher_tab == tab_id else "tertiary",
                icon=icon,
                width="stretch",
            ):
                st.session_state.current_teacher_tab = tab_id
                st.rerun()
        st.divider()
        st.caption("ACCOUNT")
        if st.button(
            "Logout",
            type="secondary",
            icon=":material/logout:",
            width="stretch",
            key="sidebar_logout",
        ):
            # Phase 1: clear EVERY namespaced session key on logout, not
            # just the handful this used to pop (audit 39).
            if clear_session_on_logout is not None:
                clear_session_on_logout()
            else:
                st.session_state.is_logged_in = False
                st.session_state.pop("teacher_data", None)
                st.session_state.pop("current_teacher_tab", None)
                st.session_state.pop("attendance_images", None)
                st.session_state.pop("last_saved_attendance", None)
                st.session_state["login_type"] = None
            st.rerun()
        theme_toggle("sidebar_teacher")


def take_attendance():
    teacher_id = st.session_state.teacher_data["teacher_id"]
    dark = is_dark_theme()
    hero_bg = (
        "linear-gradient(135deg,#12384a,#132442)"
        if dark
        else "linear-gradient(135deg,#ecfeff,#eef2ff)"
    )
    hero_title = "#f8fafc" if dark else "#12304a"
    hero_copy = "#b8c8dc" if dark else "#52647a"
    accent = "#5eead4" if dark else "#0f766e"

    st.html(
        f'<div style="background:{hero_bg};border:1px solid {accent}45;border-radius:20px;padding:2'
            f'4px 26px;margin:2px 0 20px;box-shadow:0 12px 28px rgba(15,23,42,.12);">'
        f'<div style="display:inline-flex;align-items:center;gap:7px;color:{accent};font-size:.76re'
            f'm;font-weight:800;letter-spacing:.1em;text-transform:uppercase;margin-bottom:7px;">'
        "● AI Workspace</div>"
        f'<h2 style="margin:0 0 6px;color:{hero_title}!important;font-size:1.7rem!important;">Autom'
            f'ated Classroom Attendance</h2>'
        f'<p style="margin:0;color:{hero_copy};max-width:670px;">Select your course, add classroom '
            f'photos, and run neural feature extraction to mark attendance.</p>'
        "</div>"
    )

    if "attendance_images" not in st.session_state:
        st.session_state.attendance_images = []

    # Display notification if attendance was recently saved
    if st.session_state.get("last_saved_attendance"):
        last_rec = st.session_state.last_saved_attendance
        with st.container(border=True):
            b_col1, b_col2 = st.columns([3, 1], vertical_alignment="center")
            with b_col1:
                st.success(
                    f"🎉 **Attendance Saved Successfully!** Session logged for *"
                        f"*{html.escape(str(last_rec.get('subject_name', 'Subject')))}** "
                    f"({last_rec.get('present', 0)}/{last_rec.get('total', 0)} Present) at"
                        f" {html.escape(str(last_rec.get('time', '')))}."
                )
            with b_col2:
                if st.button(
                    "📊 View Records", type="secondary", width="stretch", key="btn_view_saved_rec"
                ):
                    st.session_state.current_teacher_tab = "attendance_records"
                    st.session_state.last_saved_attendance = None
                    st.rerun()

    try:
        subjects = _paginated(get_teacher_subjects, teacher_id, limit=SUBJECTS_PAGE_SIZE, offset=0)
    except Exception:
        logger.exception("Failed to load teacher subjects")
        st.error("Could not load your subjects. Please try again.")
        return
    if not subjects:
        st.warning(
            "⚠️ No subjects created yet. Go to 'Manage Subjects' to create your first course."
        )
        return

    sub_opts = {f"{s['name']} ({s['subject_code']})": s["subject_id"] for s in subjects}
    with st.container(border=True):
        st.caption("01  •  CLASS SELECTION")
        col1, col2 = st.columns([3, 1], vertical_alignment="bottom")
        with col1:
            selected_label = st.selectbox(
                "Choose a Subject", options=list(sub_opts.keys()), key="select_attendance_sub"
            )
        with col2:
            if st.button(
                "Add Photos",
                type="primary",
                width="stretch",
                icon=":material/add_a_photo:",
                key="btn_open_add_photo",
            ):
                add_photos_dialog()

    selected_sub_id = sub_opts[selected_label]

    # Phase 2: a worker job that just finished renders its result dialog.
    render_completed_worker_job(selected_sub_id, selected_label)
    # Phase 2: while worker jobs are pending, poll them from a fragment
    # (fragment reruns only itself; the page does not fully rerun).
    if st.session_state.get(PENDING_JOB_KEY):
        _worker_client = get_worker_client()
        if _worker_client is not None:
            poll_pending_jobs_fragment(_worker_client)
        else:
            st.session_state.pop(PENDING_JOB_KEY, None)

    if st.session_state.attendance_images:
        with st.container(border=True):
            st.caption(
                f"02  •  WORKSPACE  •  {len(st.session_state.attendance_images)} PHOTOS LOADED"
            )
            st.subheader("Classroom Photos")
            gallery_cols = st.columns(4)
            for idx, img in enumerate(st.session_state.attendance_images):
                with gallery_cols[idx % 4]:
                    st.image(img, width="stretch", caption=f"Photo {idx + 1}")
                    if st.button(
                        "🗑️ Remove", key=f"btn_remove_ws_img_{idx}", width="stretch", type="tertiary"
                    ):
                        st.session_state.attendance_images.pop(idx)
                        st.rerun()
    else:
        with st.container(border=True):
            st.caption("02  •  WORKSPACE  •  NO PHOTOS LOADED")
            empty_bg = "#1e293b" if dark else "#f8fafc"
            border_c = "#334155" if dark else "#e2e8f0"
            text_title = "#f8fafc" if dark else "#1e293b"
            text_sub = "#94a3b8" if dark else "#64748b"

            st.html(
                f'<div style="text-align:center;padding:24px 18px;background:{empty_bg};border:1px '
                    f'dashed {border_c};border-radius:14px;">'
                '<div style="font-size:2.2rem;margin-bottom:6px;">📸</div>'
                f'<p style="font-family:Outfit,sans-serif;font-size:1.02rem;font-weight:700;color'
                    f':{text_title};margin:0 0 4px;">No classroom photos staged yet</p>'
                f'<p style="font-family:Outfit,sans-serif;font-size:0.86rem;color:{text_sub};margin'
                    f':0;">'
                'Click the <b>"Add Photos"</b> button above to upload group pictures or capture sna'
                    'pshots with your camera.'
                "</p></div>"
            )

    has_photos = bool(st.session_state.attendance_images)

    with st.container(border=True):
        st.caption("03  •  INFERENCE & LOGGING")
        action_title, action_hint = st.columns([2, 3], vertical_alignment="center")
        with action_title:
            st.subheader("Process Attendance")
        with action_hint:
            st.caption("Select face vision scan or voice recognition below.")

        c1, c2, c3 = st.columns([1, 1.35, 1.35])
        with c1:
            if st.button(
                "Clear Photos",
                type="secondary",
                disabled=not has_photos,
                icon=":material/delete:",
                width="stretch",
                key="btn_clear_photos",
            ):
                st.session_state.attendance_images = []
                st.rerun()
        with c2:
            if st.button(
                "Analyze Faces",
                type="primary",
                disabled=not has_photos,
                icon=":material/face:",
                width="stretch",
                key="btn_analyze_faces",
            ):
                with st.spinner("Executing facial feature extraction..."):
                    if get_enrolled_students is None:
                        logger.error("get_enrolled_students is unavailable")
                        st.error("Could not load enrolled students. Please try again.")
                    else:
                        try:
                            enrolled_stud = _paginated(
                                get_enrolled_students,
                                selected_sub_id,
                                limit=ENROLLED_PAGE_SIZE,
                                offset=0,
                            )
                        except Exception:
                            logger.exception("Failed to load enrolled students")
                            st.error("Could not load enrolled students. Please try again.")
                            enrolled_stud = None
                        if enrolled_stud is not None:
                            if not enrolled_stud:
                                st.warning("⚠️ No students enrolled in this course!")
                            else:
                                enrolled_sids = []
                                for node in enrolled_stud:
                                    stud = _student_from_enrollment_node(node)
                                    sid = stud.get("student_id")
                                    if sid is not None:
                                        enrolled_sids.append(sid)
                                # Phase 2: prefer the ML worker when it is
                                # configured — submit one job per staged
                                # photo and poll from a fragment. Any worker
                                # failure falls back to the legacy in-process
                                # pipeline below (logged, never silent).
                                _submitted_to_worker = False
                                _worker_client = get_worker_client()
                                _staged_bytes = staged_image_bytes()
                                if _worker_client is not None and _staged_bytes:
                                    try:
                                        _job_ids = submit_face_jobs(
                                            _worker_client,
                                            _staged_bytes,
                                            selected_sub_id,
                                            enrolled_sids,
                                        )
                                        st.session_state[PENDING_JOB_KEY] = {
                                            "job_ids": _job_ids,
                                            "subject_id": selected_sub_id,
                                            "subject_label": selected_label,
                                            "candidate_ids": enrolled_sids,
                                        }
                                        _submitted_to_worker = True
                                        st.rerun()
                                    except WorkerError:
                                        logger.warning(
                                            "ML worker submit failed; falling back "
                                            "to legacy in-process pipeline"
                                        )
                                if not _submitted_to_worker:
                                    try:
                                        all_detected_ids = predict_attendance_batch(
                                            st.session_state.attendance_images,
                                            candidate_ids=enrolled_sids,
                                            distance_threshold=0.38,
                                        )
                                    except Exception:
                                        logger.exception("Face attendance analysis failed")
                                        st.error("Could not analyze the photos. Please try again.")
                                        all_detected_ids = None
                                    if all_detected_ids is not None:
                                        present_attendance_result(
                                            enrolled_stud,
                                            all_detected_ids,
                                            selected_sub_id,
                                            selected_label,
                                        )
        with c3:
            if st.button(
                "Voice Attendance",
                type="tertiary",
                width="stretch",
                icon=":material/mic:",
                key="btn_voice_modal",
            ):
                voice_attendance(selected_sub_id)


# Phase 2 split: roster import lives in teacher_roster.py, auth screens
# in teacher_auth.py; re-exported here so existing imports keep working.
from src.screen.teacher_auth import (  # noqa: E402, F401
    _public_teacher_record,
    register_teacher_action,
    teacher_scrn_login,
    teacher_scrn_register,
)
from src.screen.teacher_roster import (  # noqa: E402, F401
    _parse_roster_result,
    _roster_import_ui,
    _row_usn,
)


def manage_subjects():
    teacher_id = st.session_state.teacher_data["teacher_id"]
    col1, col2 = st.columns(2)
    with col1:
        st.header("Manage Subjects", width="stretch")
    with col2:
        if st.button(
            "Create New Subject",
            type="primary",
            icon=":material/add_circle:",
            width="stretch",
            key="btn_create_sub",
        ):
            create_subject_dialog(teacher_id)

    try:
        subjects = _paginated(get_teacher_subjects, teacher_id, limit=SUBJECTS_PAGE_SIZE, offset=0)
    except Exception:
        logger.exception("Failed to load teacher subjects")
        st.error("Could not load your subjects. Please try again.")
        return
    if not subjects:
        st.info("No subjects created yet. Click 'Create New Subject' to begin!")
        return

    _roster_import_ui(teacher_id, subjects)

    for i, sub in enumerate(subjects):
        stats = [
            ("👥", "Students", sub.get("total_students", 0)),
            ("📅", "Classes", sub.get("total_classes", 0)),
        ]

        def make_footer(bound_sub=sub, idx=i):
            def footer():
                col_share, col_delete = st.columns(2)
                with col_share:
                    if st.button(
                        "Share Code",
                        key=f"share_{bound_sub['subject_code']}_{idx}",
                        icon=":material/share:",
                        width="stretch",
                    ):
                        # Share the separate join_code, not the subject_code.
                        share_subject(
                            bound_sub["name"],
                            bound_sub["subject_code"],
                            join_code=bound_sub.get("join_code"),
                            subject_id=bound_sub.get("subject_id"),
                        )
                with col_delete:
                    if st.button(
                        "Delete Subject",
                        key=f"delete_{bound_sub['subject_id']}_{idx}",
                        icon=":material/delete_forever:",
                        type="secondary",
                        width="stretch",
                    ):
                        confirm_delete_subject(
                            bound_sub["subject_id"],
                            bound_sub["name"],
                            bound_sub["subject_code"],
                            teacher_id=teacher_id,
                        )
                st.space()

            return footer

        subject_card(
            name=sub["name"],
            code=sub["subject_code"],
            section=sub["section"],
            stats=stats,
            footer_callback=make_footer(),
        )


def attendance_records():
    """Attendance Records — Phase 1: paginated, filterable, CSV export.

    Records are loaded ONE page at a time, filtered server-side
    (subject / present-absent); the totals in the tiles come from SQL
    counts (``count_attendance_for_teacher`` / ``get_session_counts``),
    never from loading every row (Phase 0 audit 9, 23, 24, 50).
    Percentages are rounded, not truncated (audit 50). Timestamps are
    parsed with the shared helper, never an unguarded fromisoformat
    (audit 30). All dynamic strings in the HTML below go through
    ``html.escape`` (audit 40).
    """
    teacher_id = st.session_state.teacher_data["teacher_id"]
    dark = is_dark_theme()

    if get_attendance_records is None or count_attendance_for_teacher is None:
        logger.error("Phase 1 records helpers are unavailable")
        st.error("Could not load attendance records. Please try again.")
        return
    try:
        subjects = _paginated(get_teacher_subjects, teacher_id, limit=SUBJECTS_PAGE_SIZE, offset=0)
    except Exception:
        logger.exception("Failed to load teacher subjects")
        st.error("Could not load attendance records. Please try again.")
        return

    hdr_color = "#818cf8" if dark else "#5144d3"
    sub_color = "#94a3b8"

    st.html(
        '<div style="margin-bottom:6px;">'
        f"<h1 style=\"font-family:'Climate Crisis',sans-serif;font-size:2.4rem;letter-spacing:2px;"
        f'color:{hdr_color};-webkit-text-fill-color:{hdr_color};margin:0 0 4px 0;">Attendance Recor'
            f'ds</h1>'
        f'<p style="font-family:Outfit,sans-serif;color:{sub_color};font-size:0.92rem;margin:0;">'
        "Session breakdown and logs across all enrolled classes</p>"
        "</div>"
    )

    # --- Filters (namespaced keys so logout clears them) ------------------
    subject_labels = {"All subjects": None}
    for s in subjects or []:
        subject_labels[f"{s.get('name', 'Subject')} ({s.get('subject_code', '')})"] = s.get(
            "subject_id"
        )
    f_col1, f_col2 = st.columns(2)
    with f_col1:
        subject_label = st.selectbox(
            "Subject",
            options=list(subject_labels.keys()),
            key="smartclass_records_subject",
        )
    with f_col2:
        status_label = st.selectbox(
            "Status",
            options=["All", "Present", "Absent"],
            key="smartclass_records_status",
        )
    subject_filter = subject_labels.get(subject_label)
    status_filter = {"All": None, "Present": True, "Absent": False}[status_label]

    # --- Totals from SQL counts (not from loaded rows) --------------------
    try:
        total_logs = count_attendance_for_teacher(teacher_id, subject_id=subject_filter)
        total_present = count_attendance_for_teacher(
            teacher_id, subject_id=subject_filter, is_present=True
        )
    except Exception:
        logger.exception("Failed to count attendance records")
        st.error("Could not load attendance records. Please try again.")
        return
    total_sessions = 0
    if get_session_counts is not None:
        scoped_subjects = [
            s
            for s in (subjects or [])
            if subject_filter is None or s.get("subject_id") == subject_filter
        ]
        for s in scoped_subjects:
            try:
                total_sessions += int(get_session_counts(s["subject_id"]).get("total_classes", 0))
            except Exception:
                logger.exception("Session count failed for subject %s", s.get("subject_id"))
    avg_pct = round(total_present / total_logs * 100) if total_logs else 0

    if total_logs == 0:
        empty_bg = "#1e293b" if dark else "white"
        st.html(
            f'<div style="text-align:center;padding:50px 20px;background:{empty_bg};border-radius:2'
                f'0px;margin-top:20px;">'
            '<div style="font-size:3rem;margin-bottom:12px;">📭</div>'
            f'<p style="font-family:Outfit,sans-serif;font-size:1.1rem;color:{sub_color};font-weigh'
                f't:600;">'
            "No attendance records found.<br/>"
            '<span style="font-weight:400;font-size:0.92rem;">Take attendance in a class to generat'
                'e session history.</span>'
            "</p></div>"
        )
        return

    # --- One page of records, newest first --------------------------------
    total_pages = max(1, -(-total_logs // RECORDS_PAGE_SIZE))
    page = int(st.session_state.get("smartclass_records_page", 0) or 0)
    page = max(0, min(page, total_pages - 1))
    try:
        records = get_attendance_records(
            teacher_id,
            subject_id=subject_filter,
            is_present=status_filter,
            limit=RECORDS_PAGE_SIZE,
            offset=page * RECORDS_PAGE_SIZE,
        )
    except Exception:
        logger.exception("Failed to load attendance records")
        st.error("Could not load attendance records. Please try again.")
        return

    # --- Streaming CSV export (DB pages streamed; see db.iter_attendance_csv) ---
    if iter_attendance_csv is not None:
        try:
            csv_text = "".join(iter_attendance_csv(teacher_id, subject_id=subject_filter))
            st.download_button(
                "⬇️ Export CSV",
                data=csv_text,
                file_name="attendance_records.csv",
                mime="text/csv",
                key="btn_export_records_csv",
            )
        except Exception:
            # Export is a convenience, not the page: log and continue.
            logger.exception("Attendance CSV export failed")

    # Session cards below group THIS page's records by session.
    data = []
    for r in records:
        ts = r.get("timestamp")
        sub_info = r.get("subjects") or {}
        data.append(
            {
                "raw_timestamp": ts,
                "ts_group": ts.split(".")[0] if ts else None,
                "Time": format_iso_timestamp(ts),
                "Subject": sub_info.get("name", "Unknown"),
                "Subject Code": sub_info.get("subject_code", "N/A"),
                "subject_id": r.get("subject_id"),
                "is_present": bool(r.get("is_present", False)),
            }
        )

    df = pd.DataFrame(data)
    summary = (
        df.groupby(["raw_timestamp", "ts_group", "Time", "Subject", "Subject Code", "subject_id"])
        .agg(Present_Count=("is_present", "sum"), Total_Count=("is_present", "count"))
        .reset_index()
        .sort_values("raw_timestamp", ascending=False)
    )

    total_students = total_logs

    tiles_config = (
        [
            (
                total_sessions,
                "Sessions",
                "#818cf8",
                "rgba(129, 140, 248, 0.15)",
                "rgba(129, 140, 248, 0.35)",
            ),
            (
                total_students,
                "Total Logs",
                "#c084fc",
                "rgba(192, 132, 252, 0.15)",
                "rgba(192, 132, 252, 0.35)",
            ),
            (
                total_present,
                "Present Entries",
                "#4ade80",
                "rgba(74, 222, 128, 0.15)",
                "rgba(74, 222, 128, 0.35)",
            ),
            (
                f"{avg_pct}%",
                "Avg Attendance",
                "#fbbf24",
                "rgba(251, 191, 36, 0.15)",
                "rgba(251, 191, 36, 0.35)",
            ),
        ]
        if dark
        else [
            (total_sessions, "Sessions", "#667eea", "#ede9fe", "#c4b5fd"),
            (total_students, "Total Logs", "#a855f7", "#f5f3ff", "#ddd6fe"),
            (total_present, "Present Entries", "#22c55e", "#f0fdf4", "#86efac"),
            (f"{avg_pct}%", "Avg Attendance", "#f59e0b", "#fffbeb", "#fde68a"),
        ]
    )

    tiles_html = ""
    for val, lbl, col, bg, border in tiles_config:
        lbl_c = "#94a3b8" if dark else "#64748b"
        tiles_html += (
            f'<div style="flex:1;min-width:120px;background:{bg};border:1px solid {border};border-r'
                f'adius:16px;padding:16px 20px;text-align:center;">'
            f'<div style="font-size:1.9rem;font-weight:800;color:{col};font-family:Outfit,sans-seri'
                f'f;">{val}</div>'
            f'<div style="font-size:0.78rem;color:{lbl_c};font-family:Outfit,sans-serif;margin-top:'
                f'3px;">{lbl}</div>'
            "</div>"
        )

    st.html(
        f'<div style="display:flex;gap:14px;margin:18px 0 22px;flex-wrap:wrap;">{tiles_html}</div>'
    )

    for _, row in summary.iterrows():
        present = int(row["Present_Count"])
        total = int(row["Total_Count"])
        absent = total - present
        pct = int(present / total * 100) if total else 0

        bar_color = (
            "#4ade80"
            if (pct >= 70 and dark)
            else "#fbbf24"
            if (pct >= 40 and dark)
            else "#f87171"
            if dark
            else ("#22c55e" if pct >= 70 else "#f59e0b" if pct >= 40 else "#ef4444")
        )
        bar_bg = (
            "rgba(34, 197, 94, 0.15)"
            if (pct >= 70 and dark)
            else "rgba(245, 158, 11, 0.15)"
            if (pct >= 40 and dark)
            else "rgba(239, 68, 68, 0.15)"
            if dark
            else ("#dcfce7" if pct >= 70 else "#fef9c3" if pct >= 40 else "#fee2e2")
        )
        bar_border = (
            "rgba(34, 197, 94, 0.35)"
            if (pct >= 70 and dark)
            else "rgba(245, 158, 11, 0.35)"
            if (pct >= 40 and dark)
            else "rgba(239, 68, 68, 0.35)"
            if dark
            else ("#86efac" if pct >= 70 else "#fde68a" if pct >= 40 else "#fca5a5")
        )

        card_bg = "#1e293b" if dark else "white"
        card_title_col = "#f8fafc" if dark else "#1e293b"
        code_badge_bg = (
            "linear-gradient(135deg,#312e81,#4338ca)"
            if dark
            else "linear-gradient(135deg,#e0e7ff,#c7d2fe)"
        )
        code_badge_col = "#a5b4fc" if dark else "#4338ca"
        track_bg = "#334155" if dark else "#f1f5f9"

        subject_name = html.escape(str(row["Subject"]))
        subject_code = html.escape(str(row["Subject Code"]))
        time_label = html.escape(str(row["Time"]))
        card_html = (
            f'<div style="background:{card_bg};border-radius:20px;padding:20px 24px;margin-bottom:1'
                f'4px;border-left:5px solid {bar_color};">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wr'
                f'ap:wrap;gap:8px;margin-bottom:14px;">'
            f'<div><div style="font-family:Outfit,sans-serif;font-size:1.08rem;font-weight:700;colo'
                f'r:{card_title_col};margin-bottom:3px;">{subject_name}</div>'
            f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">'
            f'<span style="background:{code_badge_bg};color:{code_badge_col};padding:2px 12px;borde'
                f'r-radius:20px;font-size:0.82rem;font-weight:600;">{subject_code}</span>'
            f'<span style="font-size:0.82rem;color:#94a3b8;">🕐 {time_label}</span>'
            f"</div></div>"
            f'<div style="background:{bar_bg};color:{bar_color};font-family:Outfit,sans-serif;font-'
                f'size:1.5rem;font-weight:800;padding:6px 18px;border-radius:14px;border:1px solid'
                f' {bar_border};text-align:center;">{pct}%</div>'
            f"</div>"
            f'<div style="background:{track_bg};border-radius:99px;height:8px;overflow:hidden;margi'
                f'n-bottom:10px;">'
            f'<div style="width:{pct}%;height:100%;background:linear-gradient(90deg,{bar_color}88'
                f',{bar_color});border-radius:99px;"></div>'
            f"</div></div>"
        )
        st.html(card_html)

        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button(
                f"✅ {present} Present", key=f"pres_{row['subject_id']}_{row['ts_group']}"
            ):
                session_detail_dialog(
                    int(row["subject_id"])
                    if str(row["subject_id"]).isdigit()
                    else row["subject_id"],
                    row["raw_timestamp"],
                    str(row["Subject"]),
                    "present",
                    teacher_id=teacher_id,
                )
        with b2:
            if st.button(
                f"❌ {absent} Absent",
                key=f"abs_{row['subject_id']}_{row['ts_group']}",
                type="secondary",
            ):
                session_detail_dialog(
                    int(row["subject_id"])
                    if str(row["subject_id"]).isdigit()
                    else row["subject_id"],
                    row["raw_timestamp"],
                    str(row["Subject"]),
                    "absent",
                    teacher_id=teacher_id,
                )
        with b3:
            st.html(
                f'<div style="text-align:center;padding:8px 12px;border-radius:20px;font-size:0.82r'
                    f'em;font-weight:600;font-family:Outfit,sans-serif;background:{card_bg};border:'
                    f'1px solid #334155;">👥 {total} Total</div>'
            )

    # --- Pagination controls (Phase 1) --------------------------------------
    p_col1, p_col2, p_col3 = st.columns([1, 2, 1])
    with p_col1:
        if st.button("← Previous", disabled=page == 0, key="btn_records_prev"):
            st.session_state["smartclass_records_page"] = page - 1
            st.rerun()
    with p_col2:
        st.caption(f"Page {page + 1} of {total_pages} • {total_logs} record(s)")
    with p_col3:
        if st.button("Next →", disabled=page + 1 >= total_pages, key="btn_records_next"):
            st.session_state["smartclass_records_page"] = page + 1
            st.rerun()
