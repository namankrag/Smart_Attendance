import streamlit as st

def style_bg_home():
    st.markdown("""
        <style>
            .stApp {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
            }

            /* White heading on the purple gradient home background */
            .stApp h1 {
                color: white !important;
                text-shadow: 0 4px 25px rgba(0, 0, 0, 0.25) !important;
            }

            /* Portal cards */
            .stApp div[data-testid="stColumn"] {
                background: rgba(255, 255, 255, 0.95) !important;
                padding: 2.2rem 2rem !important;
                border-radius: 2rem !important;
                display: flex !important;
                flex-direction: column !important;
                align-items: flex-start !important;
                box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25) !important;
                backdrop-filter: blur(10px) !important;
                transition: transform 0.3s ease, box-shadow 0.3s ease !important;
            }

            .stApp div[data-testid="stColumn"]:hover {
                transform: translateY(-6px) !important;
                box-shadow: 0 28px 70px rgba(0, 0, 0, 0.32) !important;
            }

            .stApp div[data-testid="stColumn"] > div:first-child {
                display: flex !important;
                flex-direction: column !important;
                height: 100% !important;
                width: 100% !important;
            }

            .stApp div[data-testid="stColumn"] img {
                height: 145px !important;
                width: auto !important;
                object-fit: contain !important;
            }
        </style>
        """, unsafe_allow_html=True)

def style_bg_dashboard():
    st.markdown("""
        <style>
            .stApp {
                background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%) !important;
            }
        </style>
        """, unsafe_allow_html = True)

def style_base_layout():
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Climate+Crisis:YEAR@1979&display=swap');
        @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@100..900&display=swap');

        /* Hide Top Bar of streamlit */
        # #MainMenu, footer, header {
        #     visibility: hidden;
        # }
        
        .block-container {
            padding-top: 1.5rem !important;    
        }

        h1 {
            font-family: 'Climate Crisis', sans-serif !important;
            font-size: 3.5rem !important;
            line-height: 1.1 !important;
            margin-bottom: 0rem !important;
            color: #1e293b !important;
            letter-spacing: 2px !important;
        }

        h2 {
            font-family: 'Climate Crisis', sans-serif !important;
            font-size: 2rem !important;
            line-height: 0.9 !important;
            margin-bottom: 0rem !important;
            color: #1e293b !important;
        }
        
        h3, h4, p {
            font-family: 'Outfit', sans-serif;    
        }

        /* Enhanced Buttons */
        button {
            border-radius: 1rem !important;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
            color: white !important;
            padding: 12px 24px !important;
            border: none !important;
            font-weight: 600 !important;
            font-family: 'Outfit', sans-serif !important;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4) !important;
            transition: all 0.3s ease !important;
        }

        button:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6) !important;
        }

        button[kind = "secondary"] {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%) !important;
            box-shadow: 0 4px 15px rgba(245, 87, 108, 0.4) !important;
        }

        button[kind = "secondary"]:hover {
            box-shadow: 0 6px 20px rgba(245, 87, 108, 0.6) !important;
        }

        button[kind = "tertiary"] {
            background: linear-gradient(135deg, #434343 0%, #000000 100%) !important;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.3) !important;
        }

        button[kind = "tertiary"]:hover {
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.5) !important;
        }

        /* Enhanced Input Fields */
        input[type="text"], input[type="password"], textarea {
            border-radius: 0.75rem !important;
            border: 2px solid #e0e7ff !important;
            padding: 12px 16px !important;
            font-family: 'Outfit', sans-serif !important;
            transition: all 0.3s ease !important;
            background: white !important;
            color: #1e293b !important;
        }

        input[type="text"]:focus, input[type="password"]:focus, textarea:focus {
            border-color: #667eea !important;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1) !important;
            outline: none !important;
            color: #1e293b !important;
        }

        input[type="text"]::placeholder, input[type="password"]::placeholder, textarea::placeholder {
            color: #94a3b8 !important;
            opacity: 1 !important;
        }

        /* ── Dialog / Modal ─────────────────────────────────────────── */
        div[data-testid="stDialog"] > div[role="dialog"] {
            border-radius: 1.8rem !important;
            border: none !important;
            overflow: hidden !important;
            box-shadow:
                0 30px 80px rgba(102, 126, 234, 0.35),
                0 0 0 1px rgba(102, 126, 234, 0.1) !important;
            animation: dialogPop 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) !important;
        }

        @keyframes dialogPop {
            from { opacity: 0; transform: scale(0.85) translateY(20px); }
            to   { opacity: 1; transform: scale(1)    translateY(0);    }
        }

        /* Dialog inner padding */
        div[data-testid="stDialog"] section {
            padding: 0 !important;
        }

        /* Enhanced Containers */
        div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlock"] {
            border-radius: 1rem !important;
        }

        div[data-testid="column"] {
            background: transparent !important;
        }

        /* Enhanced Dividers */
        hr {
            margin: 2rem 0 !important;
            border: none !important;
            height: 2px !important;
            background: linear-gradient(90deg, transparent, #e0e7ff, transparent) !important;
        }

        /* Animated Camera Input */
        div[data-testid="stCameraInput"] {
            border-radius: 1rem !important;
            overflow: visible !important;
            border: none !important;
            position: relative !important;
        }

        div[data-testid="stCameraInput"]::before {
            content: '' !important;
            position: absolute !important;
            inset: -3px !important;
            border-radius: 1.2rem !important;
            padding: 3px !important;
            background: linear-gradient(
                var(--angle, 0deg),
                #667eea, #a78bfa, #f093fb, #f5576c, #667eea
            ) !important;
            -webkit-mask:
                linear-gradient(#fff 0 0) content-box,
                linear-gradient(#fff 0 0) !important;
            -webkit-mask-composite: xor !important;
            mask-composite: exclude !important;
            animation: spin-border 3s linear infinite !important;
            box-shadow: 0 0 18px rgba(102, 126, 234, 0.6) !important;
            z-index: 10 !important;
            pointer-events: none !important;
        }

        div[data-testid="stCameraInput"]::after {
            content: '' !important;
            position: absolute !important;
            inset: -3px !important;
            border-radius: 1.2rem !important;
            background: linear-gradient(
                var(--angle, 0deg),
                #667eea, #a78bfa, #f093fb, #f5576c, #667eea
            ) !important;
            filter: blur(12px) !important;
            opacity: 0.5 !important;
            animation: spin-border 3s linear infinite !important;
            z-index: 0 !important;
            pointer-events: none !important;
        }

        @property --angle {
            syntax: '<angle>' !important;
            initial-value: 0deg !important;
            inherits: false !important;
        }

        @keyframes spin-border {
            0%   { --angle: 0deg;   }
            100% { --angle: 360deg; }
        }

        /* Corner scanner dots */
        div[data-testid="stCameraInput"] video,
        div[data-testid="stCameraInput"] img {
            border-radius: 0.9rem !important;
            position: relative !important;
            z-index: 1 !important;
        }

        /* Enhanced Audio Input */
        div[data-testid="stAudioInput"] {
            border-radius: 1rem !important;
            border: 2px solid #e0e7ff !important;
            padding: 1rem !important;
            background: white !important;
        }

        /* Enhanced File Uploader */
        div[data-testid="stFileUploader"] {
            border-radius: 1rem !important;
            border: 2px dashed #e0e7ff !important;
            background: rgba(102, 126, 234, 0.02) !important;
            transition: all 0.3s ease !important;
        }

        div[data-testid="stFileUploader"]:hover {
            border-color: #667eea !important;
            background: rgba(102, 126, 234, 0.05) !important;
        }

        /* Enhanced Dataframe */
        div[data-testid="stDataFrame"] {
            border-radius: 1rem !important;
            overflow: hidden !important;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1) !important;
        }

        /* Enhanced Toast Messages */
        div[data-testid="stToast"] {
            border-radius: 1rem !important;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15) !important;
            backdrop-filter: blur(10px) !important;
        }

        /* Spinner styling */
        div[data-testid="stSpinner"] > div {
            border-color: #667eea transparent transparent transparent !important;
        }

        /* Select box styling */
        div[data-baseweb="select"] {
            border-radius: 0.75rem !important;
        }

        div[data-baseweb="select"] > div {
            border-radius: 0.75rem !important;
            border: 2px solid #e0e7ff !important;
            background: white !important;
            color: #1e293b !important;
        }

        div[data-baseweb="select"] * {
            color: #1e293b !important;
        }

        div[data-baseweb="select"]:focus-within > div {
            border-color: #667eea !important;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1) !important;
        }
        </style>  
        """ ,unsafe_allow_html=True)