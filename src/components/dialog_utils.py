"""Shared dialog banner (Phase 1 hygiene).

Phase 1: ``title`` and ``subtitle`` are HTML-escaped HERE, at the
single choke point — callers pass raw strings and must NOT pre-escape
(escaping twice would render ``&amp;lt;`` literally). This closes the
gap where user-controlled subject/student names flowed into the banner
markup unescaped (Phase 0 audit 40). Colours come from a fixed preset
table, never from user input.
"""

import html

import streamlit as st

# Gradient presets  (start_color, end_color, icon)
THEMES = {
    "purple": ("#4f46e5", "#6366f1", ""),
    "pink": ("#db2777", "#f43f5e", ""),
    "teal": ("#0f766e", "#14b8a6", ""),
    "orange": ("#c2410c", "#f59e0b", ""),
    "blue": ("#0369a1", "#0ea5e9", ""),
}


def dialog_banner(title: str, subtitle: str = "", theme: str = "purple"):
    """Render the gradient dialog banner with escaped text.

    ``title`` / ``subtitle`` are escaped with ``html.escape`` here so
    no caller can inject markup via a subject or student name.
    """
    title = html.escape(str(title))
    subtitle = html.escape(str(subtitle)) if subtitle else ""
    c1, c2 = THEMES.get(theme, THEMES["purple"])[:2]
    icon = THEMES.get(theme, THEMES["purple"])[2]
    subtitle_color = {
        "purple": "#eef2ff",
        "pink": "#fff1f2",
        "teal": "#ecfeff",
        "orange": "#fff7ed",
        "blue": "#eff6ff",
    }.get(theme, "#ffffff")
    sub_html = (
        f'<p style="margin:7px 0 0; font-size:.95rem; opacity:1; color:{subtitle_color}; '
        f'-webkit-text-fill-color:{subtitle_color}; font-family:DM Sans,sans-serif; font-weight:700'
            f';">{subtitle}</p>'
        if subtitle
        else ""
    )
    st.markdown(
        f"""
        <div class="dialog-banner" style="
            background: linear-gradient(135deg, {c1} 0%, {c2} 100%);
            margin: -1rem -1rem 1.35rem -1rem;
            padding: 1.35rem 1.5rem 1.2rem;
            border-radius: 1.1rem 1.1rem 0 0;
        ">
            <h2 style="
                margin: 0;
                color: white;
                font-family: 'Manrope', sans-serif;
                font-size: 1.35rem;
                letter-spacing: -.03em;
                -webkit-text-fill-color: white;
                line-height: 1.2;
            ">{icon} {title}</h2>
            {sub_html}
        </div>
    """,
        unsafe_allow_html=True,
    )
