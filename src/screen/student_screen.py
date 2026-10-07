import streamlit as st
from PIL import Image
import time
from typing import List, Dict, Any

from src.ui.base_layout import style_base_layout, style_bg_dashboard, is_dark_theme
from src.components.header import header_dashboard, theme_toggle
from src.components.footer import footer_dashboard
from src.pipelines.face_pipeline import predict_attendance, get_face_embeddings, train_classifier, validate_liveness
from src.pipelines.voice_pipeline import get_voice_embedding
from src.database.db import (
    get_all_students, 
    create_student, 
    get_student_subjects, 
    get_student_attendance, 
    unenroll_student_to_subject, 
    add_student_face_embedding,
    check_pass
)
from src.components.dialog_enroll import enroll_dialog
from src.components.subject_card import subject_card
from src.components.dialog_student_attendance import student_attendance_history

@st.dialog("📸 Update Face Profile", width="medium")
def add_face_scan_dialog(student_id: int):
    st.markdown("### Update Your Face Profile")
    st.caption("Add an additional face scan (e.g. with/without glasses, different hairstyle or lighting) so FaceID recognizes you under any condition.")
    
    cam_scan = st.camera_input("Capture face snapshot", key="modal_face_update_cam")
    if cam_scan:
        img = Image.open(cam_scan).convert("RGB")
        with st.spinner("Analyzing biometric features..."):
            is_live, liveness_msg = validate_liveness(img)
            if not is_live:
                st.error(f"🛡️ Anti-Spoofing Alert: {liveness_msg}")
            else:
                encodings = get_face_embeddings(img, num_jitters=3, is_single_face=True)
                if not encodings:
                    st.error("❌ No face detected. Ensure good lighting and look directly into the camera.")
                elif len(encodings) > 1:
                    st.warning("⚠️ Multiple faces detected! Ensure only you are in the frame.")
                else:
                    new_emb = encodings[0].tolist()
                    res = add_student_face_embedding(student_id, new_emb)
                    if res:
                        train_classifier()
                        st.toast("✅ Biometric profile updated successfully!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Failed to update biometric profile.")

def student_dashboard():
    stud_data = st.session_state.student_data
    stud_id = stud_data["student_id"]

    header_dashboard()

    # ── Sidebar Navigation ──
    with st.sidebar:
        st.markdown(
            f"""<div style="padding:.4rem 0 1rem;">
              <div style="font-size:1.1rem;font-weight:800;letter-spacing:.03em;">🎓 SmartClass</div>
              <div style="font-size:.82rem;opacity:.6;margin-top:2px;">Welcome, {stud_data.get('name', 'Student')}</div>
            </div>""",
            unsafe_allow_html=True,
        )
        st.divider()
        st.caption("BIOMETRIC SETTINGS")
        if st.button("Add Extra Face Scan", type="primary", icon=":material/face:", width="stretch", key="btn_add_face_scan"):
            add_face_scan_dialog(stud_id)

        st.divider()
        st.caption("ACCOUNT")
        if st.button("Logout", type="secondary", icon=":material/logout:", width="stretch", key="sidebar_logout"):
            st.session_state.is_logged_in = False
            st.session_state.camera_active = False
            st.session_state.pop("student_data", None)
            st.session_state["login_type"] = None
            st.rerun()
        theme_toggle("sidebar_student")

    st.space()
    c1, c2 = st.columns(2)
    with c1:
        st.header("Enrolled Subjects")
    with c2:
        if st.button("Enroll in subject", type="primary", width="stretch", icon=":material/add_circle:", key="btn_open_enroll"):
            enroll_dialog()

    st.divider()

    with st.spinner("Loading enrolled classes..."):
        enrollments = get_student_subjects(stud_id)
        raw_logs = get_student_attendance(stud_id)

    if not enrollments:
        dark = is_dark_theme()
        empty_bg = "#1e293b" if dark else "white"
        st.html(
            f'<div style="text-align:center;padding:50px 20px;background:{empty_bg};border-radius:20px;margin-top:10px;">'
            '<div style="font-size:3rem;margin-bottom:10px;">📚</div>'
            '<p style="font-family:Outfit,sans-serif;font-size:1.1rem;font-weight:600;">'
            'You are not enrolled in any subjects yet.<br/>'
            '<span style="font-weight:400;font-size:0.9rem;color:#94a3b8;">Click "Enroll in subject" to join a class using your teacher\'s code.</span>'
            '</p></div>'
        )
        footer_dashboard()
        return

    # Index raw logs by subject_id
    logs_by_subject: Dict[int, List[Dict[str, Any]]] = {}
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

        total_classes = sub.get("total_classes", 0)
        user_logs = logs_by_subject.get(sid, [])
        attended_classes = sum(1 for log in user_logs if log.get("is_present"))
        absent_classes = max(0, total_classes - attended_classes)

        # Build dynamic subject log history
        subject_logs: List[Dict[str, Any]] = list(user_logs)
        recorded_timestamps = {str(log.get("timestamp")) for log in user_logs if log.get("timestamp")}
        for ts in sub.get("session_timestamps", []):
            if str(ts) not in recorded_timestamps:
                subject_logs.append({"timestamp": ts, "is_present": False})

        def attendance_actions(
            bound_name=sub_name, 
            bound_logs=subject_logs, 
            bound_sid=sid,
            attended=attended_classes, 
            absent=absent_classes
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
            if st.button(
                "Unenroll from course", 
                type="tertiary", 
                width="stretch",
                icon=":material/delete_forever:", 
                key=f"unenroll_{bound_sid}"
            ):
                result = unenroll_student_to_subject(stud_id, bound_sid)
                if result.get("success"):
                    st.toast(f"✅ Unenrolled from {bound_name}!")
                else:
                    st.error(f"Failed to unenroll: {result.get('error')}")
                time.sleep(1)
                st.rerun()

        with cols[i % 2]:
            subject_card(
                name=sub_name,
                code=sub_code,
                section=sub_section,
                stats=[("📅", "Total classes", total_classes)],
                action_callback=attendance_actions,
                footer_callback=unenrolled
            )

    footer_dashboard()

def student_screen():
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
        st.markdown(f"""
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
        """, unsafe_allow_html=True)

        if "camera_active" not in st.session_state:
            st.session_state.camera_active = False

        if not st.session_state.camera_active:
            box_bg = "#1e293b" if dark else "white"
            box_border = "border:1px solid #334155;" if dark else ""
            txt1_col = "#e2e8f0" if dark else "#64748b"

            st.html(
                f'<div style="text-align:center;padding:34px 20px;background:{box_bg};{box_border}border-radius:18px;margin-bottom:14px;">'
                '<div style="font-size:2.6rem;margin-bottom:8px;">📷</div>'
                f'<p style="font-family:Outfit,sans-serif;color:{txt1_col};font-size:0.95rem;margin:0 0 4px;">'
                'Camera is in standby mode.</p>'
                '</div>'
            )
            if st.button("🔓  Activate Face Scanner", type="primary", width="stretch", key="btn_activate_scanner"):
                st.session_state.camera_active = True
                st.rerun()
        else:
            col_cam, col_off = st.columns([5, 1], vertical_alignment="bottom")
            with col_off:
                if st.button("Turn Off", type="secondary", key="btn_deactivate_cam"):
                    st.session_state.camera_active = False
                    st.rerun()

            with col_cam:
                photo_src = st.camera_input("Center your face in the camera viewport", key="login_face_input")

            if photo_src:
                img = Image.open(photo_src).convert("RGB")
                with st.spinner("Verifying live presence & biometric signature..."):
                    is_live, liveness_msg = validate_liveness(img)
                    if not is_live:
                        st.error(f"🛡️ Anti-Spoofing Alert: {liveness_msg}")
                        st.caption("Please face the camera directly in natural lighting. Digital screens and printed photos are strictly rejected.")
                    else:
                        detected, all_ids, num_faces = predict_attendance(
                            img, 
                            distance_threshold=0.38, 
                            num_jitters=2, 
                            is_single_face=True
                        )

                        if detected:
                            matched_sid = list(detected.keys())[0]
                            all_students = get_all_students()
                            matched_student = next((s for s in all_students if s["student_id"] == matched_sid), None)
                            if matched_student:
                                st.session_state.camera_active = False
                                st.session_state.is_logged_in = True
                                st.session_state.user_role = "student"
                                st.session_state.student_data = matched_student
                                st.toast(f"Welcome back, {matched_student['name']}! 👋")
                                time.sleep(1)
                                st.rerun()
                        elif num_faces == 0:
                            st.warning("⚠️ No face detected. Please position yourself clearly in good lighting.")
                        elif num_faces > 1:
                            st.warning("⚠️ Multiple faces detected! Ensure only you are in the frame.")
                        else:
                            st.info("Face not recognized in system. Register a new student profile below.")
                            st.session_state.show_student_reg = True

        if st.session_state.get("show_student_reg"):
            with st.container(border=True):
                st.subheader("Register New Student Profile")
                reg_name = st.text_input("Full Name", placeholder="e.g. Alex Johnson", key="reg_stud_name")
                reg_pin = st.text_input("Security PIN (4 digits)", type="password", max_chars=6, placeholder="e.g. 1234", key="reg_stud_pin")
                st.caption("Optional: Voice Enrollment")
                audio_sample = st.audio_input("Record utterance (e.g. 'I am present')", key="reg_voice_sample")

                if st.button("Create Student Account", type="primary", width="stretch", key="btn_create_student_acc"):
                    if not reg_name.strip():
                        st.warning("Please enter your name.")
                    elif not st.session_state.camera_active:
                        st.warning("Please activate camera and take a face photo first.")
                    else:
                        with st.spinner("Processing biometric enrolment..."):
                            encodings = get_face_embeddings(img, num_jitters=3, is_single_face=True)
                            if encodings:
                                face_emb = encodings[0].tolist()
                                voice_emb = None
                                if audio_sample:
                                    voice_emb = get_voice_embedding(audio_sample.read())
                                created = create_student(reg_name, face_emb, voice_emb, pin=reg_pin)
                                if created:
                                    train_classifier()
                                    st.session_state.is_logged_in = True
                                    st.session_state.user_role = "student"
                                    st.session_state.student_data = created[0]
                                    st.toast(f"🎉 Profile created! Welcome {reg_name}")
                                    time.sleep(1)
                                    st.rerun()

    with tab_pin:
        st.subheader("Login with Student ID & PIN")
        login_sid = st.text_input("Student ID", placeholder="e.g. 101", key="login_pin_sid")
        login_pin = st.text_input("PIN", type="password", placeholder="Enter your PIN", key="login_pin_val")

        if st.button("Sign In with PIN", type="primary", width="stretch", key="btn_login_pin_submit"):
            if login_sid and login_pin:
                try:
                    sid_int = int(login_sid.strip())
                    students = get_all_students()
                    found = next((s for s in students if s["student_id"] == sid_int), None)
                    if found:
                        # If pin_hash stored, verify it, or allow initial login
                        pin_hash = found.get("pin_hash")
                        if pin_hash:
                            if check_pass(login_pin, pin_hash):
                                st.session_state.is_logged_in = True
                                st.session_state.user_role = "student"
                                st.session_state.student_data = found
                                st.toast(f"Welcome back, {found['name']}!")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error("❌ Invalid PIN")
                        else:
                            # Account exists without PIN yet
                            st.session_state.is_logged_in = True
                            st.session_state.user_role = "student"
                            st.session_state.student_data = found
                            st.toast(f"Welcome back, {found['name']}!")
                            time.sleep(1)
                            st.rerun()
                    else:
                        st.error("❌ Student ID not found.")
                except ValueError:
                    st.error("❌ Student ID must be an integer.")
            else:
                st.warning("Please fill in Student ID and PIN.")

    footer_dashboard()
