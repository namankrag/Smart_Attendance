import streamlit as st

# Gradient presets  (start_color, end_color, icon)
THEMES = {
    "purple":  ("#667eea", "#764ba2", ""),
    "pink":    ("#f093fb", "#f5576c", ""),
    "teal":    ("#43e97b", "#38f9d7", ""),
    "orange":  ("#fa8231", "#f7b733", ""),
    "blue":    ("#4facfe", "#00f2fe", ""),
}

def dialog_banner(title: str, subtitle: str = "", theme: str = "purple"):
    c1, c2 = THEMES.get(theme, THEMES["purple"])[:2]
    icon   = THEMES.get(theme, THEMES["purple"])[2]
    sub_html = (
        f'<p style="margin:6px 0 0; font-size:0.92rem; opacity:0.88; '
        f'font-family:Outfit,sans-serif; font-weight:400;">{subtitle}</p>'
        if subtitle else ""
    )
    st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, {c1} 0%, {c2} 100%);
            margin: -1rem -1rem 1.4rem -1rem;
            padding: 1.6rem 1.8rem 1.4rem;
            border-radius: 1.8rem 1.8rem 0 0;
        ">
            <h2 style="
                margin: 0;
                color: white;
                font-family: 'Climate Crisis', sans-serif;
                font-size: 1.6rem;
                letter-spacing: 2px;
                -webkit-text-fill-color: white;
                line-height: 1.2;
            ">{icon} {title}</h2>
            {sub_html}
        </div>
    """, unsafe_allow_html=True)


def styled_badge(text: str, color: str = "#667eea") -> str:
    """Return an inline HTML badge span."""
    return (
        f'<span style="background:{color}22; color:{color}; '
        f'padding:3px 12px; border-radius:20px; font-weight:600; '
        f'font-size:0.88rem; border:1px solid {color}44;">{text}</span>'
    )
