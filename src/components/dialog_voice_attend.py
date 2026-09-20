import streamlit as st
import pandas as pd
from datetime import datetime

from src.pipelines.voice_pipeline import process_bulk_audio
from src.database.config import supabase
from src.components.dialog_attend_result import show_attendance
from src.components.dialog_utils import dialog_banner

@st.dialog("Voice Attendance")
def voice_attendance(select_sub_id):
    dialog_banner(
        "Voice Attendance",
        subtitle="AI listens and identifies each student's voice",
        theme="blue"
    )

    st.markdown("""
        <div style="
            background: linear-gradient(135deg, #e0f2fe, #dbeafe);
            border-left: 4px solid #4facfe;
            border-radius: 12px;
            padding: 12px 16px;
            margin-bottom: 16px;
            font-family: Outfit, sans-serif;
            font-size: 0.92rem;
            color: #1e40af;
        ">
            🎙️ Ask students to say <b>"I am present"</b> or their name.
            Record the full classroom audio, then click Analyze.
        </div>
    """, unsafe_allow_html=True)

    audio_data = st.audio_input("🎤 Record Classroom Audio")

    if st.button("🔍  Analyze Audio", width='stretch', type='primary'):
        with st.spinner("🧠 AI is identifying voices…"):
            enroll_res = supabase.table('subject_students').select("*, students(*)").eq('subject_id', select_sub_id).execute()
            enroll_stud = enroll_res.data

            if not enroll_stud:
                st.warning("⚠️ No students enrolled in this subject!")
                return

            candidate_dict = {
                s['students']['student_id']: s['students']['voice_embedding']
                for s in enroll_stud if s['students'].get('voice_embedding')
            }

            if not candidate_dict:
                st.error("❌ No enrolled students have voice profiles registered.")
                return

            audio_byte = audio_data.read()
            detected_scr = process_bulk_audio(audio_byte, candidate_dict)
            res, attend_log = [], []
            crnt_timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

            for node in enroll_stud:
                stud = node['students']
                scr = detected_scr.get(stud['student_id'], 0.0)
                is_presnt = bool(scr > 0)

                res.append({
                    "Name":   stud['name'],
                    "ID":     stud['student_id'],
                    "Score":  round(float(scr), 3) if is_presnt else "-",
                    "Status": "✅ Present" if is_presnt else "❌ Absent"
                })
                attend_log.append({
                    'student_id': stud['student_id'],
                    'subject_id': select_sub_id,
                    'timestamp':  crnt_timestamp,
                    'is_present': bool(is_presnt)
                })

            st.session_state.voice_attendance_results = (pd.DataFrame(res), attend_log)

    if st.session_state.get('voice_attendance_results'):
        st.divider()
        df_res, logs = st.session_state.voice_attendance_results
        show_attendance(df_res, logs)
