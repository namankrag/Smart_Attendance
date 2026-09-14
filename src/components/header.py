import streamlit as st
from pathlib import Path
import base64

BASE_DIR = Path(__file__).resolve().parents[2]

def _img_to_base64(img_path: Path) -> str:
    with open(img_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def header_home():
    logo_b64 = _img_to_base64(BASE_DIR / "img" / "header.png")

    st.markdown(f"""
    <div style = "display : flex; flex-direction : column; align-items : center; justify-content : center; margin-bottom : 30px; margin-top : 30px">
        <img src = 'data:image/png;base64,{logo_b64}' style = 'height : 100px;' />
        <h1 style = 'text-align : center; color : #E0E3FF'> SMART<br/>CLASS</h1>
    </div>
    
        """, unsafe_allow_html=True)

def header_dashboard():
    logo_b64 = _img_to_base64(BASE_DIR / "img" / "header.png")
    
    st.markdown(f"""
        <div style="display : flex; align-items : center; justify-content : center; gap : 10px">
            <img src = 'data:image/png;base64,{logo_b64}' style = 'height : 85px;' />
            <h2 style = 'text-align : left; color : #5865F2'> SMART <br/> CLASS </h1>
        </div>   
                
                """, unsafe_allow_html=True)