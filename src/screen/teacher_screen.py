import streamlit as st
import time
import numpy as np
from datetime import datetime
import pandas as pd

from src.ui.base_layout import style_bg_dashboard, style_base_layout, is_dark_theme
from src.components.header import header_dashboard, theme_toggle
from src.components.footer import footer_dashboard
from src.database.db import check_teacher_exists, create_teacher, teacher_login, get_teacher_subjects, get_attendance_for_teacher
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
    elif 'teacher_login_type' not in st.session_state or st.session_state.teacher_login_type == 'login':
        teacher_scrn_login()
    elif st.session_state.teacher_login_type == 'register':
        teacher_scrn_register()


def teacher_dashboard():
    data = st.session_state.teacher_data
    c1, c2 = st.columns(2, vertical_alignment='center', gap='xxlarge')
    with c1:
        header_dashboard()
    with c2:
        st.subheader(f"""Welcome, {data['name']} """)
        
        b1, b2 = st.columns(2, vertical_alignment='center')
        with b1:
            if st.button("Logout", type='secondary', key='backbtn', width='stretch'):
                st.session_state['is_logged_in'] = False
                del st.session_state.teacher_data
                st.rerun()
        with b2:
            theme_toggle('teacher_dash')
    st.space()

    if "current_teacher_tab" not in st.session_state:
        st.session_state.current_teacher_tab = 'take_attendance'

    tab1, tab2, tab3 = st.columns(3)

    with tab1:
        type1 = 'primary' if st.session_state.current_teacher_tab == "take_attendance" else 'tertiary'
        if st.button("Take Attendance", type = type1, width = 'stretch', icon = ":material/ar_on_you:"):
            st.session_state.current_teacher_tab = "take_attendance"
            st.rerun()

    with tab2:
        type2 = 'primary' if st.session_state.current_teacher_tab == "manage_subjects" else 'tertiary'
        if st.button("Manage Subjects", type = type2, width = 'stretch', icon = ":material/book_ribbon:"):
            st.session_state.current_teacher_tab = "manage_subjects"
            st.rerun()

    with tab3:
        type3 = 'primary' if st.session_state.current_teacher_tab == "attendance_records" else 'tertiary'
        if st.button("Attendance Records", type = type3, width = 'stretch', icon = ":material/cards_stack:"):
            st.session_state.current_teacher_tab = "attendance_records"
            st.rerun()

    st.divider()
    if st.session_state.current_teacher_tab == 'take_attendance':
        take_attendance()
    if st.session_state.current_teacher_tab == 'manage_subjects':
        manage_subjects()
    if st.session_state.current_teacher_tab == 'attendance_records':
        attendance_records()

    footer_dashboard()


def take_attendance():
    teach_id = st.session_state.teacher_data['teacher_id']
    st.header("Take AI Attendance")
    if 'attendance_images' not in st.session_state:
        st.session_state.attendance_images = []

    subjects = get_teacher_subjects(teach_id)
    if not subjects:
        st.warning("You have not created any subjects! Please create one to begin!")
        return

    sub_opt = {f"{s['name']} - {s['subject_code']}" : s['subject_id'] for s in subjects}
    col1, col2 = st.columns([3, 1], vertical_alignment = 'bottom')
    with col1:
        selected_sub_label = st.selectbox('Select Subjects', options = list(sub_opt.keys()))
    with col2:
        if st.button('Add Photos', type='primary', width='stretch', icon=":material/photo_prints:"):
            add_photos_dialog()

    selected_sub_id = sub_opt[selected_sub_label]
    st.divider()
    if st.session_state.attendance_images:
        st.header('Added Photos')
        gallery_cols = st.columns(4)

        for idx, img in enumerate(st.session_state.attendance_images):
            with gallery_cols[idx % 4]:
                st.image(img, width='stretch', caption=f"Photo {idx+1}")
    has_photos = bool(st.session_state.attendance_images)
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Clear all photos", type = 'primary', disabled = not has_photos, icon = ":material/delete:"):
            st.session_state.attendance_images = []
            st.rerun()
    with c2:
        if st.button("Run face analysis", type = 'secondary', disabled= not has_photos, icon = ":material/analytics:"):
            with st.spinner("Deep Scanning classroom photos in parallel..."):
                all_detected_ids = predict_attendance_batch(st.session_state.attendance_images)

                enrolled_res = supabase.table('subject_students').select("*, students(*)").eq('subject_id', selected_sub_id).execute()
                enrolled_stud = enrolled_res.data

                if not enrolled_stud:
                    st.warning("No student enrolled in this course!")
                else:
                    res, attend_logs = [], []
                    crnt_timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                    for node in enrolled_stud:
                        stud = node['students']
                        sources = all_detected_ids.get(int(stud['student_id']), [])
                        is_present = len(sources) > 0
                        res.append({
                            "Name" : stud['name'],
                            "ID" : stud['student_id'],
                            "Source" : ", ".join(sources) if is_present else "-",
                            "Status" : "✅ Present" if is_present else "❌ Absent"
                        })
                        attend_logs.append({
                            'student_id' : stud['student_id'],
                            'subject_id' : selected_sub_id,
                            'timestamp' : crnt_timestamp,
                            'is_present' : bool(is_present)
                        })

                attend_result(pd.DataFrame(res), attend_logs)
    with c3:
        if st.button("Use Voice Attendance", type='primary', width='stretch', icon=":material/mic:"):
            voice_attendance(selected_sub_id)


def manage_subjects():
    teach_id = st.session_state.teacher_data['teacher_id']
    col1, col2 = st.columns(2)
    with col1:
        st.header("Manage Subjects", width='stretch')
    with col2:
        if st.button("Create New Subject", width='stretch'):
            create_subject_dialog(teach_id)

    subjects = get_teacher_subjects(teach_id)
    if not subjects:
        st.info("No subjects yet. Create one to get started!")
        return

    for i, sub in enumerate(subjects):
        stats = [
            ("🫂", "Students", sub['total_students']),
            ("🕰️", "Classes",  sub['total_classes'])
        ]

        def make_footer(bound_sub=sub, idx=i):
            def footer():
                col_share, col_delete = st.columns(2)
                with col_share:
                    if st.button(
                        "Share Code",
                        key=f"share_{bound_sub['subject_code']}_{idx}",
                        icon=":material/share:",
                        width='stretch'
                    ):
                        share_subject(bound_sub['name'], bound_sub['subject_code'])
                with col_delete:
                    if st.button(
                        "Delete Subject",
                        key=f"delete_{bound_sub['subject_id']}_{idx}",
                        icon=":material/delete_forever:",
                        type='secondary',
                        width='stretch'
                    ):
                        confirm_delete_subject(
                            bound_sub['subject_id'],
                            bound_sub['name'],
                            bound_sub['subject_code']
                        )
                st.space()
            return footer

        subject_card(
            name=sub['name'],
            code=sub['subject_code'],
            section=sub['section'],
            stats=stats,
            footer_callback=make_footer()
        )


def attendance_records():
    teach_id = st.session_state.teacher_data['teacher_id']
    records  = get_attendance_for_teacher(teach_id)
    dark     = is_dark_theme()

    hdr_color = "#818cf8" if dark else "#5144d3"
    sub_color = "#94a3b8"

    # ── Header ────────────────────────────────────────────────────
    st.html(
        '<div style="margin-bottom:6px;">'
        f'<h1 style="font-family:\'Climate Crisis\',sans-serif;font-size:2.4rem;letter-spacing:2px;'
        f'color:{hdr_color};-webkit-text-fill-color:{hdr_color};margin:0 0 4px 0;">Attendance Records</h1>'
        f'<p style="font-family:Outfit,sans-serif;color:{sub_color};font-size:0.92rem;margin:0;">'
        'Session-by-session summary of all your classes</p>'
        '</div>'
    )

    if not records:
        empty_bg = "#1e293b" if dark else "white"
        empty_border = "border:1px solid #334155;" if dark else ""
        shadow = "box-shadow:0 4px 20px rgba(0,0,0,0.4);" if dark else "box-shadow:0 4px 20px rgba(102,126,234,0.1);"

        st.html(
            f'<div style="text-align:center;padding:60px 20px;background:{empty_bg};{empty_border}border-radius:20px;'
            f'margin-top:20px;{shadow}">'
            '<div style="font-size:3rem;margin-bottom:12px;">📭</div>'
            f'<p style="font-family:Outfit,sans-serif;font-size:1.1rem;color:{sub_color};font-weight:600;">'
            'No attendance records yet.<br/>'
            '<span style="font-weight:400;font-size:0.92rem;">Take attendance to see records here.</span>'
            '</p></div>'
        )
        return

    # ── Aggregate ─────────────────────────────────────────────────
    data = []
    for r in records:
        ts = r.get('timestamp')
        data.append({
            "ts_group"     : ts.split(".")[0] if ts else None,
            "Time"         : datetime.fromisoformat(ts).strftime("%Y-%m-%d %I:%M %p") if ts else "N/A",
            "Subject"      : r['subjects']['name'],
            "Subject Code" : r['subjects']['subject_code'],
            "subject_id"   : r.get('subject_id'),
            "is_present"   : bool(r.get('is_present', False))
        })

    df = pd.DataFrame(data)
    summary = (
        df.groupby(['ts_group', 'Time', 'Subject', 'Subject Code', 'subject_id'])
        .agg(
            Present_Count=('is_present', 'sum'),
            Total_Count  =('is_present', 'count')
        )
        .reset_index()
        .sort_values('ts_group', ascending=False)
    )

    # ── Top summary strip ─────────────────────────────────────────
    total_sessions  = len(summary)
    total_students  = int(summary['Total_Count'].sum())
    total_present   = int(summary['Present_Count'].sum())
    avg_pct         = int(total_present / total_students * 100) if total_students else 0

    tiles_config = (
        [
            (total_sessions,    "Sessions",        "#818cf8", "rgba(129, 140, 248, 0.15)", "rgba(129, 140, 248, 0.35)"),
            (total_students,    "Total Records",   "#c084fc", "rgba(192, 132, 252, 0.15)", "rgba(192, 132, 252, 0.35)"),
            (total_present,     "Present Entries", "#4ade80", "rgba(74, 222, 128, 0.15)",  "rgba(74, 222, 128, 0.35)"),
            (f"{avg_pct}%",     "Avg Attendance",  "#fbbf24", "rgba(251, 191, 36, 0.15)",  "rgba(251, 191, 36, 0.35)"),
        ]
        if dark else
        [
            (total_sessions,    "Sessions",        "#667eea", "#ede9fe", "#c4b5fd"),
            (total_students,    "Total Records",   "#a855f7", "#f5f3ff", "#ddd6fe"),
            (total_present,     "Present Entries", "#22c55e", "#f0fdf4", "#86efac"),
            (f"{avg_pct}%",     "Avg Attendance",  "#f59e0b", "#fffbeb", "#fde68a"),
        ]
    )

    tiles_html = ""
    for val, lbl, col, bg, border in tiles_config:
        lbl_c = "#94a3b8" if dark else "#64748b"
        tiles_html += (
            '<div style="flex:1;min-width:120px;background:' + bg + ';'
            'border:1px solid ' + border + ';border-radius:16px;padding:16px 20px;text-align:center;">'
            '<div style="font-size:1.9rem;font-weight:800;color:' + col + ';font-family:Outfit,sans-serif;">' + str(val) + '</div>'
            '<div style="font-size:0.78rem;color:' + lbl_c + ';font-family:Outfit,sans-serif;margin-top:3px;">' + lbl + '</div>'
            '</div>'
        )

    st.html('<div style="display:flex;gap:14px;margin:18px 0 22px;flex-wrap:wrap;">' + tiles_html + '</div>')

    # ── Cards ─────────────────────────────────────────────────────
    for _, row in summary.iterrows():
        present   = int(row['Present_Count'])
        total     = int(row['Total_Count'])
        absent    = total - present
        pct       = int(present / total * 100) if total else 0

        bar_color  = "#4ade80" if (pct >= 70 and dark) else "#fbbf24" if (pct >= 40 and dark) else "#f87171" if dark else ("#22c55e" if pct >= 70 else "#f59e0b" if pct >= 40 else "#ef4444")
        bar_bg     = "rgba(34, 197, 94, 0.15)" if (pct >= 70 and dark) else "rgba(245, 158, 11, 0.15)" if (pct >= 40 and dark) else "rgba(239, 68, 68, 0.15)" if dark else ("#dcfce7" if pct >= 70 else "#fef9c3" if pct >= 40 else "#fee2e2")
        bar_border = "rgba(34, 197, 94, 0.35)" if (pct >= 70 and dark) else "rgba(245, 158, 11, 0.35)" if (pct >= 40 and dark) else "rgba(239, 68, 68, 0.35)" if dark else ("#86efac" if pct >= 70 else "#fde68a" if pct >= 40 else "#fca5a5")

        card_bg = "#1e293b" if dark else "white"
        card_border_style = "border:1px solid rgba(255,255,255,0.08);" if dark else ""
        card_title_col = "#f8fafc" if dark else "#1e293b"
        code_badge_bg = "linear-gradient(135deg,#312e81,#4338ca)" if dark else "linear-gradient(135deg,#e0e7ff,#c7d2fe)"
        code_badge_col = "#a5b4fc" if dark else "#4338ca"
        track_bg = "#334155" if dark else "#f1f5f9"
        shadow_def = "box-shadow:0 4px 20px rgba(0,0,0,0.4);" if dark else "box-shadow:0 4px 20px rgba(102,126,234,0.1);"
        shadow_hov = "box-shadow:0 8px 30px rgba(129,140,248,0.25);" if dark else "box-shadow:0 8px 30px rgba(102,126,234,0.2);"

        pres_pill_bg = "rgba(34, 197, 94, 0.15)" if dark else "#f0fdf4"
        pres_pill_border = "rgba(34, 197, 94, 0.3)" if dark else "#bbf7d0"
        pres_pill_col = "#4ade80" if dark else "#16a34a"

        abs_pill_bg = "rgba(239, 68, 68, 0.15)" if dark else "#fef2f2"
        abs_pill_border = "rgba(239, 68, 68, 0.3)" if dark else "#fecaca"
        abs_pill_col = "#f87171" if dark else "#dc2626"

        tot_pill_bg = "#334155" if dark else "#f8fafc"
        tot_pill_border = "#475569" if dark else "#e2e8f0"
        tot_pill_col = "#cbd5e1" if dark else "#475569"

        card = (
            '<div style="background:' + card_bg + ';border-radius:20px;padding:20px 24px;margin-bottom:14px;'
            + card_border_style + shadow_def + 'border-left:5px solid ' + bar_color + ';transition:all 0.2s ease;">'

            # Row 1
            '<div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;margin-bottom:14px;">'
            '<div>'
            '<div style="font-family:Outfit,sans-serif;font-size:1.08rem;font-weight:700;color:' + card_title_col + ';margin-bottom:3px;">' + str(row['Subject']) + '</div>'
            '<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">'
            '<span style="background:' + code_badge_bg + ';color:' + code_badge_col + ';padding:2px 12px;border-radius:20px;font-size:0.82rem;font-weight:600;font-family:Outfit,sans-serif;">' + str(row['Subject Code']) + '</span>'
            '<span style="font-family:Outfit,sans-serif;font-size:0.82rem;color:#94a3b8;">🕐 ' + str(row['Time']) + '</span>'
            '</div>'
            '</div>'
            '<div style="background:' + bar_bg + ';color:' + bar_color + ';font-family:Outfit,sans-serif;font-size:1.5rem;font-weight:800;'
            'padding:6px 18px;border-radius:14px;border:1px solid ' + bar_border + ';min-width:70px;text-align:center;">' + str(pct) + '%</div>'
            '</div>'

            # Row 2 – progress bar
            '<div style="background:' + track_bg + ';border-radius:99px;height:8px;overflow:hidden;margin-bottom:10px;">'
            '<div style="width:' + str(pct) + '%;height:100%;background:linear-gradient(90deg,' + bar_color + '88,' + bar_color + ');border-radius:99px;"></div>'
            '</div>'

            '</div>'
        )
        st.html(card)

        # ── Interactive present / absent buttons (replace static pills) ──
        b1, b2, b3 = st.columns(3)
        with b1:
            if st.button(
                f"✅ {present} Present",
                key=f"pres_{row['subject_id']}_{row['ts_group']}",
            ):
                session_detail_dialog(
                    int(row['subject_id']),
                    row['ts_group'],
                    str(row['Subject']),
                    'present',
                )
        with b2:
            if st.button(
                f"❌ {absent} Absent",
                key=f"abs_{row['subject_id']}_{row['ts_group']}",
                type='secondary',
            ):
                session_detail_dialog(
                    int(row['subject_id']),
                    row['ts_group'],
                    str(row['Subject']),
                    'absent',
                )
        with b3:
            st.html(
                '<div style="text-align:center;padding:8px 12px;border-radius:20px;font-size:0.82rem;'
                'font-weight:600;font-family:Outfit,sans-serif;background:' + tot_pill_bg + ';color:' + tot_pill_col + ';'
                'border:1px solid ' + tot_pill_border + ';">👥 ' + str(total) + ' Total</div>'
            )


def register_teacher(username, name, pswrd, pswrd_cnfrm):
    if not username or not name or not pswrd:
        return False, "All Fields are required!"
    elif check_teacher_exists(username):
        return False, "Username already Taken"
    elif pswrd != pswrd_cnfrm:
        return False, "Password doesn't match"

    try:
        create_teacher(username, pswrd, name)
        return True, "Sucessfully Created! Login now"
    except Exception as e:
        return False, "Unexpected Error!"


def login(username, pswrd):
    if not username or not pswrd:
        return False

    teach = teacher_login(username, pswrd)

    if teach:
        st.session_state.user_role = 'teacher'
        st.session_state.teacher_data = teach
        st.session_state.is_logged_in = True
        return True


def teacher_scrn_login():
    c1, c2 = st.columns(2, vertical_alignment="center", gap="xxlarge")
    with c1:
        header_dashboard()
    with c2:
        b1, b2 = st.columns(2, vertical_alignment='center')
        with b1:
            if st.button("Go to Home", type='secondary', key='backbtn', width='stretch'):
                st.session_state['login_type'] = None
                st.session_state['teacher_login_type'] = 'login'
                st.rerun()
        with b2:
            theme_toggle('teacher_login')

    st.header('Login using password', text_alignment='center')

    st.space()
    st.space()

    username = st.text_input("Enter Username", placeholder='@username')
    password = st.text_input("Enter Password", type='password', placeholder="Enter Password")

    st.divider()

    btn1, btn2 = st.columns(2)

    with btn1:
        if st.button("Login", icon=':material/passkey:', width='stretch'):
            if login(username, password):
                st.toast("Welcome Back", icon="👋")
                time.sleep(2)
                st.rerun()
            else:
                st.error("Invalid Username or Password")

    with btn2:
        if st.button("Register Instead", type='primary', icon=':material/passkey:', width="stretch"):
            st.session_state.teacher_login_type = 'register'
            st.rerun()

    footer_dashboard()


def teacher_scrn_register():
    c1, c2 = st.columns(2, vertical_alignment="center", gap="xxlarge")
    with c1:
        header_dashboard()
    with c2:
        b1, b2 = st.columns(2, vertical_alignment='center')
        with b1:
            if st.button("Go to Home", type='secondary', key='backbtn', width='stretch'):
                st.session_state['login_type'] = None
                st.session_state['teacher_login_type'] = 'login'
                st.rerun()
        with b2:
            theme_toggle('teacher_reg')

    st.header('Register your teacher profile')

    st.space()
    st.space()

    username = st.text_input("Enter Username", placeholder='@username')
    name = st.text_input("Enter name", placeholder='Name')
    password = st.text_input("Enter Password", type='password', placeholder="Enter Password")
    pass_conf = st.text_input("Confirm your Password", type='password', placeholder="Confirm Password")

    st.divider()

    btn1, btn2 = st.columns(2)

    with btn1:
        if st.button("Register Now", icon=':material/passkey:', width='stretch'):
            succ, msg = register_teacher(username, name, password, pass_conf)
            if succ:
                st.success(msg)
                time.sleep(2)
                st.session_state.teacher_login_type = 'login'
                st.rerun()
            else:
                st.error(msg)

    with btn2:
        if st.button("Login Instead", type='primary', icon=':material/passkey:', width="stretch"):
            st.session_state.teacher_login_type = 'login'
            st.rerun()

    footer_dashboard()
