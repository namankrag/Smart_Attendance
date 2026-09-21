import streamlit as st
from pathlib import Path

from src.components.header import header_home
from src.components.footer import footer_home
from src.ui.base_layout import style_base_layout, style_bg_home, is_dark_theme

BASE_DIR = Path(__file__).resolve().parents[2]

student_img = BASE_DIR / "img" / "student.png"
teacher_img = BASE_DIR / "img" / "teacher.png"


def home_screen():

    style_bg_home()
    style_base_layout()
    dark = is_dark_theme()

    # ── Full-width header above the cards ───────────────────────
    header_home()

    stud_title_col = "#5eead4" if dark else "#0f766e"
    teach_title_col = "#a5b4fc" if dark else "#4f46e5"
    student_card = "linear-gradient(145deg, rgba(15,118,110,.24), rgba(15,23,42,.20))" if dark else "linear-gradient(145deg, #ffffff, #f0fdfa)"
    teacher_card = "linear-gradient(145deg, rgba(79,70,229,.25), rgba(15,23,42,.20))" if dark else "linear-gradient(145deg, #ffffff, #eef2ff)"
    card_text = "#b8c8dc" if dark else "#52647a"

    # ── Portal cards ────────────────────────────────────────────
    st.html("""
        <div style="text-align:center;max-width:610px;margin:-18px auto 30px;">
          <p style="font-size:1.05rem;line-height:1.65;margin:0;">A calmer, faster way to run attendance—choose your workspace to get started.</p>
        </div>
    """)
    col1, col2 = st.columns(2, gap="large")

    with col1:
        with st.container(border=True):
            st.html(f"""<div style="background:{student_card};border:1px solid {stud_title_col}40;border-radius:16px;padding:24px;margin-bottom:18px;">
                <div style="display:inline-flex;padding:5px 11px;border-radius:99px;background:{stud_title_col}18;color:{stud_title_col};font-size:.78rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;">Student workspace</div>
                <h2 style="font-size:1.8rem!important;margin:17px 0 6px;color:{stud_title_col}!important;">I'm a Student</h2>
                <p style="margin:0;color:{card_text};"></p></div>""")
            image_col, action_col = st.columns([1, 1.35], vertical_alignment="center")
            with image_col:
                st.image(student_img, width=130)
            with action_col:
                st.caption("PERSONAL ATTENDANCE HUB")
                st.markdown("Use Face ID to sign in securely and view your subjects in one place.")
                if st.button('Open Student Portal', type='primary', icon=":material/arrow_outward:", icon_position="right", width="stretch"):
                    st.session_state["login_type"] = "student"
                    st.rerun()

    with col2:
        with st.container(border=True):
            st.html(f"""<div style="background:{teacher_card};border:1px solid {teach_title_col}40;border-radius:16px;padding:24px;margin-bottom:18px;">
                <div style="display:inline-flex;padding:5px 11px;border-radius:99px;background:{teach_title_col}18;color:{teach_title_col};font-size:.78rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;">Teacher workspace</div>
                <h2 style="font-size:1.8rem!important;margin:17px 0 6px;color:{teach_title_col}!important;">I'm a Teacher</h2>
                <p style="margin:0;color:{card_text};"></p></div>""")
            image_col, action_col = st.columns([1, 1.35], vertical_alignment="center")
            with image_col:
                st.image(teacher_img, width=130)
            with action_col:
                st.caption("CLASSROOM COMMAND CENTER")
                st.markdown("Create subjects, capture attendance, and review sessions with less effort.")
                if st.button('Open Teacher Portal', type='primary', icon=':material/arrow_outward:', icon_position="right", width="stretch"):
                    st.session_state['login_type'] = 'teacher'
                    st.rerun()

    footer_home()
