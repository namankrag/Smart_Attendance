import streamlit as st
from src.database.db import create_attendance
from src.components.dialog_utils import dialog_banner

def show_attendance(df, logs):
    present = sum(1 for l in logs if l.get('is_present'))
    total   = len(logs)
    pct     = int(present / total * 100) if total else 0

    # ── Stats strip ────────────────────────────────────────────────
    st.markdown(f"""
        <div style="
            display: flex;
            gap: 12px;
            margin-bottom: 16px;
        ">
            <div style="
                flex: 1;
                background: linear-gradient(135deg, #43e97b22, #38f9d722);
                border: 1px solid #43e97b55;
                border-radius: 14px;
                padding: 14px;
                text-align: center;
            ">
                <div style="font-size:1.8rem; font-weight:800; color:#22c55e;">
                    {present}
                </div>
                <div style="font-size:0.8rem; color:#64748b; font-family:Outfit,sans-serif;">
                    Present
                </div>
            </div>
            <div style="
                flex: 1;
                background: linear-gradient(135deg, #f5576c22, #f093fb22);
                border: 1px solid #f5576c55;
                border-radius: 14px;
                padding: 14px;
                text-align: center;
            ">
                <div style="font-size:1.8rem; font-weight:800; color:#ef4444;">
                    {total - present}
                </div>
                <div style="font-size:0.8rem; color:#64748b; font-family:Outfit,sans-serif;">
                    Absent
                </div>
            </div>
            <div style="
                flex: 1;
                background: linear-gradient(135deg, #667eea22, #764ba222);
                border: 1px solid #667eea55;
                border-radius: 14px;
                padding: 14px;
                text-align: center;
            ">
                <div style="font-size:1.8rem; font-weight:800; color:#667eea;">
                    {pct}%
                </div>
                <div style="font-size:0.8rem; color:#64748b; font-family:Outfit,sans-serif;">
                    Attendance
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    st.markdown("""
        <p style="
            font-family: Outfit, sans-serif;
            font-size: 0.88rem;
            color: #94a3b8;
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


@st.dialog("Attendance Report")
def attend_result(df, logs):
    dialog_banner("Attendance Report", subtitle="Review before saving", theme="teal")
    show_attendance(df, logs)
