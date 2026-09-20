import streamlit as st
from src.ui.base_layout import is_dark_theme

def subject_card(name, code, section, stats=None, footer_callback=None):
    dark = is_dark_theme()

    bg_style = "linear-gradient(135deg, #1e293b 0%, #0f172a 100%)" if dark else "linear-gradient(135deg, #ffffff 0%, #f8f9ff 100%)"
    border_left_col = "#818cf8" if dark else "#667eea"
    card_border = "border:1px solid rgba(129, 140, 248, 0.2);" if dark else ""
    shadow_default = "0 8px 30px rgba(0, 0, 0, 0.4)" if dark else "0 8px 30px rgba(102, 126, 234, 0.15)"
    shadow_hover   = "0 12px 40px rgba(129, 140, 248, 0.3)" if dark else "0 12px 40px rgba(102, 126, 234, 0.25)"
    
    title_gradient = "linear-gradient(135deg, #818cf8 0%, #c084fc 100%)" if dark else "linear-gradient(135deg, #667eea 0%, #764ba2 100%)"
    sub_color = "#94a3b8" if dark else "#64748b"
    
    code_bg = "linear-gradient(135deg, #312e81 0%, #4338ca 100%)" if dark else "linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%)"
    code_color = "#a5b4fc" if dark else "#4338ca"
    section_color = "#cbd5e1" if dark else "#334155"

    html = (
        f'<div style="background:{bg_style};border-left:6px solid {border_left_col};{card_border}'
        f'padding:24px 28px;border-radius:20px;box-shadow:{shadow_default};margin-bottom:20px;'
        f'transition:all 0.3s ease;cursor:pointer;" '
        f'onmouseover="this.style.transform=\'translateY(-5px)\'; this.style.boxShadow=\'{shadow_hover}\'" '
        f'onmouseout="this.style.transform=\'translateY(0)\'; this.style.boxShadow=\'{shadow_default}\'">'
        f'<h3 style="margin:0 0 12px 0;font-size:1.35rem;font-weight:700;background:{title_gradient};'
        f'-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;font-family:\'Outfit\',sans-serif;">{name}</h3>'
        f'<p style="color:{sub_color};margin:0 0 16px 0;font-size:0.98rem;line-height:1.6;font-family:\'Outfit\',sans-serif;">'
        f'Code : <span style="background:{code_bg};color:{code_color};padding:4px 14px;border-radius:8px;'
        f'font-weight:600;box-shadow:0 2px 8px rgba(0,0,0,0.2);">{code}</span>'
        f'&nbsp;&nbsp;|&nbsp;&nbsp; Section : <span style="font-weight:600;color:{section_color};">{section}</span>'
        f'</p>'
    )

    if stats:
        html += '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:16px;">'
        pill_bg_default = "linear-gradient(135deg, #334155 0%, #1e293b 100%)" if dark else "linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%)"
        pill_bg_hover   = "linear-gradient(135deg, #312e81 0%, #4338ca 100%)" if dark else "linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%)"
        pill_text_col   = "#cbd5e1" if dark else "#334155"
        val_text_col    = "#f8fafc" if dark else "#1e293b"

        for icon, label, value in stats:
            pill = (
                f'<div style="background:{pill_bg_default};padding:8px 18px;border-radius:12px;'
                f'font-size:0.92rem;color:{pill_text_col};font-weight:500;box-shadow:0 2px 8px rgba(0,0,0,0.15);'
                f'transition:all 0.2s ease;font-family:\'Outfit\',sans-serif;" '
                f'onmouseover="this.style.background=\'{pill_bg_hover}\'; this.style.transform=\'scale(1.05)\'" '
                f'onmouseout="this.style.background=\'{pill_bg_default}\'; this.style.transform=\'scale(1)\'">'
                f'{icon} <b style="color:{val_text_col};">{value}</b> {label}'
                f'</div>'
            )
            html += pill
        html += '</div>'

    html += '</div>'

    st.html(html)

    if footer_callback:
        footer_callback()
