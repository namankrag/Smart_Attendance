import streamlit as st
import segno
import io

@st.dialog("Share Class Link")
def share_subject(sub_name, sub_code):
    app_dom = "http://localhost:8501"
    join_url = f"{app_dom}/?join-code={sub_code}"

    st.header("Scan to Join")
    qr = segno.make(join_url)
    out = io.BytesIO()
    qr.save(out, kind = 'png', scale = 10, border = 1)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown('### Copy Link')
        st.code(join_url, language="text")
        st.code(sub_code, language="text")
        st.info("Copy this Link to share on Whatsapp or Email")
    with col2:
        st.markdown("### Scan to Join")
        st.image(out.getvalue(), caption='QRCODE for class joining')