import streamlit as st

def subject_card(name, code, section, stats=None, footer_callback=None):
    html = f"""
        <div style="background: white; border-left: 6px solid #EB459E; padding: 20px 25px; border-radius: 16px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); margin-bottom: 16px;">
            <h3 style="margin: 0 0 10px 0; color: #1e293b; font-size: 1.2rem; font-weight: 700;">{name}</h3>
            <p style="color: #64748b; margin: 0 0 12px 0; font-size: 0.95rem;">
                Code : <span style="background: #E0E3FF; color: #5865F2; padding: 2px 10px; border-radius: 6px; font-weight: 600;">{code}</span>
                &nbsp;|&nbsp; Section : {section}
            </p>
    """

    if stats:
        html += '<div style="display: flex; gap: 10px; flex-wrap: wrap;">'
        for icon, label, value in stats:
            html += (
                f'<div style="background: #f1f5f9; padding: 5px 14px; border-radius: 20px; '
                f'font-size: 0.88rem; color: #334155;">{icon} <b>{value}</b> {label}</div>'
            )
        html += "</div>"

    html += "</div>"

    st.markdown(html, unsafe_allow_html=True)

    if footer_callback:
        footer_callback()
