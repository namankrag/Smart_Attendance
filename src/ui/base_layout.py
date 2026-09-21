"""Shared visual language for the SmartClass Streamlit app."""

import streamlit as st


def is_dark_theme() -> bool:
    return st.session_state.get("theme", "light") == "dark"


def style_bg_home() -> None:
    """Apply the distinct, slightly richer backdrop used by the landing page."""
    if is_dark_theme():
        background = "radial-gradient(circle at 14% 12%, #164e63 0, transparent 28%), radial-gradient(circle at 86% 82%, #312e81 0, transparent 28%), #07111f"
    else:
        background = "radial-gradient(circle at 15% 12%, #ccfbf1 0, transparent 29%), radial-gradient(circle at 86% 85%, #e0e7ff 0, transparent 32%), #f8fafc"
    st.html(f"<style>.stApp {{ background: {background}; }}</style>")


def style_bg_dashboard() -> None:
    """Apply a quiet, readable dashboard backdrop in either theme."""
    if is_dark_theme():
        background = "radial-gradient(circle at 94% 0%, rgba(20,184,166,.13), transparent 25%), radial-gradient(circle at 2% 100%, rgba(99,102,241,.14), transparent 30%), #09111f"
    else:
        background = "radial-gradient(circle at 96% 0%, rgba(45,212,191,.16), transparent 24%), radial-gradient(circle at 0% 100%, rgba(199,210,254,.35), transparent 30%), #f6f8fc"
    st.html(f"<style>.stApp {{ background: {background}; }}</style>")


def style_base_layout() -> None:
    """Style Streamlit primitives once so screens and dialogs stay cohesive."""
    dark = is_dark_theme()
    c = ({
        "surface": "#101c2d", "text": "#f4f8ff", "muted": "#c3d0e1", "line": "#38526e",
        "field": "#0c1727", "primary": "#0f9b8e", "primary_deep": "#0f766e", "accent": "#818cf8",
        "danger": "#fb7185", "shadow": "rgba(0,0,0,.32)", "dialog": "#101c2d",
    } if dark else {
        "surface": "rgba(255,255,255,.88)", "text": "#10243e", "muted": "#475b73", "line": "#cbd8e6",
        "field": "#ffffff", "primary": "#0f766e", "primary_deep": "#115e59", "accent": "#4f46e5",
        "danger": "#e11d48", "shadow": "rgba(15,23,42,.10)", "dialog": "#ffffff",
    })
    st.html(f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@600;700;800&display=swap');
      #MainMenu, footer {{ visibility:hidden; }}
      [data-testid="stHeader"] {{ background:transparent !important; }}
      [data-testid="stAppDeployButton"] {{ display:none !important; }}
      [data-testid="stSidebarCollapsedControl"] {{ visibility:visible !important; }}
      html, body, [class*="css"] {{ font-family:'DM Sans',sans-serif; }}
      .block-container {{ max-width:1180px; padding-top:2rem; padding-bottom:2.5rem; }}
      .stApp, .stApp p, .stApp label, .stApp span {{ color:{c['text']}; }}
      h1, h2, h3 {{ font-family:'Manrope',sans-serif !important; color:{c['text']} !important; letter-spacing:-.035em; }}
      h1 {{ font-size:clamp(2rem,4vw,3.1rem) !important; line-height:1.08 !important; }}
      h2 {{ font-size:clamp(1.45rem,2.8vw,2.05rem) !important; }}
      h3 {{ font-size:1.18rem !important; }}
      .stApp p {{ color:{c['muted']}; }}
      hr {{ border:0; height:1px; background:{c['line']}; margin:1.55rem 0; }}
      [data-testid="stButton"] > button {{ width:100%; min-height:2.7rem; border:1px solid transparent; border-radius:.75rem; padding:.55rem 1rem; font-family:'DM Sans',sans-serif; font-weight:700; transition:transform .18s ease, box-shadow .18s ease, background .18s ease; box-shadow:0 4px 10px {c['shadow']}; }}
      [data-testid="stButton"] > button, [data-testid="stButton"] > button * {{ color:{c['text']} !important; fill:currentColor !important; }}
      [data-testid="stButton"] > button[kind="primary"], [data-testid="stButton"] > button[kind="primary"] * {{ background:{c['primary']}; color:#fff !important; fill:#fff !important; }}
      [data-testid="stButton"] > button[kind="primary"]:hover {{ background:{c['primary_deep']}; transform:translateY(-1px); box-shadow:0 9px 18px {c['shadow']}; }}
      [data-testid="stButton"] > button[kind="secondary"], [data-testid="stButton"] > button[kind="secondary"] * {{ background:transparent; color:{c['danger']} !important; fill:{c['danger']} !important; border-color:{c['danger']}; box-shadow:none; }}
      [data-testid="stButton"] > button[kind="tertiary"], [data-testid="stButton"] > button[kind="tertiary"] * {{ background:{c['surface']}; color:{c['text']} !important; fill:{c['text']} !important; border-color:{c['line']}; box-shadow:none; }}
      [data-testid="stButton"] > button[kind="tertiary"]:hover {{ border-color:{c['accent']}; color:{c['accent']}; transform:translateY(-1px); }}
      [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea, [data-baseweb="select"] > div {{ background:{c['field']} !important; color:{c['text']} !important; border:1px solid {c['line']} !important; border-radius:.75rem !important; min-height:2.8rem; box-shadow:none !important; }}
      [data-testid="stTextInput"] input:focus, [data-testid="stTextArea"] textarea:focus, [data-baseweb="select"]:focus-within > div {{ border-color:{c['primary']} !important; box-shadow:0 0 0 3px {c['primary']}25 !important; }}
      [data-testid="stTextInput"] label, [data-testid="stTextArea"] label, [data-testid="stSelectbox"] label {{ color:{c['text']} !important; font-weight:700; font-size:.9rem; }}
      [data-testid="stTextInput"] input::placeholder, [data-testid="stTextArea"] textarea::placeholder {{ color:{c['muted']} !important; opacity:.75; }}
      [data-baseweb="select"] *, ul[role="listbox"] *, [data-testid="stSelectbox"] svg {{ color:{c['text']} !important; }}
      ul[role="listbox"] {{ background:{c['dialog']} !important; border:1px solid {c['line']} !important; }}
      /* Streamlit's dialog panel has nested wrappers; style the panel and its surface together. */
      [data-testid="stDialog"] [role="dialog"], [data-testid="stDialog"] [role="dialog"] > div, [data-testid="stDialog"] section {{ background:linear-gradient(145deg, {c['dialog']}, {c['surface']}) !important; }}
      [data-testid="stDialog"] [role="dialog"] {{ border:1px solid {c['line']} !important; border-radius:1.35rem !important; box-shadow:0 28px 90px {c['shadow']}, 0 0 0 1px {c['accent']}18 !important; overflow:hidden; }}
      [data-testid="stDialog"] section {{ padding:1.1rem !important; }}
      [data-testid="stDialog"] h1 {{ font-size:1.35rem !important; color:{c['text']} !important; }}
      [data-testid="stDialog"] button[aria-label*="close" i], [data-testid="stDialog"] button[aria-label*="close" i] * {{ color:{c['text']} !important; fill:{c['text']} !important; opacity:1 !important; }}
      [data-testid="stDialog"] button[aria-label*="close" i] {{ border-radius:50% !important; width:2.2rem !important; min-width:2.2rem !important; height:2.2rem !important; background:{c['surface']} !important; border:1px solid {c['line']} !important; box-shadow:none !important; }}
      /* Streamlit's password toggle is not a regular stButton, so style it separately. */
      [data-testid="stTextInput"] button {{ background:{c['field']} !important; color:{c['text']} !important; border-color:{c['line']} !important; box-shadow:none !important; }}
      [data-testid="stTextInput"] button svg, [data-testid="stTextInput"] button * {{ color:{c['text']} !important; fill:currentColor !important; opacity:1 !important; }}
      [data-testid="stTextInputRootElement"] {{ background:{c['field']} !important; border-radius:.75rem !important; }}
      [data-testid="stDialog"] [data-testid="stCodeBlock"], [data-testid="stDialog"] pre {{ background:{c['field']} !important; border:1px solid {c['line']} !important; border-radius:.85rem !important; color:{c['text']} !important; }}
      [data-testid="stDialog"] code, [data-testid="stDialog"] pre * {{ color:{c['text']} !important; }}
      [data-testid="stDialog"] [data-testid="stHorizontalBlock"] {{ gap:.85rem; }}
      .dialog-banner {{ position:relative; overflow:hidden; box-shadow:inset 0 1px 0 rgba(255,255,255,.18); }}
      .dialog-banner::after {{ content:''; position:absolute; width:150px; height:150px; right:-45px; top:-72px; border-radius:50%; background:rgba(255,255,255,.12); }}
      .dialog-banner h2, .dialog-banner p {{ position:relative; z-index:1; }}
      [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {{ color:{c['muted']} !important; opacity:1 !important; font-weight:600 !important; }}
      [data-testid="stDialog"] [data-testid="stAlert"] *, [data-testid="stDialog"] [data-testid="stAlert"] {{ color:{c['text']} !important; opacity:1 !important; }}
      [data-testid="stFileUploader"], [data-testid="stCameraInput"], [data-testid="stAudioInput"] {{ background:{c['surface']} !important; border:1px dashed {c['line']} !important; border-radius:1rem !important; padding:.7rem !important; }}
      /* Camera capture/clear actions also live outside Streamlit's standard button wrapper. */
      [data-testid="stCameraInput"] button {{ background:{c['surface']} !important; color:{c['text']} !important; border:1px solid {c['line']} !important; box-shadow:none !important; }}
      [data-testid="stCameraInput"] button svg, [data-testid="stCameraInput"] button * {{ color:{c['text']} !important; fill:currentColor !important; opacity:1 !important; }}
      [data-testid="stDataFrame"] {{ border:1px solid {c['line']}; border-radius:.9rem; overflow:hidden; }}
      [data-testid="stAlert"] {{ border-radius:.8rem; border:1px solid {c['line']}; }}
      [data-testid="stToast"] {{ background:{c['dialog']} !important; color:{c['text']} !important; border:1px solid {c['line']}; border-radius:.8rem; }}
      [data-testid="stImage"] img {{ border-radius:.8rem; }}
      [data-testid="stVerticalBlockBorderWrapper"] {{ background:{c['surface']}; border:1px solid {c['line']} !important; border-radius:1rem !important; box-shadow:0 10px 28px {c['shadow']}; }}
      [data-testid="stSidebar"] {{ background:linear-gradient(180deg, {c['surface']}, {c['dialog']}) !important; border-right:1px solid {c['line']} !important; }}
      [data-testid="stSidebar"] [data-testid="stButton"] > button {{ margin-bottom:.35rem; text-align:left; }}
      @media (max-width: 720px) {{
        .block-container {{ padding:1.1rem .9rem 2rem; }}
        h1 {{ font-size:2rem !important; }}
        h2 {{ font-size:1.5rem !important; }}
        [data-testid="stHorizontalBlock"] {{ flex-wrap:wrap !important; gap:.7rem !important; }}
        [data-testid="column"], [data-testid="stColumn"] {{ flex:1 1 100% !important; width:100% !important; min-width:100% !important; }}
        [data-testid="stSidebar"] {{ min-width:min(82vw, 20rem) !important; max-width:min(82vw, 20rem) !important; }}
        [data-testid="stSidebar"] .block-container {{ padding:1.2rem .9rem 2rem !important; }}
        [data-testid="stDialog"] [role="dialog"] {{ max-width:calc(100vw - 1rem) !important; border-radius:1rem !important; }}
        [data-testid="stDialog"] section {{ padding:.75rem !important; }}
        [data-testid="stCameraInput"] {{ padding:.45rem !important; }}
      }}
    </style>
    """)
