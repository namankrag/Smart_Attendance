import streamlit as st
import pandas as pd
from datetime import datetime
from src.pipelines.voice_pipeline import process_bulk_audio
from src.database.config import supabase
from src.components.dialog_attend_result import show_attendance
from src.components.dialog_utils import dialog_banner
from src.ui.base_layout import is_dark_theme

@st.dialog("Voice Attendance", width="medium")
def voice_attendance(select_sub_id: int):
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
            enroll_res = (
                supabase.table("subject_students")
                .select("*, students(*)")
                .eq("subject_id", select_sub_id)
                .execute()
            )
            enroll_stud = enroll_res.data or []

            if not enroll_stud:
                st.warning("⚠️ No students enrolled in this subject!")
                return

            candidate_dict = {
                s["students"]["student_id"]: s["students"]["voice_embedding"]
                for s in enroll_stud 
                if s.get("students") and s["students"].get("voice_embedding")
            }

            if not candidate_dict:
                st.error("❌ No enrolled students have voice profiles registered.")
                return

            audio_bytes = audio_data.read()
            detected_scores = process_bulk_audio(audio_bytes, candidate_dict)
            
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

            st.session_state.voice_attendance_results = (pd.DataFrame(res_rows), attend_logs)

    if st.session_state.get("voice_attendance_results"):
        st.divider()
        df_res, logs = st.session_state.voice_attendance_results
        show_attendance(df_res, logs)
