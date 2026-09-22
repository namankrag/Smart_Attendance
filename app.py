import sys
import types

# Several older packages (webrtcvad, face_recognition_models) use pkg_resources
# which was removed in Python 3.14. Inject a minimal shim before any local
# imports trigger those packages.
if "pkg_resources" not in sys.modules:
    _pkg_shim = types.ModuleType("pkg_resources")
    _pkg_shim.resource_filename = lambda package_or_requirement, resource_name: resource_name
    _pkg_shim.require = lambda *a, **kw: []
    _pkg_shim.get_distribution = lambda name: type("D", (), {"version": "0.0.0"})()
    sys.modules["pkg_resources"] = _pkg_shim

import streamlit as st
from pathlib import Path

from src.screen.home_screen import home_screen
from src.screen.teacher_screen import teacher_screen
from src.screen.student_screen import student_screen
from src.components.dialog_auto_enroll import auto_enroll

BASE_DIR = Path(__file__).parent.resolve()

def main():
    st.set_page_config(
        page_title = 'SmartClass - Making Attendance faster using AI',
        page_icon = str(BASE_DIR / "img" / "header.png"),
        initial_sidebar_state = "collapsed",
    )

    # Minimal CSS — only hide deploy button and menu, make header transparent
    st.markdown("""
        <style>
            [data-testid="stAppDeployButton"] { display: none !important; }
            #MainMenu { visibility: hidden !important; }
            footer { visibility: hidden !important; }
            
            /* Make header transparent so it adapts to page background */
            [data-testid="stHeader"] {
                background: transparent !important;
                background-color: transparent !important;
            }
            
            /* Custom cursor - Light mode (magenta/purple) */
            * {
                cursor: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M3 3L10.07 19.97L12.58 12.58L19.97 10.07L3 3Z" fill="%23FF00FF" stroke="%23CC00CC" stroke-width="1.5" stroke-linejoin="round"/></svg>'), auto !important;
            }
            
            a, button, [role="button"], input[type="submit"], input[type="button"], [data-testid*="button"] {
                cursor: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M3 3L10.07 19.97L12.58 12.58L19.97 10.07L3 3Z" fill="%23FF66FF" stroke="%23FF00CC" stroke-width="2" stroke-linejoin="round"/></svg>'), pointer !important;
            }
            
            /* Custom cursor - Dark mode (cyan/blue) - overrides light mode when background is dark */
            [data-testid="stAppViewContainer"][style*="rgb(14, 17, 23)"] *,
            [data-testid="stAppViewContainer"][style*="rgb(38, 39, 48)"] * {
                cursor: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M3 3L10.07 19.97L12.58 12.58L19.97 10.07L3 3Z" fill="%2300D9FF" stroke="%230099CC" stroke-width="1.5" stroke-linejoin="round"/></svg>'), auto !important;
            }
            
            [data-testid="stAppViewContainer"][style*="rgb(14, 17, 23)"] a,
            [data-testid="stAppViewContainer"][style*="rgb(14, 17, 23)"] button,
            [data-testid="stAppViewContainer"][style*="rgb(14, 17, 23)"] [role="button"],
            [data-testid="stAppViewContainer"][style*="rgb(14, 17, 23)"] input[type="submit"],
            [data-testid="stAppViewContainer"][style*="rgb(14, 17, 23)"] input[type="button"],
            [data-testid="stAppViewContainer"][style*="rgb(14, 17, 23)"] [data-testid*="button"],
            [data-testid="stAppViewContainer"][style*="rgb(38, 39, 48)"] a,
            [data-testid="stAppViewContainer"][style*="rgb(38, 39, 48)"] button,
            [data-testid="stAppViewContainer"][style*="rgb(38, 39, 48)"] [role="button"],
            [data-testid="stAppViewContainer"][style*="rgb(38, 39, 48)"] input[type="submit"],
            [data-testid="stAppViewContainer"][style*="rgb(38, 39, 48)"] input[type="button"],
            [data-testid="stAppViewContainer"][style*="rgb(38, 39, 48)"] [data-testid*="button"] {
                cursor: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M3 3L10.07 19.97L12.58 12.58L19.97 10.07L3 3Z" fill="%2300FFFF" stroke="%2300CCFF" stroke-width="2" stroke-linejoin="round"/></svg>'), pointer !important;
            }
        </style>
    """, unsafe_allow_html=True)

    if 'login_type' not in st.session_state:
        st.session_state['login_type'] = None

    match st.session_state['login_type']:
        case 'teacher':
            teacher_screen()
        case 'student':
            student_screen()
        case None:
            home_screen()

    join_code = st.query_params.get('join-code')
    if join_code:
        if st.session_state.login_type != 'student':
            st.session_state.login_type = 'student'
            st.rerun()
        if st.session_state.get('is_logged_in') and st.session_state.get('user_role') == 'student':
            auto_enroll(join_code)

main()
