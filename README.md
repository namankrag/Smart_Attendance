# 🎓 SmartClass – Smart Attendance System

> Making attendance faster using AI.

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://smartclass-main.streamlit.app/)
[![Live Demo](https://img.shields.io/badge/Live%20Demo-smartclass--main.streamlit.app-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://smartclass-main.streamlit.app/)

🚀 **Live App:** [https://smartclass-main.streamlit.app/](https://smartclass-main.streamlit.app/)

SmartClass is a web-based attendance management system built with **Python** and **Streamlit**. It replaces manual roll calls with AI-driven **face recognition** and **voice recognition**, protects face login with **passive anti-spoofing**, and lets students join classes instantly through **QR codes / join links**. Teachers and students each get their own dashboard, and all data is stored in a **Supabase** backend.

---

## 📑 Table of Contents

1. [Features](#-features)
2. [Tech Stack](#-tech-stack)
3. [How It Works](#-how-it-works)
4. [Project Structure](#-project-structure)
5. [Installation & Setup](#-installation--setup)
6. [Configuration](#-configuration)
7. [Database Schema](#-database-schema)
8. [Running the App](#-running-the-app)
9. [Usage Guide](#-usage-guide)
10. [Dev Container / Codespaces](#-dev-container--codespaces)
11. [Troubleshooting](#-troubleshooting)
12. [Future Improvements](#-future-improvements)
13. [Contributing](#-contributing)
14. [License](#-license)

---

## ✨ Features

### 🏠 Role-Based Access
- **Home screen** where users choose to continue as a **Teacher** or a **Student**.
- Separate **Teacher** and **Student** dashboards with session-based login state and a sidebar for navigation.
- Teacher accounts use a username + **bcrypt-hashed password** (minimum 6 characters).

### 🧑‍🏫 Teacher Features
- **Manage subjects**: create subjects (code, name, section) and delete them (cascades to enrollments and attendance logs).
- **Take attendance by face**: upload or capture multiple classroom photos, then analyze them in one batch.
- **Take attendance by voice**: record classroom audio and identify each speaker.
- **Review before saving**: a report dialog shows present/absent counts and attendance percentage before anything is written to the database.
- **Share a class**: every subject has a join code, a shareable link and a colour-themed **QR code**.
- **Attendance records**: session-wise cards with attendance percentage, summary tiles (sessions, total logs, present entries, average attendance), and a per-session drill-down.
- **Manual corrections**: from a session's detail view, flip any student between **Present** and **Absent**.

### 🧑‍🎓 Student Features
- **FaceID login** with live anti-spoofing checks, or **Student ID + PIN** login.
- **Self-registration** on first face scan: name, 4–6 character PIN, and an optional voice sample.
- **Add extra face scans** (glasses, hairstyle, lighting) from the sidebar. Up to **5** face embeddings are kept per student.
- **Auto-enrol** by opening a join link (`?join-code=XXXX`) or scanning the teacher's QR code, or enter a subject code manually.
- View enrolled subjects, total classes, and a timestamped **attended / absent history** for each subject.
- Unenroll from a subject at any time.

### 🤖 AI / Biometric Features
- **Face recognition** with `dlib` (HOG detector, 68-point landmarks, ResNet encoder via `face_recognition_models`) producing L2-normalised 128-D descriptors.
  - Single-face login uses a fast upright scan.
  - Classroom photos add **micro-tilt passes (±15°)** to catch tilted heads, with duplicate suppression by descriptor distance.
  - Matching uses a strict Euclidean threshold (default `0.38`) and is **scoped to students enrolled in the selected subject**, which avoids false matches against students from other classes.
  - Gallery embeddings are cached for 5 minutes and refreshed when a profile is registered or updated.
- **Passive liveness / anti-spoofing** on face login and extra-scan enrolment. It rejects:
  - phone/tablet bezels around the face,
  - screen glare and over-exposed regions,
  - Moiré patterns from digital screens (FFT frequency-energy analysis).
- **Voice recognition** with `resemblyzer` (256-D speaker embeddings) and `librosa`. Classroom audio is split into speech segments and each is matched by cosine similarity (default threshold `0.65`) against enrolled students' voice prints.

### 🔗 Join Links & QR Codes
- Deep-link support: opening the app with `?join-code=<code>` switches to the student flow and shows the **auto-enrol dialog** once the student is logged in.
- QR codes are generated with **segno**. Set `APP_URL` in secrets to control the base URL embedded in links and QR codes.

### 🎨 UI / UX
- **Light and dark themes** with a toggle on every screen.
- Animated gradient buttons, themed dialogs with banners, and responsive/mobile-friendly styling.
- Collapsed sidebar by default, custom page title and favicon.
- Streamlit's deploy button, main menu and footer are hidden for a polished look.

### 🛠️ Reliability & Compatibility
- Supabase calls are wrapped in an **exponential-backoff retry** decorator for transient network errors.
- Built-in `pkg_resources` shim so the app still runs on newer Python versions where `pkg_resources` is no longer bundled (needed by `face_recognition_models`).

---

## 🧰 Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| Web framework | [Streamlit](https://streamlit.io/) |
| Database / Backend | [Supabase](https://supabase.com/) |
| Face recognition | `dlib-bin`, `face_recognition_models`, `scipy` (distance matrix) |
| Voice recognition | `resemblyzer`, `librosa` |
| Data / numerics | `numpy`, `pandas` |
| Authentication | `bcrypt` |
| QR code generation | `segno` |
| Image handling | `pillow` |

---

## ⚙️ How It Works

1. **Registration**: a student scans their face (passing the liveness check) and optionally records a voice sample. The 128-D face embedding and 256-D voice embedding are stored in Supabase.
2. **Class creation**: a teacher creates a subject and gets a join code, link and QR code.
3. **Enrolment**: students enter the code, open the link or scan the QR code; the `auto_enroll` dialog confirms and enrols them.
4. **Attendance**: the teacher adds classroom photos (face scan) or records audio (voice scan). The system detects faces/speakers, matches them against **only the students enrolled in that subject**, and builds a report.
5. **Confirmation**: the teacher reviews the report and saves it. Each session is stored as one `attendance_logs` row per enrolled student, sharing a timestamp.
6. **Reports**: teachers see per-session breakdowns and can correct entries; students see their attended and absent sessions per subject. Absences for sessions held before a student enrolled are computed at view time rather than stored.

---

## 📂 Project Structure

```
Smart_Attendance/
├── .devcontainer/            # Dev container / Codespaces configuration
├── img/                      # header.png, NKA.png, student.png, teacher.png
├── src/
│   ├── database/
│   │   ├── config.py         # Supabase client, retry decorator
│   │   └── db.py             # All database queries and bcrypt helpers
│   ├── pipelines/
│   │   ├── face_pipeline.py  # Face detection, embeddings, liveness, matching
│   │   └── voice_pipeline.py # Voice embeddings and speaker identification
│   ├── screen/
│   │   ├── home_screen.py
│   │   ├── teacher_screen.py
│   │   └── student_screen.py
│   ├── components/           # Reusable UI components and dialogs
│   │   ├── header.py / footer.py / subject_card.py / dialog_utils.py
│   │   ├── dialog_create_subject.py / dialog_delete_subject.py
│   │   ├── dialog_share_subject.py / dialog_auto_enroll.py / dialog_enroll.py
│   │   ├── dialog_add_photo.py / dialog_attend_result.py / dialog_voice_attend.py
│   │   └── dialog_session_detail.py / dialog_student_attendance.py
│   └── ui/
│       └── base_layout.py    # Themes, global CSS, backgrounds
├── app.py                    # Application entry point and routing
├── requirements.txt          # Python dependencies
├── .gitignore
└── README.md
```

---

## 🚀 Installation & Setup

### Prerequisites
- Python 3.10 or newer
- `pip` and (recommended) `venv`
- A free [Supabase](https://supabase.com/) project
- A webcam / microphone (for capturing face and voice)
- On some systems, `cmake` and a C++ compiler may be required for `dlib` (the prebuilt `dlib-bin` package usually avoids this)

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

Create a `.streamlit/secrets.toml` file in the project root. Keys are **top-level** (not nested in a section):

```toml
SUPABASE_URL = "YOUR_SUPABASE_URL"
SUPABASE_KEY = "YOUR_SUPABASE_ANON_OR_SERVICE_KEY"

# Optional: base URL used in join links and QR codes
APP_URL = "https://your-app-url.streamlit.app"
```

> ⚠️ Never commit your secrets. `.streamlit/` is already listed in `.gitignore`.

If `APP_URL` is not set, share links default to `https://smartclass-main.streamlit.app`.

---

## 🗄️ Database Schema

Create these tables in Supabase (column names must match the queries in `src/database/db.py`):

| Table | Columns |
|---|---|
| `teachers` | `teacher_id` (PK), `username` (unique), `password` (bcrypt hash), `name` |
| `students` | `student_id` (PK), `name`, `face_embedding` (JSON), `voice_embedding` (JSON), `pin_hash` (text, optional) |
| `subjects` | `subject_id` (PK), `subject_code` (unique), `name`, `section`, `teacher_id` (FK → teachers) |
| `subject_students` | `id` (PK), `student_id` (FK → students), `subject_id` (FK → subjects) |
| `attendance_logs` | `id` (PK), `student_id` (FK → students), `subject_id` (FK → subjects), `timestamp`, `is_present` (bool) |

Notes:
- `face_embedding` stores either a single 128-float list or a list of up to 5 such lists.
- `voice_embedding` stores a 256-float list.
- Foreign keys from `attendance_logs` and `subject_students` to `students` and `subjects` are needed for the joined selects (e.g. `students(name, student_id)`) to work.

---

## ▶️ Running the App

```bash
streamlit run app.py
```

The app opens at **http://localhost:8501**.

---

## 📖 Usage Guide

### As a Teacher
1. Open the app and choose **Teacher Portal**.
2. Register a new account or sign in.
3. Go to **Manage Subjects** → **Create New Subject**, then use **Share Code** to get the join code, link and QR code.
4. Go to **Take Attendance**, pick a subject, and click **Add Photos** (upload or camera). Then click **Analyze Faces**, or use **Voice Attendance**.
5. Review the report and click **Save and Confirm**.
6. Open **Attendance Records** to browse sessions and fix individual entries if needed.

### As a Student
1. Open the app and choose **Student Portal** (or open your teacher's join link).
2. Use **FaceID Scanner** to sign in. If your face isn't recognised, you'll be offered the registration form (name, PIN, optional voice sample). Alternatively sign in with **Student ID & PIN**.
3. Join a class using **Enroll in subject** or the join link / QR code.
4. Check your **Attended** and **Absent** history for each subject, and add extra face scans from the sidebar to improve recognition.

### Join Link Format
```
https://smartclass-main.streamlit.app/?join-code=<CLASS_CODE>
```

---

## 🐳 Dev Container / Codespaces

The repository ships with a `.devcontainer` configuration (Python 3.11), so you can open it directly in **GitHub Codespaces** or **VS Code Dev Containers** for a ready-to-run environment. The app starts automatically on port 8501.

---

## 🩺 Troubleshooting

| Problem | Solution |
|---|---|
| `dlib` fails to install | Install `cmake` and a C++ build toolchain, or use the prebuilt `dlib-bin` package. |
| `pkg_resources` not found | Already handled by the shim in `app.py`; also make sure `setuptools` is installed. |
| `KeyError: 'SUPABASE_URL'` | Add `SUPABASE_URL` and `SUPABASE_KEY` as top-level keys in `.streamlit/secrets.toml`. |
| Supabase connection errors | Verify the URL / key and the table and column names above. |
| Camera or microphone not working | Allow browser permissions and use `localhost` or HTTPS. |
| "Anti-Spoofing Alert" on a real face | Face the camera directly in even, natural lighting; avoid strong backlight, glare, and dark surroundings. |
| Faces not recognised | Use good lighting, front-facing photos and higher-resolution images; add extra face scans from the student sidebar. |
| Wrong student marked present | Lower the distance threshold (default `0.38`) in `face_pipeline.py` / `teacher_screen.py`, or fix the entry in **Attendance Records**. |

---

## 🔮 Future Improvements

- Email / SMS notifications for low attendance
- Export attendance to CSV / PDF
- Admin dashboard and richer analytics charts
- Active liveness challenges (blink / head turn) on top of the current passive checks
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