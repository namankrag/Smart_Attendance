import streamlit as st
from pathlib import Path
import base64

BASE_DIR = Path(__file__).resolve().parents[2]

def _img_to_base64(img_path: Path) -> str:
    with open(img_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def theme_toggle(key_suffix: str = "hdr"):
    if "theme" not in st.session_state:
        st.session_state["theme"] = "light"

    current = st.session_state["theme"]
    is_dark = current == "dark"
    label = "☀️ Light" if is_dark else "🌙 Dark"

    if st.button(label, key=f"theme_toggle_{key_suffix}", type="tertiary", width="stretch"):
        st.session_state["theme"] = "light" if is_dark else "dark"
        st.rerun()

def header_home():
    logo_b64 = _img_to_base64(BASE_DIR / "img" / "header.png")

    top_col1, top_col2 = st.columns([6, 1.4], vertical_alignment="center")
    with top_col2:
        st.markdown("<div style='margin-top: 12px;'></div>", unsafe_allow_html=True)
        theme_toggle("home")

    is_dark = st.session_state.get('theme', 'light') == 'dark'
    title_color = "#f8fafc" if is_dark else "#122033"
    accent = "#5eead4" if is_dark else "#0f766e"

    st.html(
        '<style>'
        '@keyframes fadeInDown{from{opacity:0;transform:translateY(-30px)}to{opacity:1;transform:translateY(0)}}'
        '@keyframes float{0%,100%{transform:translateY(0px)}50%{transform:translateY(-10px)}}'
        '</style>'
        '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;'
        'margin-bottom:34px;margin-top:4px;animation:fadeInDown 0.8s ease-out;">'
        '<div style="width:88px;height:88px;display:grid;place-items:center;border-radius:25px;background:rgba(255,255,255,.55);border:1px solid rgba(15,118,110,.18);box-shadow:0 12px 30px rgba(15,23,42,.12);margin-bottom:18px;">'
        '<img src="data:image/png;base64,' + logo_b64 + '" style="height:62px;width:auto;filter:drop-shadow(0 5px 10px rgba(15,23,42,.18));animation:float 3s ease-in-out infinite;" /></div>'
        '<div style="display:flex;flex-direction:column;align-items:center;gap:0;">'
        '<span style="font-family:\'Manrope\',sans-serif;font-size:clamp(2.65rem,7vw,4.4rem);font-weight:800;'
        'color:' + title_color + ';letter-spacing:-.07em;white-space:nowrap;line-height:.92;">SMART</span>'
        '<span style="font-family:\'Manrope\',sans-serif;font-size:clamp(2.65rem,7vw,4.4rem);font-weight:800;letter-spacing:-.07em;white-space:nowrap;line-height:.92;color:' + accent + ';">CLASS</span>'
        '</div>'
        '</div>'
    )

def header_dashboard():
    logo_b64 = _img_to_base64(BASE_DIR / "img" / "header.png")
    is_dark = st.session_state.get('theme', 'light') == 'dark'

    bg_style = (
        'linear-gradient(135deg,rgba(30,41,59,0.92) 0%,rgba(15,23,42,0.85) 100%)'
        if is_dark else
        'linear-gradient(135deg,rgba(255,255,255,0.92) 0%,rgba(224,227,255,0.85) 100%)'
    )
    border_style = 'border:1px solid rgba(129,140,248,0.3);' if is_dark else ''
    shadow_style = 'box-shadow:0 8px 30px rgba(0,0,0,0.4);' if is_dark else 'box-shadow:0 8px 30px rgba(102,126,234,0.18);'
    c1_color = "#818cf8" if is_dark else "#5144d3"
    c2_color = "#c084fc" if is_dark else "#a855f7"

    st.html(
        f'<div style="display:flex;align-items:center;justify-content:center;gap:14px;'
        f'padding:14px 22px;border-radius:20px;background:{bg_style};{border_style}'
        f'{shadow_style}backdrop-filter:blur(12px);width:fit-content;margin:0 auto;">'
        f'<img src="data:image/png;base64,{logo_b64}" style="height:52px;width:auto;'
        f'flex-shrink:0;filter:drop-shadow(0 3px 10px rgba(129,140,248,0.35));" />'
        f'<div style="display:flex;flex-direction:column;line-height:1;gap:2px;">'
        f'<span style="font-family:\'Climate Crisis\',sans-serif;font-size:1.45rem;font-weight:900;'
        f'color:{c1_color};letter-spacing:4px;white-space:nowrap;">SMART</span>'
        f'<span style="font-family:\'Climate Crisis\',sans-serif;font-size:1.45rem;font-weight:900;'
        f'color:{c2_color};letter-spacing:4px;white-space:nowrap;">CLASS</span>'
        f'</div>'
        f'</div>'
    )
