import base64

import streamlit as st
import pandas as pd
import logging
from datetime import datetime
from src.pipelines.voice_pipeline import get_voice_embedding, process_bulk_audio
from src.database.db import (
    get_enrolled_students,
    get_subject_by_id,
    update_voice_embedding,
)
from src.components.dialog_attend_result import show_attendance
from src.components.dialog_utils import dialog_banner
from src.ui.base_layout import is_dark_theme
from src.ui.worker_client import WorkerError, get_worker_client

logger = logging.getLogger(__name__)

# Legacy (un-namespaced) results key, cleared on open for hygiene.
_LEGACY_RESULTS_KEY = "voice_attendance_results"


def _results_key(teacher_id, subject_id) -> str:
    """Namespaced session key for voice results: one slot per teacher+subject."""
    return f"smartclass_voice_{teacher_id}_{subject_id}"


def _build_voice_result(enroll_stud, detected_scores, select_sub_id):
    """Build (DataFrame, attendance logs) from detected voice scores.

    Shared by the ML-worker path and the legacy in-process path so both
    render identical results.
    """
    res_rows, attend_logs = [], []
    current_timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    for node in enroll_stud:
        stud = node.get("students")
        if not stud:
            continue
        sid = stud["student_id"]
        score = detected_scores.get(sid, 0.0)
        is_present = bool(score > 0)

        res_rows.append({
            "Name": stud["name"],
            "ID": sid,
            "Score": round(float(score), 3) if is_present else "-",
            "Status": "✅ Present" if is_present else "❌ Absent"
        })
        attend_logs.append({
            "student_id": sid,
            "subject_id": select_sub_id,
            "timestamp": current_timestamp,
            "is_present": is_present
        })
    return pd.DataFrame(res_rows), attend_logs


@st.fragment(run_every="2s")
def _voice_job_poller_fragment(client, key, select_sub_id):
    """Poll a pending voice job from a fragment (Phase 2.2).

    On completion, builds the result rows from the worker's identified
    speakers and stores them under the dialog's results key, then
    reruns once so the dialog renders them. On failure, records a
    generic failure flag (the dialog shows a generic error and the
    teacher can retry with the legacy path).
    """
    pending = st.session_state.get(f"{key}_voice_job_pending")
    if not pending:
        return
    try:
        job = client.get_job(str(pending["job_id"]))
    except WorkerError:
        st.warning("Waiting for the ML worker… (poll failed, retrying)")
        return
    status = str(job.get("status", "unknown"))
    progress = int(job.get("progress") or 0)
    st.progress(min(100, max(0, progress)), text=f"ML worker: {status} ({progress}%)")
    if status not in ("done", "failed"):
        return
    st.session_state.pop(f"{key}_voice_job_pending", None)
    if status == "failed" or job.get("error"):
        logger.warning("ML worker voice job failed: %s", job.get("error"))
        st.session_state[f"{key}_voice_job_failed"] = True
        st.rerun()
        return
    identified = (job.get("result") or {}).get("identified") or {}
    detected_scores = {sid: float(score) for sid, score in identified.items()}
    df_res, logs = _build_voice_result(
        pending["enroll_stud"], detected_scores, select_sub_id)
    st.session_state[key] = (df_res, logs, pending["missing_voiceprint_names"])
    st.rerun()


def _resolve_teacher_id(teacher_id):
    if teacher_id is not None:
        return teacher_id
    teacher_data = st.session_state.get("teacher_data") or {}
    return teacher_data.get("teacher_id")


def _resolve_subject_name(subject_id, subject_name):
    """Subject name for the banner — via db.py, never direct Supabase.

    Phase 1: all DB access goes through ``src/database/db.py`` with
    explicit column lists (audit 37: UI code called Supabase directly
    with ``select("*")``). Failures return "" (the banner tolerates a
    missing name); they are logged server-side, never shown raw.
    """
    if subject_name:
        return subject_name
    try:
        subject = get_subject_by_id(subject_id)
        if subject:
            return subject.get("name") or ""
    except Exception:
        logger.exception("Failed to resolve subject name for %s", subject_id)
    return ""


@st.dialog("Voice Attendance", width="medium")
def voice_attendance(select_sub_id, teacher_id=None, subject_name: str = None):
    teacher_id = _resolve_teacher_id(teacher_id)
    subject_name = _resolve_subject_name(select_sub_id, subject_name)
    key = _results_key(teacher_id, select_sub_id)

    # Clear namespaced results on dialog OPEN (stale results from a
    # previous run for this teacher+subject must not leak into this one).
    # They are cleared again on close/discard/save by show_attendance
    # via results_session_key=key (which also clears the open marker).
    # NOTE: a @st.dialog function re-executes on every rerun while it is
    # open, so the clear must be guarded by a once-per-opening marker —
    # an unconditional pop() here would wipe the results immediately
    # after Analyze, on the next rerun. There is no Streamlit hook for
    # the dialog's X/Escape close; that path leaves results + marker in
    # place until the next Save/Discard clears them.
    open_marker = f"{key}_open"
    if not st.session_state.get(open_marker):
        st.session_state.pop(key, None)
        st.session_state.pop(_LEGACY_RESULTS_KEY, None)
        st.session_state.pop(f"{key}_voice_job_pending", None)
        st.session_state.pop(f"{key}_voice_job_failed", None)
        st.session_state[open_marker] = True

    dialog_banner(
        "Voice Attendance",
        subtitle="AI listens and identifies each student's voice",
        theme="blue"
    )
    dark = is_dark_theme()

    box_bg = "rgba(30, 58, 138, 0.3)" if dark else "linear-gradient(135deg, #e0f2fe, #dbeafe)"
    box_border = "#3b82f6" if dark else "#4facfe"
    box_text = "#93c5fd" if dark else "#1e40af"

    st.markdown(f"""
        <div style="
            background: {box_bg};
            border-left: 4px solid {box_border};
            border-radius: 12px;
            padding: 12px 16px;
            margin-bottom: 16px;
            font-family: Outfit, sans-serif;
            font-size: 0.92rem;
            color: {box_text};
        ">
            🎙️ Ask students to say <b>"I am present"</b> or their name.
            Record classroom audio, then click Analyze.
        </div>
    """, unsafe_allow_html=True)

    audio_data = st.audio_input("🎤 Record Classroom Audio", key="voice_rec_input")
    st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)

    if st.button("🔍  Analyze Audio", width="stretch", type="primary", key="btn_analyze_audio"):
        if not audio_data:
            st.warning("⚠️ Please record audio before analyzing.")
            return

        with st.spinner("🧠 AI is analyzing voice prints…"):
            # Phase 1: enrolments come from db.get_enrolled_students
            # (explicit columns, paginated) — never a direct
            # `select("*, students(*)")` from UI code (audit 37).
            enroll_stud = []
            _offset = 0
            while True:
                _page = get_enrolled_students(select_sub_id, limit=1000, offset=_offset)
                if not _page:
                    break
                enroll_stud.extend(_page)
                _offset += len(_page)
                if len(_page) < 1000:
                    break

            if not enroll_stud:
                st.warning("⚠️ No students enrolled in this subject!")
                return

            # Student IDs are UUID strings — use them exactly as returned.
            candidate_dict = {
                s["students"]["student_id"]: s["students"]["voice_embedding"]
                for s in enroll_stud
                if s.get("students") and s["students"].get("voice_embedding")
            }

            # Enrolled students with NO voiceprint can never be detected:
            # list them (instead of silently marking them absent) and
            # require explicit confirmation before saving.
            missing_voiceprint_names = [
                s["students"]["name"]
                for s in enroll_stud
                if s.get("students") and not s["students"].get("voice_embedding")
            ]

            if not candidate_dict:
                st.error("❌ No enrolled students have voice profiles registered.")
                if missing_voiceprint_names:
                    st.warning(
                        "Students without a voiceprint: "
                        + ", ".join(missing_voiceprint_names)
                    )
                return

            audio_bytes = audio_data.read()
            # Phase 2: prefer the ML worker when configured — submit one
            # voice job and poll it from a fragment. Any worker failure
            # falls back to the legacy in-process pipeline (logged).
            _submitted_to_worker = False
            _voice_client = get_worker_client()
            if _voice_client is not None:
                try:
                    _job = _voice_client.submit_job(
                        "voice",
                        subject_id=select_sub_id,
                        candidate_ids=list(candidate_dict),
                        payload_b64=base64.b64encode(audio_bytes).decode("ascii"),
                        metadata={"method": "voice_attendance"},
                    )
                    st.session_state[f"{key}_voice_job_pending"] = {
                        "job_id": str(_job["id"]),
                        "enroll_stud": enroll_stud,
                        "missing_voiceprint_names": missing_voiceprint_names,
                    }
                    _submitted_to_worker = True
                    st.rerun()
                except WorkerError:
                    logger.warning(
                        "ML worker voice submit failed; falling back to "
                        "legacy in-process pipeline")
            if not _submitted_to_worker:
                detected_scores = process_bulk_audio(audio_bytes, candidate_dict)
                df_res, logs = _build_voice_result(
                    enroll_stud, detected_scores, select_sub_id)
                st.session_state[key] = (df_res, logs, missing_voiceprint_names)

    # Phase 2: poll a pending voice job from a fragment.
    if st.session_state.get(f"{key}_voice_job_pending"):
        _voice_client = get_worker_client()
        if _voice_client is not None:
            _voice_job_poller_fragment(_voice_client, key, select_sub_id)
        else:
            st.session_state.pop(f"{key}_voice_job_pending", None)
    if st.session_state.pop(f"{key}_voice_job_failed", None):
        st.error("The ML worker could not analyze the audio. Please try again.")

    if st.session_state.get(key):
        st.divider()
        df_res, logs, missing_names = st.session_state[key]
        show_attendance(df_res, logs, subject_name=subject_name,
                        teacher_id=teacher_id, subject_id=select_sub_id,
                        method="voice",
                        missing_voiceprint_names=missing_names,
                        results_session_key=key)


@st.dialog("Re-enrol Voiceprint", width="medium")
def voice_reenroll_dialog(student_id, *, pin_verified: bool = False):
    """Re-record a student's voice sample and update their voice_embedding.

    PIN re-authentication is the CALL SITE's responsibility: the caller
    must verify the student's PIN (against the stored PIN hash) BEFORE
    calling this dialog with ``pin_verified=True``. If ``pin_verified``
    is False, recording is allowed but saving is blocked and the dialog
    says so — a voiceprint must never be overwritten without proving
    the student consents, or anyone could replace someone else's
    voiceprint and then be marked present as them.

    Phase 1: the save goes through ``db.update_voice_embedding`` (the
    Phase 1 db helper), never a direct Supabase call from UI code.
    """
    dialog_banner(
        "Re-enrol Voiceprint",
        subtitle="Record a fresh voice sample to replace the stored voiceprint",
        theme="blue"
    )

    if not pin_verified:
        st.warning(
            "⚠️ PIN re-authentication has not been completed for this student. "
            "The call site must verify the student's PIN before re-enrolment "
            "can be saved — recording below is preview-only until then."
        )

    audio_data = st.audio_input(
        "🎤 Record a voice sample (e.g. say \"I am present\")",
        key="voice_reenroll_input",
    )

    if st.button("💾  Save New Voiceprint", width="stretch", type="primary",
                 key="btn_save_voice_reenroll", disabled=not pin_verified):
        if not audio_data:
            st.warning("⚠️ Please record a voice sample first.")
            return
        with st.spinner("Processing voice sample…"):
            new_embedding = get_voice_embedding(audio_data.read())
        if not new_embedding:
            st.error("❌ Could not extract a voiceprint from that recording. Please try again.")
            return
        try:
            update_voice_embedding(student_id, new_embedding)
        except Exception:
            # Log the DB detail server-side; the UI gets a generic error.
            logger.exception("Failed to update voiceprint for student %s", student_id)
            st.error("❌ Failed to update voiceprint. Please try again.")
            return
        st.toast("✅ Voiceprint updated successfully!", icon="🎙️")
        st.rerun()
