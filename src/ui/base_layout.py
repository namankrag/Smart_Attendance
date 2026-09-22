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
        # ── Button palette (dark) ──
        # Primary: electric violet → hot pink
        "btn_primary":         "linear-gradient(135deg,#a855f7 0%,#ec4899 50%,#f97316 100%)",
        "btn_primary_size":    "200% 200%",
        "btn_primary_pos":     "0% 50%",
        "btn_primary_pos_h":   "100% 50%",
        "btn_primary_glow":    "0 0 0 0 rgba(168,85,247,0)",
        "btn_primary_glow_h":  "0 0 22px 4px rgba(168,85,247,.55), 0 6px 24px rgba(236,72,153,.45)",
        "btn_primary_glow_a":  "0 0 14px 2px rgba(168,85,247,.7), 0 4px 14px rgba(236,72,153,.6)",
        "btn_primary_text":    "#ffffff",
        # Default: cyan → emerald
        "btn_default":         "linear-gradient(135deg,#06b6d4 0%,#10b981 100%)",
        "btn_default_size":    "200% 200%",
        "btn_default_pos":     "0% 50%",
        "btn_default_pos_h":   "100% 50%",
        "btn_default_glow":    "0 0 0 0 rgba(6,182,212,0)",
        "btn_default_glow_h":  "0 0 20px 4px rgba(6,182,212,.5), 0 6px 20px rgba(16,185,129,.4)",
        "btn_default_glow_a":  "0 0 12px 2px rgba(6,182,212,.65), 0 4px 12px rgba(16,185,129,.55)",
        "btn_default_text":    "#ffffff",
        # Secondary: amber → orange → red
        "btn_secondary":       "linear-gradient(135deg,#fbbf24 0%,#f97316 50%,#ef4444 100%)",
        "btn_secondary_size":  "200% 200%",
        "btn_secondary_pos":   "0% 50%",
        "btn_secondary_pos_h": "100% 50%",
        "btn_secondary_glow":  "0 0 0 0 rgba(251,191,36,0)",
        "btn_secondary_glow_h":"0 0 20px 4px rgba(251,191,36,.5), 0 6px 20px rgba(239,68,68,.4)",
        "btn_secondary_glow_a":"0 0 12px 2px rgba(251,191,36,.65), 0 4px 12px rgba(239,68,68,.55)",
        "btn_secondary_text":  "#1a0a00",
        # Tertiary: teal glass outline with shimmer
        "btn_tertiary_bg":     "rgba(6,182,212,.10)",
        "btn_tertiary_bg_h":   "rgba(6,182,212,.22)",
        "btn_tertiary_border": "#22d3ee",
        "btn_tertiary_glow_h": "0 0 16px 3px rgba(34,211,238,.4)",
        "btn_tertiary_text":   "#67e8f9",
    } if dark else {
        "surface": "rgba(255,255,255,.88)", "text": "#10243e", "muted": "#475b73", "line": "#cbd8e6",
        "field": "#ffffff", "primary": "#0f766e", "primary_deep": "#115e59", "accent": "#4f46e5",
        "danger": "#e11d48", "shadow": "rgba(15,23,42,.10)", "dialog": "#ffffff",
        # ── Button palette (light) ──
        # Primary: indigo → purple → pink
        "btn_primary":         "linear-gradient(135deg,#6366f1 0%,#a855f7 50%,#ec4899 100%)",
        "btn_primary_size":    "200% 200%",
        "btn_primary_pos":     "0% 50%",
        "btn_primary_pos_h":   "100% 50%",
        "btn_primary_glow":    "0 0 0 0 rgba(99,102,241,0)",
        "btn_primary_glow_h":  "0 0 20px 4px rgba(99,102,241,.40), 0 6px 20px rgba(168,85,247,.30)",
        "btn_primary_glow_a":  "0 0 12px 2px rgba(99,102,241,.55), 0 4px 12px rgba(168,85,247,.45)",
        "btn_primary_text":    "#ffffff",
        # Default: sky → teal
        "btn_default":         "linear-gradient(135deg,#38bdf8 0%,#2dd4bf 100%)",
        "btn_default_size":    "200% 200%",
        "btn_default_pos":     "0% 50%",
        "btn_default_pos_h":   "100% 50%",
        "btn_default_glow":    "0 0 0 0 rgba(56,189,248,0)",
        "btn_default_glow_h":  "0 0 18px 4px rgba(56,189,248,.38), 0 6px 18px rgba(45,212,191,.30)",
        "btn_default_glow_a":  "0 0 10px 2px rgba(56,189,248,.50), 0 4px 10px rgba(45,212,191,.40)",
        "btn_default_text":    "#ffffff",
        # Secondary: rose → orange
        "btn_secondary":       "linear-gradient(135deg,#f43f5e 0%,#fb923c 100%)",
        "btn_secondary_size":  "200% 200%",
        "btn_secondary_pos":   "0% 50%",
        "btn_secondary_pos_h": "100% 50%",
        "btn_secondary_glow":  "0 0 0 0 rgba(244,63,94,0)",
        "btn_secondary_glow_h":"0 0 18px 4px rgba(244,63,94,.35), 0 6px 18px rgba(251,146,60,.28)",
        "btn_secondary_glow_a":"0 0 10px 2px rgba(244,63,94,.48), 0 4px 10px rgba(251,146,60,.38)",
        "btn_secondary_text":  "#ffffff",
        # Tertiary: sky-teal glass outline
        "btn_tertiary_bg":     "rgba(14,165,233,.08)",
        "btn_tertiary_bg_h":   "rgba(14,165,233,.18)",
        "btn_tertiary_border": "#0ea5e9",
        "btn_tertiary_glow_h": "0 0 14px 3px rgba(14,165,233,.30)",
        "btn_tertiary_text":   "#0369a1",
    })
    st.html(f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@600;700;800&display=swap');
      #MainMenu, footer {{ visibility:hidden; }}
      [data-testid="stAppDeployButton"] {{ display:none !important; }}
      
      html, body, [class*="css"] {{ font-family:'DM Sans',sans-serif; }}
      .block-container {{ max-width:1180px; padding-top:2rem; padding-bottom:2.5rem; }}
      .stApp, .stApp p, .stApp label, .stApp span {{ color:{c['text']}; }}
      h1, h2, h3 {{ font-family:'Manrope',sans-serif !important; color:{c['text']} !important; letter-spacing:-.035em; }}
      h1 {{ font-size:clamp(2rem,4vw,3.1rem) !important; line-height:1.08 !important; }}
      h2 {{ font-size:clamp(1.45rem,2.8vw,2.05rem) !important; }}
      h3 {{ font-size:1.18rem !important; }}
      .stApp p {{ color:{c['muted']}; }}
      hr {{ border:0; height:1px; background:{c['line']}; margin:1.55rem 0; }}

      /* ══════════════════════════════════════════════════════
         BUTTON ANIMATIONS
      ══════════════════════════════════════════════════════ */
      @keyframes btn-shimmer {{
        0%   {{ background-position: 0% 50%; }}
        50%  {{ background-position: 100% 50%; }}
        100% {{ background-position: 0% 50%; }}
      }}
      @keyframes btn-pulse-primary {{
        0%, 100% {{ box-shadow: {c['btn_primary_glow']}; }}
        50%       {{ box-shadow: {c['btn_primary_glow_a']}; }}
      }}
      @keyframes btn-pulse-default {{
        0%, 100% {{ box-shadow: {c['btn_default_glow']}; }}
        50%       {{ box-shadow: {c['btn_default_glow_a']}; }}
      }}
      @keyframes btn-pulse-secondary {{
        0%, 100% {{ box-shadow: {c['btn_secondary_glow']}; }}
        50%       {{ box-shadow: {c['btn_secondary_glow_a']}; }}
      }}

      /* ── Base shared button reset ── */
      [data-testid="stButton"] > button {{
        width:100%; min-height:2.75rem;
        border-radius:.85rem; padding:.55rem 1.1rem;
        font-family:'DM Sans',sans-serif; font-weight:700; font-size:.92rem;
        letter-spacing:.01em;
        border:none; outline:none; cursor:pointer;
        position:relative; overflow:hidden;
        background-size:{c['btn_primary_size']};
        transition: transform .2s cubic-bezier(.34,1.56,.64,1),
                    box-shadow .22s ease,
                    background-position .6s ease,
                    filter .2s ease;
      }}
      /* Shimmer overlay pseudo-element */
      [data-testid="stButton"] > button::before {{
        content:'';
        position:absolute; inset:0;
        background: linear-gradient(110deg,
          rgba(255,255,255,0) 30%,
          rgba(255,255,255,.22) 50%,
          rgba(255,255,255,0) 70%);
        transform: translateX(-100%);
        transition: transform .55s ease;
        pointer-events:none; z-index:1;
      }}
      [data-testid="stButton"] > button:hover::before {{
        transform: translateX(100%);
      }}
      /* Press-down effect */
      [data-testid="stButton"] > button:active {{
        transform: translateY(1px) scale(.975) !important;
      }}

      /* ── Default (no type) — cyan → emerald ── */
      [data-testid="stButton"] > button:not([kind]) {{
        background: {c['btn_default']};
        background-size: {c['btn_default_size']};
        background-position: {c['btn_default_pos']};
        box-shadow: {c['btn_default_glow']};
      }}
      [data-testid="stButton"] > button:not([kind]),
      [data-testid="stButton"] > button:not([kind]) * {{
        color:{c['btn_default_text']} !important; fill:{c['btn_default_text']} !important;
      }}
      [data-testid="stButton"] > button:not([kind]):hover {{
        background-position: {c['btn_default_pos_h']};
        transform: translateY(-3px) scale(1.015);
        box-shadow: {c['btn_default_glow_h']};
        filter: brightness(1.08);
      }}
      [data-testid="stButton"] > button:not([kind]):focus-visible {{
        animation: btn-pulse-default 1.6s ease-in-out infinite;
      }}

      /* ── Primary — violet → pink → orange ── */
      [data-testid="stButton"] > button[kind="primary"] {{
        background: {c['btn_primary']};
        background-size: {c['btn_primary_size']};
        background-position: {c['btn_primary_pos']};
        box-shadow: {c['btn_primary_glow']};
      }}
      [data-testid="stButton"] > button[kind="primary"],
      [data-testid="stButton"] > button[kind="primary"] * {{
        color:{c['btn_primary_text']} !important; fill:{c['btn_primary_text']} !important;
      }}
      [data-testid="stButton"] > button[kind="primary"]:hover {{
        background-position: {c['btn_primary_pos_h']};
        transform: translateY(-3px) scale(1.015);
        box-shadow: {c['btn_primary_glow_h']};
        filter: brightness(1.08);
      }}
      [data-testid="stButton"] > button[kind="primary"]:focus-visible {{
        animation: btn-pulse-primary 1.6s ease-in-out infinite;
      }}

      /* ── Secondary — amber/rose → orange/red ── */
      [data-testid="stButton"] > button[kind="secondary"] {{
        background: {c['btn_secondary']};
        background-size: {c['btn_secondary_size']};
        background-position: {c['btn_secondary_pos']};
        box-shadow: {c['btn_secondary_glow']};
      }}
      [data-testid="stButton"] > button[kind="secondary"],
      [data-testid="stButton"] > button[kind="secondary"] * {{
        color:{c['btn_secondary_text']} !important; fill:{c['btn_secondary_text']} !important;
      }}
      [data-testid="stButton"] > button[kind="secondary"]:hover {{
        background-position: {c['btn_secondary_pos_h']};
        transform: translateY(-3px) scale(1.015);
        box-shadow: {c['btn_secondary_glow_h']};
        filter: brightness(1.08);
      }}
      [data-testid="stButton"] > button[kind="secondary"]:focus-visible {{
        animation: btn-pulse-secondary 1.6s ease-in-out infinite;
      }}

      /* ── Tertiary — glass cyan outline ── */
      [data-testid="stButton"] > button[kind="tertiary"] {{
        background: {c['btn_tertiary_bg']};
        border: 1.5px solid {c['btn_tertiary_border']} !important;
        box-shadow: none;
        backdrop-filter: blur(6px);
      }}
      [data-testid="stButton"] > button[kind="tertiary"],
      [data-testid="stButton"] > button[kind="tertiary"] * {{
        color:{c['btn_tertiary_text']} !important; fill:{c['btn_tertiary_text']} !important;
      }}
      [data-testid="stButton"] > button[kind="tertiary"]:hover {{
        background: {c['btn_tertiary_bg_h']};
        transform: translateY(-3px) scale(1.015);
        box-shadow: {c['btn_tertiary_glow_h']};
        border-color: {c['btn_tertiary_border']} !important;
      }}

      /* Disabled state — dim everything */
      [data-testid="stButton"] > button:disabled,
      [data-testid="stButton"] > button[disabled] {{
        opacity: .38 !important;
        cursor: not-allowed !important;
        transform: none !important;
        filter: none !important;
        box-shadow: none !important;
        animation: none !important;
      }}

      /* ── Sidebar panel styles ── */
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
      
      /* Sidebar text — larger, bolder, theme-aware */
      [data-testid="stSidebar"] *:not(button):not(svg) {{
        color: {c['text']} !important;
      }}
      [data-testid="stSidebar"] [data-testid="stMarkdown"] {{
        font-size: 1.05rem !important;
        font-weight: 700 !important;
        line-height: 1.4 !important;
      }}
      [data-testid="stSidebar"] [data-testid="stMarkdown"] div {{
        font-weight: 700 !important;
      }}
      [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{
        font-size: 0.85rem !important;
        font-weight: 700 !important;
        letter-spacing: 0.05em !important;
        opacity: 0.85 !important;
      }}

      /* ══════════════════════════════════════════════════════
         MOBILE RESPONSIVE — ≤ 768 px
      ══════════════════════════════════════════════════════ */
      @media (max-width: 768px) {{
        .block-container {{ padding:.9rem .7rem 2rem !important; }}
        h1 {{ font-size:1.75rem !important; }}
        h2 {{ font-size:1.3rem !important; }}
        h3 {{ font-size:1.05rem !important; }}
        [data-testid="stHorizontalBlock"] {{ flex-wrap:wrap !important; gap:.6rem !important; }}
        [data-testid="column"], [data-testid="stColumn"] {{ flex:1 1 100% !important; width:100% !important; min-width:100% !important; }}

        /* Sidebar slides in as overlay */
        [data-testid="stSidebar"] {{ min-width:min(88vw,18rem) !important; max-width:min(88vw,18rem) !important; z-index:9999 !important; }}
        [data-testid="stSidebar"] .block-container {{ padding:1rem .85rem 2rem !important; }}
        [data-testid="stSidebar"] [data-testid="stButton"] > button {{ margin-bottom:.5rem; font-size:.95rem; min-height:3rem; }}

        /* Sidebar toggle — large floating tap target */
        [data-testid="stSidebarCollapsedControl"] {{
          top:.65rem !important; left:.65rem !important;
          position:fixed !important; z-index:10000 !important;
          background:{c['surface']} !important;
          border:2px solid {c['accent']} !important;
          border-radius:.65rem !important;
          box-shadow:0 4px 16px rgba(0,0,0,.30) !important;
          visibility:visible !important; display:flex !important;
          align-items:center !important; justify-content:center !important;
          width:2.6rem !important; height:2.6rem !important;
          padding:.25rem !important;
        }}
        [data-testid="stSidebarCollapsedControl"] button,
        [data-testid="stSidebarCollapsedControl"] button:hover {{
          background:transparent !important; box-shadow:none !important;
          border:none !important; width:100% !important; height:100% !important; padding:0 !important;
        }}
        [data-testid="stSidebarCollapsedControl"] button svg {{
          color:{c['accent']} !important; fill:{c['accent']} !important;
          width:1.4rem !important; height:1.4rem !important;
        }}

        /* Dialogs full-width */
        [data-testid="stDialog"] [role="dialog"] {{ max-width:calc(100vw - .8rem) !important; border-radius:1rem !important; margin:.4rem !important; }}
        [data-testid="stDialog"] section {{ padding:.7rem !important; }}

        /* Inputs / camera */
        [data-testid="stCameraInput"], [data-testid="stAudioInput"], [data-testid="stFileUploader"] {{ padding:.4rem !important; }}

        /* Buttons — bigger tap targets */
        [data-testid="stButton"] > button {{ min-height:3rem !important; font-size:.95rem !important; border-radius:.75rem !important; }}

        /* Tables scroll */
        [data-testid="stDataFrame"] {{ overflow-x:auto !important; }}
      }}

      /* Very small phones */
      @media (max-width: 420px) {{
        h1 {{ font-size:1.45rem !important; }}
        h2 {{ font-size:1.15rem !important; }}
        .block-container {{ padding:.7rem .5rem 2rem !important; }}
      }}
    </style>
    """)
