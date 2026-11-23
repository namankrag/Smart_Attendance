import streamlit as st
from pathlib import Path
from src.ui.base_layout import is_dark_theme
from src.ui.images import img_to_base64

BASE_DIR = Path(__file__).resolve().parents[2]

# Phase 1: image loading tolerates missing files (see src/ui/images.py).


def _logo_img_tag(logo_b64: str) -> str:
    """<img> tag for the base64 logo, or "" when the logo is unavailable."""
    if not logo_b64:
        return ""
    return (
        f'<img src="data:image/png;base64,{logo_b64}" style="max-height:28px;'
        f'filter:drop-shadow(0 2px 8px rgba(0,0,0,0.4));" />'
    )


def footer_home():
    logo_b64 = img_to_base64(BASE_DIR / "img" / "NKA.png")
    is_dark = is_dark_theme()
    bg_style = "rgba(30, 41, 59, 0.6)" if is_dark else "rgba(255, 255, 255, 0.15)"
    border_style = "border:1px solid rgba(129, 140, 248, 0.2);" if is_dark else ""
    text_color = "#f8fafc" if is_dark else "white"

    st.html(
        f'<div style="margin-top:3rem;display:flex;gap:8px;justify-content:center;align-items:cente'
            f'r;'
        f'padding:20px;border-radius:15px;background:{bg_style};{border_style}backdrop-filter:blur(10px);">'
        f'<p style="font-weight:600;color:{text_color};margin:0;font-size:1rem;'
        f"text-shadow:0 2px 10px rgba(0,0,0,0.4);font-family:'Outfit',sans-serif;\">Created by</p>"
        + _logo_img_tag(logo_b64)
        + "</div>"
    )


def footer_dashboard():
    logo_b64 = img_to_base64(BASE_DIR / "img" / "NKA.png")
    is_dark = is_dark_theme()

    bg_style = (
        "linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(15, 23, 42, 0.6) 100%)"
        if is_dark
        else "linear-gradient(135deg, rgba(255, 255, 255, 0.8) 0%, rgba(255, 255, 255, 0.6) 100%)"
    )
    border_style = "border:1px solid rgba(129, 140, 248, 0.2);" if is_dark else ""
    text_color = "#e2e8f0" if is_dark else "#334155"

    st.html(
        f'<div style="margin-top:3rem;display:flex;gap:8px;justify-content:center;align-items:cente'
            f'r;'
        f"padding:20px;border-radius:15px;background:{bg_style};{border_style}"
        f'box-shadow:0 4px 15px rgba(0,0,0,0.2);backdrop-filter:blur(10px);">'
        f'<p style="font-weight:700;color:{text_color};margin:0;font-size:1rem;'
        f"font-family:'Outfit',sans-serif;\">Created by</p>" + _logo_img_tag(logo_b64) + "</div>"
    )
