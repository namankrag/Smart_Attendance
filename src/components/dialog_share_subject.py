"""Share a subject's join link / QR code.

The join_code is shown SEPARATELY from the subject_code: subject_code is
the human display code (e.g. CS101), join_code is the unguessable,
URL-safe enrolment secret that goes in ``?join-code=``. Never build a
join link from the subject_code.
"""

import base64
import io
import logging
from urllib.parse import quote

import segno
import streamlit as st

from src.components.dialog_utils import dialog_banner
from src.ui.base_layout import is_dark_theme

try:
    from src.database.db import get_subject_join_code
except ImportError:  # pragma: no cover - db agent has not landed yet
    get_subject_join_code = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


@st.dialog("Share Class Link", width="large")
def share_subject(sub_name: str, sub_code: str, join_code: str | None = None, subject_id=None):
    # Resolve the join code if the caller did not pass it. The db function
    # is assumed to be get_subject_join_code(subject_id) (db agent to
    # confirm); if it cannot be resolved, do not fall back to the
    # subject_code — show that the join code is unavailable instead.
    if not join_code and subject_id is not None and get_subject_join_code is not None:
        try:
            join_code = get_subject_join_code(subject_id)
        except TypeError:
            try:
                join_code = get_subject_join_code(sub_code)
            except Exception:
                logger.exception("get_subject_join_code failed")
                join_code = None
        except Exception:
            logger.exception("get_subject_join_code failed")
            join_code = None

    dialog_banner(
        "Share Class Link", subtitle=f"Invite students to join {sub_name}", theme="purple"
    )
    dark = is_dark_theme()

    # Determine base domain dynamically if available, otherwise default
    base_url = "https://attend-dev.streamlit.app"
    try:
        # Check if custom base url is specified in secrets
        if "APP_URL" in st.secrets:
            base_url = st.secrets["APP_URL"].rstrip("/")
    except Exception:
        pass

    join_url = f"{base_url}/?join-code={quote(join_code, safe='')}" if join_code else None

    # ── Coloured QR code (only when a real join code exists) ──
    qr_b64 = None
    if join_url:
        qr = segno.make(join_url, error="h")
        out = io.BytesIO()
        if dark:
            qr.save(
                out,
                kind="png",
                scale=12,
                border=2,
                dark="#818cf8",
                light="#0f172a",
                data_dark="#c084fc",
            )
        else:
            qr.save(
                out,
                kind="png",
                scale=12,
                border=2,
                dark="#5144d3",
                light="#f0f0ff",
                data_dark="#a855f7",
            )
        qr_b64 = base64.b64encode(out.getvalue()).decode()

    col1, col2 = st.columns([1.1, 1], gap="medium")

    link_title_col = "#818cf8" if dark else "#5144d3"
    code_title_col = "#c084fc" if dark else "#a855f7"
    box_bg = (
        "linear-gradient(135deg, #312e81 0%, #1e1b4b 100%)"
        if dark
        else "linear-gradient(135deg, #e0e7ff 0%, #ede9fe 100%)"
    )
    box_border = "#818cf8" if dark else "#667eea"
    box_text_col = "#c7d2fe" if dark else "#4338ca"
    scan_sub_col = "#94a3b8"

    with col1:
        st.markdown(
            f"""
            <p style="
                font-family: Outfit, sans-serif;
                font-weight: 700;
                font-size: 1rem;
                color: {link_title_col};
                margin-bottom: 6px;
                letter-spacing: 1px;
                text-transform: uppercase;
            ">🔗 Join Link</p>
        """,
            unsafe_allow_html=True,
        )
        if join_url:
            st.code(join_url, language="text")
        else:
            st.warning(
                "Join code is not available for this subject yet. Ask the teacher to recreate the s"
                    "ubject or contact support."
            )

        st.markdown(
            f"""
            <p style="
                font-family: Outfit, sans-serif;
                font-weight: 700;
                font-size: 1rem;
                color: {code_title_col};
                margin: 10px 0 6px;
                letter-spacing: 1px;
                text-transform: uppercase;
            ">🎫 Join Code</p>
        """,
            unsafe_allow_html=True,
        )
        if join_code:
            st.code(join_code, language="text")
        else:
            st.caption("Join code unavailable.")

        st.markdown(
            f"""
            <p style="
                font-family: Outfit, sans-serif;
                font-weight: 700;
                font-size: 1rem;
                color: {code_title_col};
                margin: 10px 0 6px;
                letter-spacing: 1px;
                text-transform: uppercase;
            ">📚 Subject Code</p>
        """,
            unsafe_allow_html=True,
        )
        st.code(sub_code, language="text")
        st.caption(
            "The subject code identifies the class; only the join code above enrolls students."
        )

        st.markdown(
            f"""
            <div style="
                background: {box_bg};
                border-left: 4px solid {box_border};
                border-radius: 12px;
                padding: 12px 16px;
                margin-top: 10px;
                font-family: Outfit, sans-serif;
                font-size: 0.9rem;
                color: {box_text_col};
                font-weight: 500;
            ">
                💬 Share this link or join code via <b>WhatsApp</b>, <b>Email</b>, or LMS!
            </div>
        """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""
            <p style="
                font-family: Outfit, sans-serif;
                font-weight: 700;
                font-size: 1rem;
                color: {link_title_col};
                margin-bottom: 8px;
                letter-spacing: 1px;
                text-transform: uppercase;
                text-align: center;
            ">📱 Scan to Join</p>
        """,
            unsafe_allow_html=True,
        )

        if qr_b64:
            st.markdown(
                f"""
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
                    color: {scan_sub_col};
                    margin-top: 10px;
                ">Point camera at QR to join instantly</p>
            """,
                unsafe_allow_html=True,
            )
        else:
            st.caption("QR code unavailable without a join code.")
