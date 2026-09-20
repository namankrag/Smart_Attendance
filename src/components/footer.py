import streamlit as st
from pathlib import Path
import base64

BASE_DIR = Path(__file__).resolve().parents[2]

def _img_to_base64(img_path: Path) -> str:
    with open(img_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def footer_home():
    logo_b64 = _img_to_base64(BASE_DIR / "img" / "NKA.png")

    st.markdown(f"""
    <div style="
        margin-top: 3rem;
        display: flex;
        gap: 8px;
        justify-content: center;
        align-items: center;
        padding: 20px;
        border-radius: 15px;
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(10px);
    ">
        <p style="
            font-weight: 600;
            color: white;
            margin: 0;
            font-size: 1rem;
            text-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
        "> Created by </p>
        <img src='data:image/png;base64,{logo_b64}' style='
            max-height: 28px;
            filter: drop-shadow(0 2px 8px rgba(0, 0, 0, 0.2));
        ' />
    </div> 
        """, unsafe_allow_html=True)


def footer_dashboard():
    logo_b64 = _img_to_base64(BASE_DIR / "img" / "NKA.png")
    
    st.markdown(f"""
    <div style="
        margin-top: 3rem;
        display: flex;
        gap: 8px;
        justify-content: center;
        align-items: center;
        padding: 20px;
        border-radius: 15px;
        background: linear-gradient(135deg, rgba(255, 255, 255, 0.8) 0%, rgba(255, 255, 255, 0.6) 100%);
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05);
        backdrop-filter: blur(10px);
    ">
        <p style="
            font-weight: 700;
            color: #334155;
            margin: 0;
            font-size: 1rem;
        "> Created by </p>
        <img src='data:image/png;base64,{logo_b64}' style='
            max-height: 28px;
            filter: drop-shadow(0 2px 6px rgba(0, 0, 0, 0.1));
        ' />
    </div> 
            """, unsafe_allow_html=True)