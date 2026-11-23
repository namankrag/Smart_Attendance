# 🎓 SmartClass – Smart Attendance System

> Making attendance faster using AI.

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://smartclass-main.streamlit.app/)
[![Live Demo](https://img.shields.io/badge/Live%20Demo-smartclass--main.streamlit.app-FF4B4B?style=flat&logo=streamlit&logoColor=white)](https://smartclass-main.streamlit.app/)

🚀 **Live App:** [https://smartclass-main.streamlit.app/](https://smartclass-main.streamlit.app/)

SmartClass is a web-based attendance management system built with **Python** and **Streamlit**. It replaces manual roll calls with AI-driven **face recognition** and **voice recognition**, screens face login with **heuristic liveness checks** (see [Honest Threat Model & Limitations](#-honest-threat-model--limitations) — these are not presentation-attack detection), and lets students join classes instantly through **QR codes / join links**. Teachers and students each get their own dashboard, and all data is stored in a **Supabase** backend.

---

## 📑 Table of Contents

1. [Features](#-features)
2. [Tech Stack](#-tech-stack)
3. [How It Works](#-how-it-works)
4. [Architecture](#-architecture)
5. [Project Structure](#-project-structure)
6. [Installation & Setup](#-installation--setup)
7. [Configuration](#-configuration)
8. [Deployment](#-deployment)
9. [Database Schema](#-database-schema)
10. [Running the App](#-running-the-app)
11. [Usage Guide](#-usage-guide)
12. [Privacy & Legal (DPDP / GDPR)](#-privacy--legal-dpdp--gdpr)
13. [Dev Container / Codespaces](#-dev-container--codespaces)
14. [Troubleshooting](#-troubleshooting)
15. [Honest Threat Model & Limitations](#-honest-threat-model--limitations)
16. [Future Improvements](#-future-improvements)
17. [Contributing](#-contributing)
18. [License](#-license)

---

## ✨ Features

### 🏠 Role-Based Access
- **Home screen** where users choose to continue as a **Teacher** or a **Student**.
- Separate **Teacher** and **Student** dashboards with session-based login state and a sidebar for navigation.
- Teacher accounts use a username + **Argon2id-hashed password** (minimum 6 characters; legacy bcrypt hashes are re-hashed on login).

### 🧑‍🏫 Teacher Features
- **Manage subjects**: create subjects (code, name, section) and delete them (cascades to enrollments and attendance logs).
- **Take attendance by face**: upload or capture multiple classroom photos, then analyze them in one batch.
- **Take attendance by voice**: record classroom audio and identify each speaker.
- **Review before saving**: a report dialog shows present/absent counts and attendance percentage before anything is written to the database.
- **Share a class**: every subject has a join code, a shareable link and a colour-themed **QR code**.
- **Attendance records**: session-wise cards with attendance percentage, summary tiles (sessions, total logs, present entries, average attendance), and a per-session drill-down.
- **Manual corrections**: from a session's detail view, flip any student between **Present** and **Absent**.

### 🧑‍🎓 Student Features
- **FaceID login** with heuristic liveness screening, or **Student ID + PIN** login.
- **Non-biometric fallback:** a student never has to use face or voice — Student ID + PIN login and teacher manual marking work with no penalty and no difference in the attendance record (GDPR Art. 9 / AEPD guidance; see [Privacy](#-privacy--legal-dpdp--gdpr)).
- **Self-registration** on first face scan: name, 4–6 character PIN, and an optional voice sample. Registration shows a plain-language privacy notice, records consent (DPDP Act Sec. 6), and registers under-18s as PIN-only until a parent/guardian gives verifiable consent in person to the teacher (Sec. 9(1)).
- **My data & privacy:** every student can see what data is held about them (Sec. 11), withdraw biometric consent (Sec. 6(4)), and self-service **"Delete My Biometric Data"** (Sec. 12(2)) — a real delete of face/voice templates, not a flag.
- **Add extra face scans** (glasses, hairstyle, lighting) from the sidebar. Up to **5** face embeddings are kept per student.
- **Auto-enrol** by opening a join link (`?join-code=XXXX`) or scanning the teacher's QR code, or enter a subject code manually.
- View enrolled subjects, total classes, and a timestamped **attended / absent history** for each subject.
- Unenroll from a subject at any time — with a confirmation step.

### 🤖 AI / Biometric Features
- **Face recognition** with `dlib` (HOG detector, 68-point landmarks, ResNet encoder via `face_recognition_models`) producing L2-normalised 128-D descriptors.
  - Single-face login uses a fast upright scan.
  - Classroom photos add **micro-tilt passes (±15°)** to catch tilted heads, with duplicate suppression by descriptor distance.
  - Matching uses a strict Euclidean threshold (default `0.38`) and is **scoped to students enrolled in the selected subject**, which avoids false matches against students from other classes.
  - Gallery embeddings are cached for 5 minutes and refreshed when a profile is registered or updated.
- **Heuristic liveness screening** on face login and extra-scan enrolment. It looks for weak signals — phone/tablet bezels around the face, screen glare and over-exposed regions, and Moiré patterns from digital screens (FFT frequency-energy analysis) — and may flag some of them. **It does not reliably block printed photos or video replays**, and a pass is not proof of a live person. See [Honest Threat Model & Limitations](#-honest-threat-model--limitations).
- **Voice recognition** with `resemblyzer` (256-D speaker embeddings) and `librosa`. Classroom audio is split into speech segments and each is matched by cosine similarity (default threshold `0.65`) against enrolled students' voice prints.

### 🔗 Join Links & QR Codes
- Deep-link support: opening the app with `?join-code=<code>` switches to the student flow and shows the **auto-enrol dialog** once the student is logged in.
- QR codes are generated with **segno**. Set `APP_URL` in secrets to control the base URL embedded in links and QR codes.

### 🎨 UI / UX
- **Light and dark themes** with a toggle on every screen.
- Animated gradient buttons, themed dialogs with banners, and responsive/mobile-friendly styling.
- Collapsed sidebar by default, custom page title and favicon.
- Streamlit's deploy button, main menu and footer are hidden for a polished look.

### 🛡️ Reliability & Compatibility
- Supabase calls are wrapped in an **exponential-backoff retry** decorator for transient network errors.
- Built-in `pkg_resources` shim so the app still runs on newer Python versions where `pkg_resources` is no longer bundled (needed by `face_recognition_models`).
- **Dependencies are locked** (`requirements-ui.lock` for the UI image, `worker/requirements.lock` for the worker) — generated with `uv pip compile --python-version 3.11`; regenerate with the same command. Unused packages were removed: no code imports `scikit-learn` or `webrtcvad` (scikit-learn remains only as a transitive dependency of SpeechBrain/pyannote in the worker image). Real runtime dependencies are listed explicitly: `scipy`, `httpx`, `onnxruntime`, `argon2-cffi`.
- **Streamlit XSRF and CORS protection stay on** (`.streamlit/config.toml`); the dev container no longer disables them (audit 44).
- **CI** (`.github/workflows/ci.yml`): ruff, mypy (advisory), bandit, pip-audit, pytest on Python 3.11.

---

## 🧰 Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Web framework | [Streamlit](https://streamlit.io/) |
| Database / Backend | [Supabase](https://supabase.com/) (Postgres + pgvector + Auth + RLS) |
| Face recognition | Phase 2 worker: ONNX Runtime, SCRFD + ArcFace/AdaFace; legacy `dlib-bin` path kept behind `FACE_BACKEND=dlib` |
| Voice recognition | Phase 2 worker: ECAPA-TDNN (`speechbrain`), pyannote diarization, AASIST; legacy `resemblyzer` path kept for local dev |
| Data / numerics | `numpy`, `pandas`, `scipy` |
| Authentication | Google-first via Supabase Auth (`st.login` OIDC bridge); PINs/passwords hashed with Argon2id (`argon2-cffi`, OWASP) — legacy bcrypt hashes are transparently re-hashed on login |
| QR code generation | `segno` |
| Image handling | `pillow` |

---

## 🏗️ Architecture

```mermaid
flowchart LR
    Student["Student / Teacher\n(browser)"] --> UI["Streamlit UI\n(light image, no ML libs)\nDockerfile.ui"]
    UI -->|anon key + user JWT\nRLS enforced| SB["Supabase Postgres\nstudents / subjects /\nattendance / audit_log"]
    UI -->|anon key + JWT| SB
    SB <-->|pgvector 512-d face\n192-d voice, HNSW| VEC["face_embeddings\nvoice_embeddings"]
    UI -->|POST /jobs\nGET /jobs/id| W["FastAPI ML worker\nDockerfile.worker\nONNX face/voice + PAD"]
    W -->|service_role key\n(worker env only)| SB
    W -->|FOR UPDATE SKIP LOCKED| JOBS["inference_jobs"]
    W -.->|raw photo/audio\nin memory only,\ndeleted after use| W
```

- **UI image** (`Dockerfile.ui`, `requirements-ui.txt` → `requirements-ui.lock`): Streamlit + Supabase client + Argon2id. No torch / dlib / onnxruntime / pyannote.
- **Worker image** (`Dockerfile.worker`, `worker/requirements.txt` → `worker/requirements.lock`): FastAPI + ONNX Runtime + torch/SpeechBrain/pyannote, model weights baked in, `/healthz` + `/readyz`. Started by `docker-compose.yml` alongside the UI.
- **Database:** Supabase Postgres with pgvector (migration 004), RLS policies (migrations 001/003/004/005), append-only `audit_log`, and `consent_records` / `parental_consents` (migration 005).
- **Raw media:** photos/audio are held in memory only (UI session state / worker payload cache) and deleted immediately after inference. They are never written to disk or object storage. See `docs/privacy/dpia.md`.

---

## ⚙️ How It Works

1. **Registration**: a student reads the plain-language privacy notice, gives consent, and (if 18+) scans their face (passing the heuristic liveness screening in the legacy path, or Phase 2 PAD in the worker path — see [limitations](#-honest-threat-model--limitations)) and optionally records a voice sample. Templates are stored as 512-D face / 192-D voice vectors in `face_embeddings` / `voice_embeddings`; raw photos/audio are deleted immediately after inference. Under-18s register PIN-only until a parent/guardian consents in person to the teacher.
2. **Class creation**: a teacher creates a subject and gets a join code, link and QR code.
3. **Enrolment**: students enter the code, open the link or scan the QR code; the `auto_enroll` dialog confirms and enrols them.
4. **Attendance**: the teacher adds classroom photos (face scan) or records audio (voice scan). The system detects faces/speakers, matches them against **only the students enrolled in that subject**, and builds a report. Students can also be marked by PIN login or manually — no biometrics required.
5. **Confirmation**: the teacher reviews the report and saves it. Each session is stored as one `attendance_logs` row per enrolled student, sharing a timestamp.
6. **Reports**: teachers see per-session breakdowns and can correct entries; students see their attended and absent sessions per subject. Absences for sessions held before a student enrolled are computed at view time rather than stored.

---

## 📂 Project Structure

```
Smart_Attendance/
├── .devcontainer/            # Dev container / Codespaces configuration
├── .github/workflows/ci.yml  # CI: ruff, mypy, bandit, pip-audit, pytest
├── .streamlit/               # config.toml (XSRF/CORS on), secrets.toml.example
├── docs/privacy/             # privacy-notice.md, dpia.md, cancelable-templates.md
├── img/                      # header.png, NKA.png, student.png, teacher.png
├── migrations/               # 001-005 (005: consent tables + delete_subject_tx)
├── scripts/                  # evaluate_biometrics.py, pin_hash_helper.py
├── src/
│   ├── database/
│   │   ├── config.py         # Supabase client (anon key only), retry policy
│   │   ├── db.py             # All database queries; transactional subject delete
│   │   ├── privacy.py        # Phase 3: consent, parental gate, erasure, breach log
│   │   └── vector.py         # pgvector match_faces (+ template-access audit)
│   ├── pipelines/            # Legacy dlib/resemblyzer (worker is the Phase 2 path)
│   ├── screen/               # home / teacher / student screens (+ auth, dialogs)
│   ├── components/           # Reusable UI components and dialogs
│   └── ui/                   # base_layout, uploads (in-memory ingest), worker_client
├── tests/                    # pytest incl. tests/test_phase3_privacy.py
├── worker/                   # FastAPI ML worker (ONNX face/voice + PAD)
├── app.py                    # Application entry point and routing
├── docker-compose.yml        # UI + worker (healthchecks on /healthz)
├── Dockerfile.ui / Dockerfile.worker
├── requirements-ui.txt / requirements-ui.lock   # UI deps (locked, Python 3.11)
├── worker/requirements.txt / worker/requirements.lock
├── requirements.txt          # Legacy local-dev deps (dlib/resemblyzer)
├── .env.example
├── LICENSE                   # MIT
├── pyproject.toml            # ruff / mypy / bandit config
├── .gitignore
└── README.md
```

---

## 🚀 Installation & Setup

### Prerequisites
- Python 3.11
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

# 3. Install dependencies (locked, Python 3.11 — see requirements-ui.lock)
pip install -r requirements-ui.lock
# Legacy local-dev stack (dlib/resemblyzer) only if you need the old
# in-process pipelines:
# pip install -r requirements.txt
```

---

## 🔐 Configuration

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in real values. Keys are **top-level** (not nested in a section):

```toml
SUPABASE_URL = "YOUR_SUPABASE_URL"
SUPABASE_KEY = "YOUR_SUPABASE_ANON_KEY"
```

> ⚠️ `SUPABASE_KEY` is the **anon key only**. The service_role key bypasses Row Level Security and must NEVER be placed here or anywhere in the Streamlit app — it lives in the ML worker environment only (see `.env.example`). Never commit your secrets: `.streamlit/secrets.toml` and `.env` are gitignored; only the `.example` files are checked in.

If `APP_URL` is not set, share links default to `https://smartclass-main.streamlit.app`.

For local Docker runs, copy `.env.example` to `.env` (worker secrets go there, never in the UI service).

---

## 🚢 Deployment

> **Status: not deployed.** The deployment decision (Streamlit Community Cloud vs a container for the UI; Cloud Run vs Render for the worker) still needs Naman. Nothing below has been run against a hosted environment yet.

1. **Database:** create a Supabase project, enable the `vector` extension, and run the migrations **in order** from the Supabase SQL Editor — `migrations/001_phase0_core.sql`, `002_phase0_pin_enforcement.sql` (only after every student has a PIN hash), `003_fix_rls_recursion.sql`, `004_phase1_pgvector.sql`, `005_phase3_privacy.sql`. Back up (`pg_dump`) before each run. Never run migrations from the app.
2. **Auth:** create a Google Cloud OAuth client with redirect `https://<your-project>.supabase.co/auth/v1/callback`, enable the Google provider in Supabase Auth, and link each teacher/student `auth_user_id` to their row (without the link, RLS returns zero rows by design).
3. **Worker:** bake the model weights into the worker image (`worker/models/` — the build fails if any weight is missing), set `SUPABASE_SERVICE_ROLE_KEY`, `HF_TOKEN` and `DATABASE_URL` in the worker environment only, and deploy the worker first. Check `GET /readyz` returns 200.
4. **UI:** deploy the Streamlit app with `SUPABASE_URL` + `SUPABASE_ANON_KEY` only (via `.streamlit/secrets.toml` or environment), set `ML_WORKER_URL` to the worker, and confirm XSRF/CORS protection is on (`.streamlit/config.toml`).
5. **Privacy before real data:** fill in the real grievance-officer contact (currently a placeholder), backfill dates of birth for the under-18 gate, and have the privacy notice + DPIA (`docs/privacy/`) reviewed by a qualified data-protection lawyer.
6. **Evaluate:** run `scripts/evaluate_biometrics.py` on a labelled classroom set and calibrate thresholds before trusting PAD or matching in production (see [limitations](#-honest-threat-model--limitations)).

Local Docker equivalent: `docker compose up --build` (UI on :8501, worker on :8000, healthchecks on `/healthz`).

---

## 🗄️ Database Schema

Apply the migrations in `migrations/` (001–005) — the table below is a summary, not the DDL. Key tables:

| Table | Columns |
|---|---|
| `teachers` | `teacher_id` (UUID PK), `username` (unique), `password` (Argon2id hash), `name`, `auth_user_id` |
| `students` | `student_id` (UUID PK), `usn` (unique), `name`, `pin_hash` (Argon2id, NOT NULL after 002), `date_of_birth`, `auth_user_id` |
| `face_embeddings` / `voice_embeddings` | `student_id` (FK), `embedding` (pgvector 512-d / 192-d), `model_version`, `created_at` |
| `consent_records` | `student_id`, `purpose`, `notice_version`, `granted`, `granted_at` |
| `parental_consents` | `student_id`, `guardian_name`, `verification_method`, `verified_by_teacher_id`, `verified_at` |
| `subjects` | `subject_id` (UUID PK), `subject_code`, `name`, `section`, `teacher_id` (FK), `join_code` (unique) |
| `subject_students` | `student_id` (FK), `subject_id` (FK), `enrolled_at` |
| `attendance_sessions` | `session_id` (UUID PK), `subject_id`, `teacher_id`, `method`, `started_at` |
| `attendance_logs` | `id` (UUID PK), `session_id`, `student_id`, `subject_id`, `timestamp`, `is_present`, `UNIQUE (session_id, student_id)` |
| `audit_log` | append-only: `actor_id`, `action`, `table_name`, `record_id`, `details`, `created_at` |

Notes:
- Legacy 128-D dlib face vectors (in `students.face_embedding`) and 256-D Resemblyzer voice vectors are kept only until the Phase 2 worker migrates them; the pgvector tables hold the 512-D / 192-D Phase 2 vectors.
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

## 🔒 Privacy & Legal (DPDP / GDPR)

Smart Attendance processes biometric data, so privacy is a feature, not a footnote. Full details: `docs/privacy/privacy-notice.md` (the notice), `docs/privacy/dpia.md` (DPIA + proportionality), `docs/privacy/cancelable-templates.md` (future option, not built). Code: `src/database/privacy.py`, migration `005_phase3_privacy.sql`.

**India DPDP Act 2023** (official text: https://www.indiacode.nic.in/bitstream/123456789/22037/2/a2023-22.pdf — section numbers verified against the Act text, 2026-11-22):

| Requirement | What the app does |
|---|---|
| Plain-language Notice (Sec. 5) | Shown at registration and in "My data & privacy"; versioned (`PRIVACY_NOTICE_VERSION = "1.0"`) |
| Withdrawable Consent (Sec. 6(1), 6(4), 6(6)) | Consent recorded with timestamp + notice version (Sec. 6(10) burden of proof); withdrawal is one click, as easy as giving consent |
| Verifiable parental consent, under 18 (Sec. 9(1)) | Under-18s register PIN-only; a parent/guardian must consent in person to the teacher before any template is made; the gate fails closed on unknown age |
| Security safeguards + breach logging (Sec. 8(5), 8(6)) | RLS, anon-key-only UI, structured breach log (`security_breach` in `audit_log`: breach id, categories, affected *count*, notification status — never personal data from the breach) |
| Erasure on withdrawal / purpose end (Sec. 8(7)) | "Delete My Biometric Data" deletes templates from `face_embeddings`/`voice_embeddings` + legacy columns, and logs it |
| Access summary (Sec. 11) | "My data & privacy" shows identity, enrolments, template counts + model versions, consent state, attendance totals — never `pin_hash` or vectors |
| Correction + erasure self-service (Sec. 12) | Correct your name; delete your templates |
| Grievance contact (Sec. 8(9), 8(10) / Sec. 13) | Grievance officer contact in-app + in the notice — **currently a placeholder (`grievance-officer@example.invalid`); Naman must fill in a real contact before deployment** |

**GDPR Art. 9 + AEPD biometric attendance guidelines** (https://gdpr-info.eu/art-9-gdpr/): biometric data is a special category. Consent is only freely given because a **non-biometric fallback** exists — Student ID + PIN login and teacher manual marking, with no penalty and no difference in the record. Every template read/match is logged in `audit_log` (`template_access`, identifiers + counts only). Proportionality and the DPIA are in `docs/privacy/dpia.md`.

**Templates:** raw photos/audio are processed in memory and deleted immediately after inference — never written to disk or object storage (tested). Templates live in separate pgvector tables, away from identity rows, under strict RLS. Encryption at rest is a **Supabase platform setting, not app-level encryption** — the app does not encrypt vectors itself and does not claim to. ISO/IEC 24745 cancelable templates are documented as a future option only (`docs/privacy/cancelable-templates.md`).

**What Phase 3 built (code complete, NOT deployed):** consent + parental-consent flows, access summary, correction, "Delete My Biometric Data", template-access audit logging (UI + worker), breach logging, transactional subject delete (`delete_subject_tx`), unenrol confirmation, locked dependencies, CI, MIT licence, example secrets, XSRF/CORS on. Migration 005 has **not** been run live yet.

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

## 🛡️ Honest Threat Model & Limitations

This section states plainly what the system does **not** protect against yet. Do not rely on the features below beyond what is written here.

### What is NOT true today
- **Printed photos and video replays are not reliably blocked in the legacy path.** The legacy dlib face login uses heuristic screening only (glare, Moiré, bezel signals). A printed photo or a replayed video can pass it. Face login is therefore a *convenience* factor, not a security boundary. The Phase 2 worker has a real PAD model (MiniFASNet/CDCN) — but it is **not deployed and not evaluated** (see below).
- **The face-match threshold (0.38, legacy) is uncalibrated.** It was chosen ad hoc, not measured on a labelled dataset, so the real false-match / false-non-match rates are unknown. The worker's thresholds are uncalibrated starting points too.
- **Biometric templates are stored as plain embedding vectors** in Supabase (512-D face / 192-D voice in pgvector; 128-D / 256-D legacy vectors in `students`). They are not encrypted at rest by the app, and they cannot be revoked like a password if leaked — a new scan is the only rotation. Encryption at rest is a Supabase platform setting, not app-level encryption. Cancelable templates (ISO/IEC 24745) are documented as a future option only.
- **Voice attendance can be spoofed by replay** (playing a recording of a student), and students with no voiceprint are simply undetectable by voice. The worker's AASIST anti-spoofing is not evaluated yet.
- **1:N face matching is scoped to the enrolled roster only when the caller passes `candidate_ids`.** The pipeline logs a warning when it is not given; the teacher classroom flow does pass it.

### What is fixed (Phases 0–1, verified)
- **PINs are hashed with Argon2id** (OWASP Password Storage Cheat Sheet); legacy bcrypt hashes are transparently re-hashed on the next successful login. PIN login has sliding-window rate limiting + exponential lockout, and fails closed on PIN-less accounts.
- **Row Level Security is enabled** (migrations 001/003/004/005): students see only their own rows, teachers only their own subjects and that attendance; anon reads return nothing. Verified live after migration 003 (anon reads return `200 []`, no 42P17 recursion errors). The `service_role` key lives in the worker environment only, never in Streamlit code.
- **1:1-only face login:** student face login verifies against the claimed student's template only.
- **Google-first login** is wired in code (Supabase Auth JWT drives RLS); the Streamlit OIDC provider setup itself is still pending.

### What Phase 2 will do about it
- **Real presentation-attack detection (PAD):** deploy and evaluate MiniFASNet / CDCN (https://arxiv.org/abs/2106.14948) per ISO/IEC 30107-3 (APCER/BPCER), replacing the heuristic checks.
- **Calibrated matching:** measure FMR/FNMR curves and set the operating threshold per ISO/IEC 19795-1 instead of the ad-hoc 0.38.
- **Template protection:** evaluate encrypted / cancellable template storage before any production deployment holding real student biometrics.

### Safe operation until then
Use this system for low-stakes classroom attendance with a teacher present, keep the teacher's review-before-saving step enabled, and correct entries from **Attendance Records** when the AI is wrong. Do not use face-only login as the sole gate for anything high-stakes (exams, payments, access control).

### What Phase 2 built (code complete, NOT deployed or evaluated yet)
- **Separate ML worker** (`worker/`, `Dockerfile.worker`, `docker-compose.yml`): FastAPI service with `POST /jobs`, `GET /jobs/{id}`, `GET /healthz`, `GET /readyz`; Postgres `FOR UPDATE SKIP LOCKED` queue (`inference_jobs`); light UI image (`Dockerfile.ui`, `requirements-ui.txt`) with no torch/dlib/onnxruntime/pyannote. The UI submits photo/audio jobs and polls from an `@st.fragment`, falling back to the legacy in-process pipeline when the worker is unreachable.
- **ONNX face pipeline** (`worker/face_onnx.py`): SCRFD detection + 5-point alignment, overlapping tiled inference + NMS for back-row faces, ArcFace/AdaFace batched embeddings, AdaFace/MagFace feature-norm quality gate, Hungarian one-to-one matching + second-best margin test. The legacy dlib path is kept behind the explicit `FACE_BACKEND=dlib` flag; the ONNX path is the default and fails loudly when weights are missing.
- **Face PAD** (`worker/pad.py`): MiniFASNet/CDCN passive PAD plus a randomised blink/head-turn active challenge. The heuristic liveness is removed as a gate; if the PAD model is unavailable the check **rejects** (fail closed).
- **Voice** (`worker/voice_onnx.py`): ECAPA-TDNN + pyannote diarization + AASIST anti-spoofing + server-issued random challenge phrase. No speech-recognition check of the phrase (needs Naman's approval first).
- **Evaluation** (`scripts/evaluate_biometrics.py`): ISO/IEC 19795-1 (ROC/DET, FMR/FNMR, EER, FPIR/FNIR, FTE/FTA) and ISO/IEC 30107-3 (APCER/BPCER/IAPMR) from a labelled dataset — **no labelled classroom set exists yet, so no thresholds have been calibrated and no metrics have been measured**. All worker thresholds are uncalibrated starting points.
- **Load test** (`tests/load/locustfile.py`): 50 concurrent users (logins, attendance lookups, group-photo jobs) with p50/p95/p99 + error rate. **No benchmark has been run** — there is no deployed system and no model weights yet.

**What is still NOT true:** no model weights are bundled (they must be baked into the worker image — see `worker/README.md`); `HF_TOKEN` and the `service_role` key are not configured; migration 004 has not been run live; the Streamlit OIDC provider setup is not done. Until those land and the evaluation script runs on real classroom data, the limitations above still apply.

### What Phase 3 built (code complete, NOT deployed or evaluated yet)
- **Privacy, DPDP Act 2023 + GDPR Art. 9** (see [Privacy](#-privacy--legal-dpdp--gdpr) and `docs/privacy/`): plain-language notice (Sec. 5), versioned consent records with withdrawal (Sec. 6(1), 6(4)), verifiable parental consent for under-18s with a fail-closed gate (Sec. 9(1)), breach logging (Sec. 8(5)–(6)), erasure on withdrawal/purpose end (Sec. 8(7)), access summary (Sec. 11), correction + "Delete My Biometric Data" self-service (Sec. 12), grievance contact — **currently a placeholder, must be filled in before deployment** (Sec. 8(9), 8(10) / Sec. 13).
- **Non-biometric fallback:** PIN login + teacher manual marking, stated in the UI as working with no penalty, so biometric consent is genuinely free.
- **Template-access audit logging:** every template read/match is written to `audit_log` (UI `match_faces`, worker gallery load + match) with identifiers + counts only — never vectors, photos or audio.
- **Engineering:** locked dependencies (`requirements-ui.lock`, `worker/requirements.lock`, Python 3.11), GitHub Actions CI (ruff, mypy, bandit, pip-audit, pytest), MIT `LICENSE`, `.streamlit/secrets.toml.example` + `.env.example` (placeholders only), XSRF/CORS protection on (dev container fixed, audit 44), confirmation dialog for unenrol, transactional subject delete (`delete_subject_tx`, migration 005).
- **Still NOT done:** migration 005 has not been run live; the grievance officer is a placeholder; dates of birth are missing for the 8 legacy students, so the under-18 gate cannot evaluate them on re-enrolment (DOB backfill open); templates are still plain vectors (no app-level encryption, no cancelable templates — see `docs/privacy/cancelable-templates.md`); PAD/anti-spoofing is still unevaluated.

---

## 🔮 Future Improvements

- Email / SMS notifications for low attendance
- Export attendance to CSV / PDF
- Admin dashboard and richer analytics charts
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

MIT — see the [`LICENSE`](LICENSE) file.

---

## 👤 Author

**Naman** – [@namankrag](https://github.com/namankrag)