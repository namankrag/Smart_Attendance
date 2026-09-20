import streamlit as st
from pathlib import Path
import base64

BASE_DIR = Path(__file__).resolve().parents[2]

def _img_to_base64(img_path: Path) -> str:
    with open(img_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def header_home():
    logo_b64 = _img_to_base64(BASE_DIR / "img" / "header.png")

    st.html(
        '<style>'
        '@keyframes fadeInDown{from{opacity:0;transform:translateY(-30px)}to{opacity:1;transform:translateY(0)}}'
        '@keyframes float{0%,100%{transform:translateY(0px)}50%{transform:translateY(-10px)}}'
        '</style>'
        '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;'
        'margin-bottom:40px;margin-top:30px;animation:fadeInDown 0.8s ease-out;">'
        '<img src="data:image/png;base64,' + logo_b64 + '" style="height:100px;width:auto;'
        'filter:drop-shadow(0 10px 30px rgba(255,255,255,0.35)) brightness(1.1);'
        'animation:float 3s ease-in-out infinite;margin-bottom:18px;" />'
        '<div style="display:flex;flex-direction:column;align-items:center;gap:0;">'
        '<span style="font-family:\'Climate Crisis\',sans-serif;font-size:4rem;font-weight:900;'
        'color:#ffffff;letter-spacing:8px;white-space:nowrap;'
        'text-shadow:0 4px 24px rgba(0,0,0,0.22),0 0 60px rgba(255,255,255,0.15);'
        'line-height:1;-webkit-text-fill-color:#ffffff;">SMART</span>'
        '<span style="font-family:\'Climate Crisis\',sans-serif;font-size:4rem;font-weight:900;'
        'letter-spacing:8px;white-space:nowrap;line-height:1;'
        'background:linear-gradient(90deg,#fde68a 0%,#fbbf24 40%,#f472b6 100%);'
        '-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;">'
        'CLASS</span>'
        '</div>'
        '</div>'
    )

def header_dashboard():
    logo_b64 = _img_to_base64(BASE_DIR / "img" / "header.png")

    st.html(
        '<div style="display:flex;align-items:center;justify-content:flex-start;gap:14px;'
        'padding:14px 22px;border-radius:20px;'
        'background:linear-gradient(135deg,rgba(255,255,255,0.92) 0%,rgba(224,227,255,0.85) 100%);'
        'box-shadow:0 8px 30px rgba(102,126,234,0.18);backdrop-filter:blur(12px);width:fit-content;">'
        '<img src="data:image/png;base64,' + logo_b64 + '" style="height:52px;width:auto;'
        'flex-shrink:0;filter:drop-shadow(0 3px 10px rgba(102,126,234,0.25));" />'
        '<div style="display:flex;flex-direction:column;line-height:1;gap:2px;">'
        '<span style="font-family:\'Climate Crisis\',sans-serif;font-size:1.45rem;font-weight:900;'
        'color:#5144d3;letter-spacing:4px;white-space:nowrap;">SMART</span>'
        '<span style="font-family:\'Climate Crisis\',sans-serif;font-size:1.45rem;font-weight:900;'
        'color:#a855f7;letter-spacing:4px;white-space:nowrap;">CLASS</span>'
        '</div>'
        '</div>'
    )
