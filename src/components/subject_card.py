import streamlit as st

def subject_card(name, code, section, stats=None, footer_callback=None):
    html = f"""
        <div style="
            background: linear-gradient(135deg, #ffffff 0%, #f8f9ff 100%);
            border-left: 6px solid #667eea;
            padding: 24px 28px;
            border-radius: 20px;
            box-shadow: 0 8px 30px rgba(102, 126, 234, 0.15);
            margin-bottom: 20px;
            transition: all 0.3s ease;
            cursor: pointer;
        " onmouseover="this.style.transform='translateY(-5px)'; this.style.boxShadow='0 12px 40px rgba(102, 126, 234, 0.25)'" 
           onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 8px 30px rgba(102, 126, 234, 0.15)'">
            <h3 style="
                margin: 0 0 12px 0;
                color: #1e293b;
                font-size: 1.35rem;
                font-weight: 700;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                background-clip: text;
            ">{name}</h3>
            <p style="
                color: #64748b;
                margin: 0 0 16px 0;
                font-size: 0.98rem;
                line-height: 1.6;
            ">
                Code : <span style="
                    background: linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%);
                    color: #4338ca;
                    padding: 4px 14px;
                    border-radius: 8px;
                    font-weight: 600;
                    box-shadow: 0 2px 8px rgba(67, 56, 202, 0.1);
                ">{code}</span>
                &nbsp;&nbsp;|&nbsp;&nbsp; Section : <span style="
                    font-weight: 600;
                    color: #334155;
                ">{section}</span>
            </p>
    """

    if stats:
        html += '<div style="display: flex; gap: 12px; flex-wrap: wrap; margin-top: 16px;">'
        for icon, label, value in stats:
            pill = (
                '<div style="'
                'background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%);'
                'padding: 8px 18px;'
                'border-radius: 12px;'
                'font-size: 0.92rem;'
                'color: #334155;'
                'font-weight: 500;'
                'box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);'
                'transition: all 0.2s ease;'
                '" onmouseover="this.style.background=\'linear-gradient(135deg, #e0e7ff 0%, #c7d2fe 100%)\'; this.style.transform=\'scale(1.05)\'"'
                '   onmouseout="this.style.background=\'linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%)\'; this.style.transform=\'scale(1)\'">'
                f'{icon} <b style="color: #1e293b;">{value}</b> {label}'
                '</div>'
            )
            html += pill
        html += "</div>"

    html += "</div>"

    st.markdown(html, unsafe_allow_html=True)

    if footer_callback:
        footer_callback()
