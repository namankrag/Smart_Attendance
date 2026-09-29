# 🎓 SmartClass – Smart Attendance System

> Making attendance faster using AI.

SmartClass is a web-based attendance management system built with **Python** and **Streamlit**. It replaces manual roll calls with AI-driven **face recognition** and **voice recognition**, and lets students join classes instantly through **QR codes / join links**. Teachers and students each get their own dashboard, and all data is stored securely in a **Supabase** backend.

---

## 📑 Table of Contents

1. [Features](#-features)
2. [Tech Stack](#-tech-stack)
3. [How It Works](#-how-it-works)
4. [Project Structure](#-project-structure)
5. [Installation & Setup](#-installation--setup)
6. [Configuration](#-configuration)
7. [Running the App](#-running-the-app)
8. [Usage Guide](#-usage-guide)
9. [Dev Container / Codespaces](#-dev-container--codespaces)
10. [Troubleshooting](#-troubleshooting)
11. [Future Improvements](#-future-improvements)
12. [Contributing](#-contributing)
13. [License](#-license)

---

## ✨ Features

### 🏠 Role-Based Access
- **Home screen** where users choose to continue as a **Teacher** or a **Student**.
- Separate **Teacher** and **Student** dashboards with session-based login state.
- Secure sign-up / login with **bcrypt-hashed passwords**.

### 🧑‍🏫 Teacher Features
- Create and manage **classes / subjects**.
- Take attendance using **AI face recognition** (from a photo or camera capture of the classroom).
- Take attendance using **voice recognition** (speaker identification via voice embeddings).
- Generate a unique **join code**, **shareable link**, and **QR code** so students can enrol in a class in one step.
- View and manage the list of enrolled students.
- View attendance records and reports for each class.

### 🧑‍🎓 Student Features
- Register with profile details and **face data** (and voice sample) for recognition.
- **Auto-enrol** into a class by opening a join link (`?join-code=XXXX`) or scanning the teacher's QR code.
- View enrolled subjects and personal **attendance history**.

### 🤖 AI / Biometric Features
- **Face recognition** using `dlib` + `face_recognition_models` to detect faces and compute face encodings.
- **Voice recognition** using `resemblyzer` (speaker embeddings) with `librosa` for audio processing.
- Encodings are compared against enrolled students to mark attendance automatically.

### 🔗 Join Links & QR Codes
- Deep-link support: opening the app with `?join-code=<code>` automatically switches to the student flow and triggers the **auto-enrol dialog** once the student is logged in.
- QR codes generated with **segno**.

### 🎨 UI / UX
- Clean **Streamlit** interface with a collapsed sidebar by default.
- Custom app title, favicon and header image.
- Hidden Streamlit deploy button, main menu and footer for a polished look.
- Transparent header that adapts to the page background.
- **Custom themed cursor** with separate colours for light mode (magenta) and dark mode (cyan).

### 🛠️ Compatibility
- Built-in `pkg_resources` shim so the app runs on **Python 3.14**, where `pkg_resources` has been removed (needed by `webrtcvad` and `face_recognition_models`).

---

## 🧰 Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.x |
| Web framework | [Streamlit](https://streamlit.io/) |
| Database / Backend | [Supabase](https://supabase.com/) |
| Face recognition | `dlib-bin`, `face_recognition_models` |
| Voice recognition | `resemblyzer`, `librosa` |
| ML utilities | `scikit-learn`, `numpy`, `pandas` |
| Authentication | `bcrypt` |
| QR code generation | `segno` |
| Image handling | `pillow` |

---

## ⚙️ How It Works

1. **Registration** – A student signs up and provides face (and voice) samples. Encodings/embeddings are computed and stored in Supabase.
2. **Class creation** – A teacher creates a class and receives a join code, link and QR code.
3. **Enrolment** – Students open the link or scan the QR code; after login they are auto-enrolled via the `auto_enroll` dialog.
4. **Attendance** – The teacher captures a classroom photo or voice input. The system detects faces / speakers, matches them against enrolled students, and marks them present.
5. **Reports** – Teachers and students can review attendance records from their dashboards.

---

## 📂 Project Structure

```
Smart_Attendance/
├── .devcontainer/        # Dev container / Codespaces configuration
├── img/                  # Images and icons (e.g. header.png favicon)
├── src/
│   ├── screen/           # Page-level screens
│   │   ├── home_screen.py
│   │   ├── teacher_screen.py
│   │   └── student_screen.py
│   └── components/       # Reusable UI components / dialogs
│       └── dialog_auto_enroll.py
├── app.py                # Application entry point
├── requirements.txt      # Python dependencies
├── .gitignore
└── README.md
```

> The `src/` folder also contains the supporting logic (database access, face/voice recognition helpers, etc.).

---

## 🚀 Installation & Setup

### Prerequisites
- Python 3.10 or newer
- `pip` and (recommended) `venv`
- A free [Supabase](https://supabase.com/) project
- A webcam / microphone (for capturing face and voice)
- On some systems, `cmake` and a C++ compiler may be required for `dlib`

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/namankrag/Smart_Attendance.git
cd Smart_Attendance

# 2. Create and activate a virtual environment
python -m venv venv
# macOS / Linux
source venv/bin/activate
# Windows
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

---

## 🔐 Configuration

The app uses Supabase as its backend. Create a `.streamlit/secrets.toml` file in the project root:

```toml
[supabase]
url = "YOUR_SUPABASE_URL"
key = "YOUR_SUPABASE_ANON_OR_SERVICE_KEY"
```

> ⚠️ Never commit your secrets. Make sure `.streamlit/secrets.toml` is listed in `.gitignore`.

Then create the required tables in your Supabase project (for example: `teachers`, `students`, `subjects`/`classes`, `enrollments`, `attendance`). Adjust names to match the queries used in `src/`.

---

## ▶️ Running the App

```bash
streamlit run app.py
```

The app opens at **http://localhost:8501**.

---

## 📖 Usage Guide

### As a Teacher
1. Open the app and choose **Teacher**.
2. Sign up / log in.
3. Create a class and share its **join code, link or QR code**.
4. Start an attendance session using face or voice recognition.
5. Review attendance reports.

### As a Student
1. Open the app and choose **Student** (or open your teacher's join link).
2. Sign up with your details and register your face (and voice).
3. Join a class using the code / link / QR.
4. Check your attendance history from your dashboard.

### Join Link Format
```
https://<your-app-url>/?join-code=<CLASS_CODE>
```

---

## 🐳 Dev Container / Codespaces

The repository ships with a `.devcontainer` configuration, so you can open it directly in **GitHub Codespaces** or **VS Code Dev Containers** for a ready-to-run environment.

---

## 🩺 Troubleshooting

| Problem | Solution |
|---|---|
| `dlib` fails to install | Install `cmake` and a C++ build toolchain, or use the prebuilt `dlib-bin` package. |
| `pkg_resources` not found | Already handled by the shim in `app.py`; also make sure `setuptools` is installed. |
| Supabase connection errors | Verify the URL / key in `secrets.toml` and your table names. |
| Camera or microphone not working | Allow browser permissions and use `localhost` or HTTPS. |
| Faces not recognised | Use good lighting, front-facing photos and higher-resolution images. |

---

## 🔮 Future Improvements

- Email / SMS notifications for low attendance
- Export attendance to CSV / PDF
- Admin dashboard and analytics charts
- Anti-spoofing / liveness detection
- Mobile-friendly PWA

---

## 🤝 Contributing

Contributions are welcome!

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m "Add your feature"`
4. Push to the branch: `git push origin feature/your-feature`
5. Open a Pull Request

---

## 📄 License

No license has been specified yet. Add a `LICENSE` file (e.g. MIT) to define how others may use this project.

---

## 👤 Author

**Naman** – [@namankrag](https://github.com/namankrag)
