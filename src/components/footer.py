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
    <div style = "margin-top : 2rem; display : flex; gap : 6px; justify-content : center; align-items : center">
        <p style = "font-weight : bold; color : white;"> Created by </p>
        <img src = 'data:image/png;base64,{logo_b64}' style = 'max-height : 25px' />
    </div> 
        """, unsafe_allow_html=True)


def footer_dashboard():
    logo_b64 = _img_to_base64(BASE_DIR / "img" / "NKA.png")
    
    st.markdown(f"""
    <div style = "margin-top : 2rem; display : flex; gap : 6px; justify-content : center; align-items : center">
        <p style = "font-weight : bold; color : black;"> Created by </p>
        <img src = 'data:image/png;base64,{logo_b64}' style = 'max-height : 25px' />
    </div> 
            """, unsafe_allow_html=True)