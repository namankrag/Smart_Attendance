import streamlit as st
import segno
import io
from src.components.dialog_utils import dialog_banner

@st.dialog("Share Class Link")
def share_subject(sub_name, sub_code):
    dialog_banner(
        "Share Class Link",
        subtitle=f"Invite students to join  {sub_name}",
        theme="purple"
    )

    app_dom = "smartclass-main.streamlit.app"
    join_url = f"{app_dom}/?join-code={sub_code}"

    # ── Coloured QR code ────────────────────────────────────────────
    qr = segno.make(join_url, error='h')
    out = io.BytesIO()
    qr.save(
        out,
        kind='png',
        scale=12,
        border=2,
        dark='#5144d3',        # module colour  – deep indigo
        light='#f0f0ff',       # background     – soft lavender
        data_dark='#a855f7',   # data modules   – vibrant purple
    )

    col1, col2 = st.columns([1.1, 1], gap='medium')

    with col1:
        # ── Link section ────────────────────────────────────────────
        st.markdown("""
            <p style="
                font-family: Outfit, sans-serif;
                font-weight: 700;
                font-size: 1rem;
                color: #5144d3;
                margin-bottom: 6px;
                letter-spacing: 1px;
                text-transform: uppercase;
            ">🔗 Join Link</p>
        """, unsafe_allow_html=True)
        st.code(join_url, language="text")

        st.markdown("""
            <p style="
                font-family: Outfit, sans-serif;
                font-weight: 700;
                font-size: 1rem;
                color: #a855f7;
                margin: 10px 0 6px;
                letter-spacing: 1px;
                text-transform: uppercase;
            ">🎫 Subject Code</p>
        """, unsafe_allow_html=True)
        st.code(sub_code, language="text")

        st.markdown("""
            <div style="
                background: linear-gradient(135deg, #e0e7ff 0%, #ede9fe 100%);
                border-left: 4px solid #667eea;
                border-radius: 12px;
                padding: 12px 16px;
                margin-top: 10px;
                font-family: Outfit, sans-serif;
                font-size: 0.9rem;
                color: #4338ca;
                font-weight: 500;
            ">
                💬 Share this link or code on <b>WhatsApp</b>, <b>Email</b>, or any platform!
            </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
            <p style="
                font-family: Outfit, sans-serif;
                font-weight: 700;
                font-size: 1rem;
                color: #5144d3;
                margin-bottom: 8px;
                letter-spacing: 1px;
                text-transform: uppercase;
                text-align: center;
            ">📱 Scan to Join</p>
        """, unsafe_allow_html=True)

        # Glow wrapper around the QR
        import base64
        qr_b64 = base64.b64encode(out.getvalue()).decode()
        st.markdown(f"""
            <div style="
                display: flex;
                justify-content: center;
                align-items: center;
            ">
                <div style="
                    background: linear-gradient(135deg, #667eea, #a855f7, #f093fb);
                    padding: 4px;
                    border-radius: 18px;
                    box-shadow:
                        0 0 20px rgba(102,126,234,0.5),
                        0 0 50px rgba(168,85,247,0.3);
                    animation: qrGlow 2.5s ease-in-out infinite alternate;
                ">
                    <img src="data:image/png;base64,{qr_b64}"
                         style="
                             display: block;
                             border-radius: 14px;
                             width: 200px;
                             height: 200px;
                         " />
                </div>
            </div>

            <style>
                @keyframes qrGlow {{
                    from {{ box-shadow: 0 0 20px rgba(102,126,234,0.5), 0 0 50px rgba(168,85,247,0.3); }}
                    to   {{ box-shadow: 0 0 35px rgba(168,85,247,0.8), 0 0 70px rgba(240,147,251,0.5); }}
                }}
            </style>

            <p style="
                text-align: center;
                font-family: Outfit, sans-serif;
                font-size: 0.8rem;
                color: #94a3b8;
                margin-top: 10px;
            ">Point camera at QR to join instantly</p>
        """, unsafe_allow_html=True)
