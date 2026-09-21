import streamlit as st
from src.database.db import create_attendance
from src.components.dialog_utils import dialog_banner
from src.ui.base_layout import is_dark_theme

def show_attendance(df, logs):
    present = sum(1 for l in logs if l.get('is_present'))
    total   = len(logs)
    pct     = int(present / total * 100) if total else 0
    dark    = is_dark_theme()

    p_bg = "rgba(34, 197, 94, 0.15)" if dark else "linear-gradient(135deg, #43e97b22, #38f9d722)"
    p_border = "rgba(34, 197, 94, 0.35)" if dark else "#43e97b55"
    p_col = "#4ade80" if dark else "#22c55e"

    a_bg = "rgba(239, 68, 68, 0.15)" if dark else "linear-gradient(135deg, #f5576c22, #f093fb22)"
    a_border = "rgba(239, 68, 68, 0.35)" if dark else "#f5576c55"
    a_col = "#f87171" if dark else "#ef4444"

    pct_bg = "rgba(129, 140, 248, 0.15)" if dark else "linear-gradient(135deg, #667eea22, #764ba222)"
    pct_border = "rgba(129, 140, 248, 0.35)" if dark else "#667eea55"
    pct_col = "#818cf8" if dark else "#667eea"

    lbl_col = "#94a3b8"

    # ── Stats strip ────────────────────────────────────────────────
    st.markdown(f"""
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
    """, unsafe_allow_html=True)

    st.markdown(f"""
        <p style="
            font-family: Outfit, sans-serif;
            font-size: 0.88rem;
            color: {lbl_col};
            margin-bottom: 6px;
        ">Review before confirming — this cannot be undone.</p>
    """, unsafe_allow_html=True)

    st.dataframe(df, hide_index=True, width='stretch')

    col1, col2 = st.columns(2)
    with col1:
        if st.button('🗑️  Discard', width='stretch'):
            st.session_state.voice_attendance_results = []
            st.session_state.attendance_images = []
            st.rerun()
    with col2:
        if st.button("✅  Save and Confirm", type='primary', width='stretch'):
            try:
                create_attendance(logs)
                st.toast("✅ Attendance saved!", icon="🎉")
                st.session_state.attendance_images = []
                st.session_state.voice_attendance_results = None
                st.rerun()
            except Exception:
                st.error("❌ Sync failed — please try again.")


@st.dialog("Attendance Report", width="large")
def attend_result(df, logs):
    dialog_banner("Attendance Report", subtitle="Review before saving", theme="teal")
    show_attendance(df, logs)
