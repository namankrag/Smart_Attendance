import streamlit as st
import time
from datetime import datetime
import pandas as pd
from typing import Dict, Any, List

from src.ui.base_layout import style_bg_dashboard, style_base_layout, is_dark_theme
from src.components.header import header_dashboard, theme_toggle
from src.components.footer import footer_dashboard
from src.database.db import (
    check_teacher_exists, 
    create_teacher, 
    teacher_login, 
    get_teacher_subjects, 
    get_attendance_for_teacher
)
from src.components.dialog_create_subject import create_subject_dialog
from src.components.subject_card import subject_card
from src.components.dialog_share_subject import share_subject
from src.components.dialog_add_photo import add_photos_dialog
from src.pipelines.face_pipeline import predict_attendance_batch
from src.database.config import supabase
from src.components.dialog_attend_result import attend_result
from src.components.dialog_voice_attend import voice_attendance
from src.components.dialog_delete_subject import confirm_delete_subject
from src.components.dialog_session_detail import session_detail_dialog

def teacher_screen():
    style_bg_dashboard()
    style_base_layout()

    if "teacher_data" in st.session_state:
        teacher_dashboard()
    elif "teacher_login_type" not in st.session_state or st.session_state.teacher_login_type == "login":
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
        ("take_attendance",    "Take Attendance",    ":material/ar_on_you:"),
        ("manage_subjects",    "Manage Subjects",    ":material/book_ribbon:"),
        ("attendance_records", "Attendance Records", ":material/cards_stack:"),
    )
    data = st.session_state.teacher_data

    with st.sidebar:
        st.markdown(
            f"""<div style="padding:.4rem 0 1rem;">
              <div style="font-size:1.1rem;font-weight:800;letter-spacing:.03em;">🎓 SmartClass</div>
              <div style="font-size:.82rem;opacity:.6;margin-top:2px;">Welcome, {data.get('name', 'Teacher')}</div>
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
        if st.button("Logout", type="secondary", icon=":material/logout:", width="stretch", key="sidebar_logout"):
            st.session_state.is_logged_in = False
            st.session_state.pop("teacher_data", None)
            st.session_state["login_type"] = None
            st.rerun()
        theme_toggle("sidebar_teacher")

def take_attendance():
    teacher_id = st.session_state.teacher_data["teacher_id"]
    dark = is_dark_theme()
    hero_bg = "linear-gradient(135deg,#12384a,#132442)" if dark else "linear-gradient(135deg,#ecfeff,#eef2ff)"
    hero_title = "#f8fafc" if dark else "#12304a"
    hero_copy = "#b8c8dc" if dark else "#52647a"
    accent = "#5eead4" if dark else "#0f766e"

    st.html(
        f'<div style="background:{hero_bg};border:1px solid {accent}45;border-radius:20px;padding:24px 26px;margin:2px 0 20px;box-shadow:0 12px 28px rgba(15,23,42,.12);">'
        f'<div style="display:inline-flex;align-items:center;gap:7px;color:{accent};font-size:.76rem;font-weight:800;letter-spacing:.1em;text-transform:uppercase;margin-bottom:7px;">'
        '● AI Workspace</div>'
        f'<h2 style="margin:0 0 6px;color:{hero_title}!important;font-size:1.7rem!important;">Automated Classroom Attendance</h2>'
        f'<p style="margin:0;color:{hero_copy};max-width:670px;">Select your course, add classroom photos, and run neural feature extraction to mark attendance.</p>'
        '</div>'
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
                    f"🎉 **Attendance Saved Successfully!** Session logged for **{last_rec.get('subject_name', 'Subject')}** "
                    f"({last_rec.get('present', 0)}/{last_rec.get('total', 0)} Present) at {last_rec.get('time', '')}."
                )
            with b_col2:
                if st.button("📊 View Records", type="secondary", width="stretch", key="btn_view_saved_rec"):
                    st.session_state.current_teacher_tab = "attendance_records"
                    st.session_state.last_saved_attendance = None
                    st.rerun()

    subjects = get_teacher_subjects(teacher_id)
    if not subjects:
        st.warning("⚠️ No subjects created yet. Go to 'Manage Subjects' to create your first course.")
        return

    sub_opts = {f"{s['name']} ({s['subject_code']})" : s["subject_id"] for s in subjects}
    with st.container(border=True):
        st.caption("01  •  CLASS SELECTION")
        col1, col2 = st.columns([3, 1], vertical_alignment="bottom")
        with col1:
            selected_label = st.selectbox("Choose a Subject", options=list(sub_opts.keys()), key="select_attendance_sub")
        with col2:
            if st.button("Add Photos", type="primary", width="stretch", icon=":material/add_a_photo:", key="btn_open_add_photo"):
                add_photos_dialog()

    selected_sub_id = sub_opts[selected_label]

    if st.session_state.attendance_images:
        with st.container(border=True):
            st.caption(f"02  •  WORKSPACE  •  {len(st.session_state.attendance_images)} PHOTOS LOADED")
            st.subheader("Classroom Photos")
            gallery_cols = st.columns(4)
            for idx, img in enumerate(st.session_state.attendance_images):
                with gallery_cols[idx % 4]:
                    st.image(img, width="stretch", caption=f"Photo {idx + 1}")
                    if st.button("🗑️ Remove", key=f"btn_remove_ws_img_{idx}", width="stretch", type="tertiary"):
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
                f'<div style="text-align:center;padding:24px 18px;background:{empty_bg};border:1px dashed {border_c};border-radius:14px;">'
                '<div style="font-size:2.2rem;margin-bottom:6px;">📸</div>'
                f'<p style="font-family:Outfit,sans-serif;font-size:1.02rem;font-weight:700;color:{text_title};margin:0 0 4px;">No classroom photos staged yet</p>'
                f'<p style="font-family:Outfit,sans-serif;font-size:0.86rem;color:{text_sub};margin:0;">'
                'Click the <b>"Add Photos"</b> button above to upload group pictures or capture snapshots with your camera.'
                '</p></div>'
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
            if st.button("Clear Photos", type="secondary", disabled=not has_photos, icon=":material/delete:", width="stretch", key="btn_clear_photos"):
                st.session_state.attendance_images = []
                st.rerun()
        with c2:
            if st.button("Analyze Faces", type="primary", disabled=not has_photos, icon=":material/face:", width="stretch", key="btn_analyze_faces"):
                with st.spinner("Executing facial feature extraction..."):
                    enrolled_res = (
                        supabase.table("subject_students")
                        .select("*, students(*)")
                        .eq("subject_id", selected_sub_id)
                        .execute()
                    )
                    enrolled_stud = enrolled_res.data or []

                    if not enrolled_stud:
                        st.warning("⚠️ No students enrolled in this course!")
                    else:
                        enrolled_sids = [
                            int(node["students"]["student_id"]) 
                            for node in enrolled_stud 
                            if node.get("students") and node["students"].get("student_id")
                        ]
                        all_detected_ids = predict_attendance_batch(
                            st.session_state.attendance_images,
                            candidate_ids=enrolled_sids,
                            distance_threshold=0.38
                        )

                        res_rows, attend_logs = [], []
                        current_timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                        for node in enrolled_stud:
                            stud = node.get("students")
                            if not stud:
                                continue
                            sid = stud["student_id"]
                            sources = all_detected_ids.get(int(sid), [])
                            is_present = len(sources) > 0

                            res_rows.append({
                                "Name": stud["name"],
                                "ID": sid,
                                "Source": ", ".join(sources) if is_present else "-",
                                "Status": "✅ Present" if is_present else "❌ Absent"
                            })
                            attend_logs.append({
                                "student_id": sid,
                                "subject_id": selected_sub_id,
                                "timestamp": current_timestamp,
                                "is_present": is_present
                            })
                        attend_result(pd.DataFrame(res_rows), attend_logs, subject_name=selected_label)
        with c3:
            if st.button("Voice Attendance", type="tertiary", width="stretch", icon=":material/mic:", key="btn_voice_modal"):
                voice_attendance(selected_sub_id)

def manage_subjects():
    teacher_id = st.session_state.teacher_data["teacher_id"]
    col1, col2 = st.columns(2)
    with col1:
        st.header("Manage Subjects", width="stretch")
    with col2:
        if st.button("Create New Subject", type="primary", icon=":material/add_circle:", width="stretch", key="btn_create_sub"):
            create_subject_dialog(teacher_id)

    subjects = get_teacher_subjects(teacher_id)
    if not subjects:
        st.info("No subjects created yet. Click 'Create New Subject' to begin!")
        return

    for i, sub in enumerate(subjects):
        stats = [
            ("👥", "Students", sub.get("total_students", 0)),
            ("📅", "Classes",  sub.get("total_classes", 0))
        ]

        def make_footer(bound_sub=sub, idx=i):
            def footer():
                col_share, col_delete = st.columns(2)
                with col_share:
                    if st.button(
                        "Share Code",
                        key=f"share_{bound_sub['subject_code']}_{idx}",
                        icon=":material/share:",
                        width="stretch"
                    ):
                        share_subject(bound_sub["name"], bound_sub["subject_code"])
                with col_delete:
                    if st.button(
                        "Delete Subject",
                        key=f"delete_{bound_sub['subject_id']}_{idx}",
                        icon=":material/delete_forever:",
                        type="secondary",
                        width="stretch"
                    ):
                        confirm_delete_subject(
                            bound_sub["subject_id"],
                            bound_sub["name"],
                            bound_sub["subject_code"]
                        )
                st.space()
            return footer

        subject_card(
            name=sub["name"],
            code=sub["subject_code"],
            section=sub["section"],
            stats=stats,
            footer_callback=make_footer()
        )

def attendance_records():
    teacher_id = st.session_state.teacher_data["teacher_id"]
    records = get_attendance_for_teacher(teacher_id)
    dark = is_dark_theme()

    hdr_color = "#818cf8" if dark else "#5144d3"
    sub_color = "#94a3b8"

    st.html(
        '<div style="margin-bottom:6px;">'
        f'<h1 style="font-family:\'Climate Crisis\',sans-serif;font-size:2.4rem;letter-spacing:2px;'
        f'color:{hdr_color};-webkit-text-fill-color:{hdr_color};margin:0 0 4px 0;">Attendance Records</h1>'
        f'<p style="font-family:Outfit,sans-serif;color:{sub_color};font-size:0.92rem;margin:0;">'
        'Session breakdown and logs across all enrolled classes</p>'
        '</div>'
    )

    if not records:
        empty_bg = "#1e293b" if dark else "white"
        st.html(
            f'<div style="text-align:center;padding:50px 20px;background:{empty_bg};border-radius:20px;margin-top:20px;">'
            '<div style="font-size:3rem;margin-bottom:12px;">📭</div>'
            f'<p style="font-family:Outfit,sans-serif;font-size:1.1rem;color:{sub_color};font-weight:600;">'
            'No attendance records found.<br/>'
            '<span style="font-weight:400;font-size:0.92rem;">Take attendance in a class to generate session history.</span>'
            '</p></div>'
        )
        return

    data = []
    for r in records:
        ts = r.get("timestamp")
        sub_info = r.get("subjects") or {}
        data.append({
            "raw_timestamp": ts,
            "ts_group": ts.split(".")[0] if ts else None,
            "Time": datetime.fromisoformat(ts).strftime("%Y-%m-%d %I:%M %p") if ts else "N/A",
            "Subject": sub_info.get("name", "Unknown"),
            "Subject Code": sub_info.get("subject_code", "N/A"),
            "subject_id": r.get("subject_id"),
            "is_present": bool(r.get("is_present", False))
        })

    df = pd.DataFrame(data)
    summary = (
        df.groupby(["raw_timestamp", "ts_group", "Time", "Subject", "Subject Code", "subject_id"])
        .agg(
            Present_Count=("is_present", "sum"),
            Total_Count=("is_present", "count")
        )
        .reset_index()
        .sort_values("raw_timestamp", ascending=False)
    )

    total_sessions = len(summary)
    total_students = int(summary["Total_Count"].sum())
    total_present = int(summary["Present_Count"].sum())
    avg_pct = int(total_present / total_students * 100) if total_students else 0

    tiles_config = (
        [
            (total_sessions, "Sessions", "#818cf8", "rgba(129, 140, 248, 0.15)", "rgba(129, 140, 248, 0.35)"),
            (total_students, "Total Logs", "#c084fc", "rgba(192, 132, 252, 0.15)", "rgba(192, 132, 252, 0.35)"),
            (total_present, "Present Entries", "#4ade80", "rgba(74, 222, 128, 0.15)", "rgba(74, 222, 128, 0.35)"),
            (f"{avg_pct}%", "Avg Attendance", "#fbbf24", "rgba(251, 191, 36, 0.15)", "rgba(251, 191, 36, 0.35)"),
        ]
        if dark else
        [
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
            f'<div style="flex:1;min-width:120px;background:{bg};border:1px solid {border};border-radius:16px;padding:16px 20px;text-align:center;">'
            f'<div style="font-size:1.9rem;font-weight:800;color:{col};font-family:Outfit,sans-serif;">{val}</div>'
            f'<div style="font-size:0.78rem;color:{lbl_c};font-family:Outfit,sans-serif;margin-top:3px;">{lbl}</div>'
            '</div>'
        )

    st.html(f'<div style="display:flex;gap:14px;margin:18px 0 22px;flex-wrap:wrap;">{tiles_html}</div>')

    for _, row in summary.iterrows():
        present = int(row["Present_Count"])
        total = int(row["Total_Count"])
        absent = total - present
        pct = int(present / total * 100) if total else 0

        bar_color = "#4ade80" if (pct >= 70 and dark) else "#fbbf24" if (pct >= 40 and dark) else "#f87171" if dark else ("#22c55e" if pct >= 70 else "#f59e0b" if pct >= 40 else "#ef4444")
        bar_bg = "rgba(34, 197, 94, 0.15)" if (pct >= 70 and dark) else "rgba(245, 158, 11, 0.15)" if (pct >= 40 and dark) else "rgba(239, 68, 68, 0.15)" if dark else ("#dcfce7" if pct >= 70 else "#fef9c3" if pct >= 40 else "#fee2e2")
        bar_border = "rgba(34, 197, 94, 0.35)" if (pct >= 70 and dark) else "rgba(245, 158, 11, 0.35)" if (pct >= 40 and dark) else "rgba(239, 68, 68, 0.35)" if dark else ("#86efac" if pct >= 70 else "#fde68a" if pct >= 40 else "#fca5a5")

        card_bg = "#1e293b" if dark else "white"
        card_title_col = "#f8fafc" if dark else "#1e293b"
        code_badge_bg = "linear-gradient(135deg,#312e81,#4338ca)" if dark else "linear-gradient(135deg,#e0e7ff,#c7d2fe)"
        code_badge_col = "#a5b4fc" if dark else "#4338ca"
        track_bg = "#334155" if dark else "#f1f5f9"

        card_html = (
            f'<div style="background:{card_bg};border-radius:20px;padding:20px 24px;margin-bottom:14px;border-left:5px solid {bar_color};">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;margin-bottom:14px;">'
            f'<div><div style="font-family:Outfit,sans-serif;font-size:1.08rem;font-weight:700;color:{card_title_col};margin-bottom:3px;">{row["Subject"]}</div>'
            f'<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">'
            f'<span style="background:{code_badge_bg};color:{code_badge_col};padding:2px 12px;border-radius:20px;font-size:0.82rem;font-weight:600;">{row["Subject Code"]}</span>'
            f'<span style="font-size:0.82rem;color:#94a3b8;">🕐 {row["Time"]}</span>'
            f'</div></div>'
            f'<div style="background:{bar_bg};color:{bar_color};font-family:Outfit,sans-serif;font-size:1.5rem;font-weight:800;padding:6px 18px;border-radius:14px;border:1px solid {bar_border};text-align:center;">{pct}%</div>'
            f'</div>'
            f'<div style="background:{track_bg};border-radius:99px;height:8px;overflow:hidden;margin-bottom:10px;">'
            f'<div style="width:{pct}%;height:100%;background:linear-gradient(90deg,{bar_color}88,{bar_color});border-radius:99px;"></div>'
            f'</div></div>'
        )
        st.html(card_html)

        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button(f"✅ {present} Present", key=f"pres_{row['subject_id']}_{row['ts_group']}"):
                session_detail_dialog(int(row["subject_id"]), row["raw_timestamp"], str(row["Subject"]), "present")
        with b2:
            if st.button(f"❌ {absent} Absent", key=f"abs_{row['subject_id']}_{row['ts_group']}", type="secondary"):
                session_detail_dialog(int(row["subject_id"]), row["raw_timestamp"], str(row["Subject"]), "absent")
        with b3:
            st.html(
                f'<div style="text-align:center;padding:8px 12px;border-radius:20px;font-size:0.82rem;font-weight:600;font-family:Outfit,sans-serif;background:{card_bg};border:1px solid #334155;">👥 {total} Total</div>'
            )

def register_teacher_action(username: str, name: str, pwd: str, pwd_confirm: str) -> tuple[bool, str]:
    if not username.strip() or not name.strip() or not pwd:
        return False, "All fields are required!"
    if len(pwd) < 6:
        return False, "Password must be at least 6 characters long."
    if pwd != pwd_confirm:
        return False, "Passwords do not match."
    if check_teacher_exists(username):
        return False, "Username is already taken."

    try:
        create_teacher(username, pwd, name)
        return True, "Account created successfully! Please login."
    except Exception as exc:
        return False, f"Registration error: {exc}"

def teacher_scrn_login():
    c1, c2 = st.columns(2, vertical_alignment="center", gap="xxlarge")
    with c1:
        header_dashboard()
    with c2:
        b1, b2 = st.columns(2, vertical_alignment="center")
        with b1:
            if st.button("Go to Home", type="secondary", key="backbtn", width="stretch"):
                st.session_state["login_type"] = None
                st.session_state["teacher_login_type"] = "login"
                st.rerun()
        with b2:
            theme_toggle("teacher_login")

    st.header("Teacher Portal Sign In", text_alignment="center")
    st.space()

    username = st.text_input("Username", placeholder="@username", key="teacher_login_user")
    password = st.text_input("Password", type="password", placeholder="Enter Password", key="teacher_login_pwd")

    st.divider()
    btn1, btn2 = st.columns(2)

    with btn1:
        if st.button("Login", icon=":material/passkey:", width="stretch", key="btn_teacher_login"):
            if username and password:
                teacher = teacher_login(username, password)
                if teacher:
                    st.session_state.user_role = "teacher"
                    st.session_state.teacher_data = teacher
                    st.session_state.is_logged_in = True
                    st.toast(f"Welcome back, {teacher['name']}! 👋")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Invalid Username or Password")
            else:
                st.warning("Please enter username and password")

    with btn2:
        if st.button("Register New Account", type="primary", icon=":material/person_add:", width="stretch", key="btn_to_teacher_reg"):
            st.session_state.teacher_login_type = "register"
            st.rerun()

    footer_dashboard()

def teacher_scrn_register():
    c1, c2 = st.columns(2, vertical_alignment="center", gap="xxlarge")
    with c1:
        header_dashboard()
    with c2:
        b1, b2 = st.columns(2, vertical_alignment="center")
        with b1:
            if st.button("Go to Home", type="secondary", key="backbtn", width="stretch"):
                st.session_state["login_type"] = None
                st.session_state["teacher_login_type"] = "login"
                st.rerun()
        with b2:
            theme_toggle("teacher_reg")

    st.header("Register Teacher Profile")
    st.space()

    username = st.text_input("Username", placeholder="@username", key="reg_teach_user")
    name = st.text_input("Full Name", placeholder="e.g. Dr. Jane Smith", key="reg_teach_name")
    password = st.text_input("Password", type="password", placeholder="Minimum 6 characters", key="reg_teach_pwd")
    pass_conf = st.text_input("Confirm Password", type="password", placeholder="Re-enter password", key="reg_teach_pwd_confirm")

    st.divider()
    btn1, btn2 = st.columns(2)

    with btn1:
        if st.button("Complete Registration", icon=":material/how_to_reg:", width="stretch", key="btn_teacher_reg_submit"):
            succ, msg = register_teacher_action(username, name, password, pass_conf)
            if succ:
                st.success(msg)
                time.sleep(1.5)
                st.session_state.teacher_login_type = "login"
                st.rerun()
            else:
                st.error(msg)

    with btn2:
        if st.button("Already have an account? Sign In", type="primary", icon=":material/login:", width="stretch", key="btn_back_to_teacher_login"):
            st.session_state.teacher_login_type = "login"
            st.rerun()

    footer_dashboard()
