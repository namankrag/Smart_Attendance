# ML worker (Phase 2)

FastAPI + Postgres-queue ML worker. It runs in its own container; the
Streamlit UI image contains **no** torch / dlib / onnxruntime /
pyannote.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | Liveness (process up) |
| GET | `/readyz` | Readiness (model files present + job store reachable; 503 otherwise) |
| POST | `/jobs` | Submit a `face` or `voice` job → 202 `{id, status, ...}` |
| GET | `/jobs/{id}` | Poll status / progress / result / error |
| POST | `/challenges/face` | Issue a randomised blink/head-turn challenge |
| POST | `/challenges/voice` | Issue a random challenge phrase |
| POST | `/verify/face-1to1` | 1:1 face verification + PAD + challenge (fail closed) |
| POST | `/verify/voice-1to1` | 1:1 voice verification + AASIST + challenge (fail closed) |

## Attendance REST API

The data API is mounted at `/api/v1` in this same FastAPI service. It
validates the Supabase access token on each request and forwards that
user JWT to Postgres so RLS remains active. The internal adapter used by
the Streamlit server also requires `X-Internal-Token`; set the same
`API_INTERNAL_TOKEN` on the UI and worker. This token is server-side only.

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/auth/student` | Verify PIN, apply login throttling, and link the student profile to the signed-in user |
| POST | `/api/v1/auth/teacher` | Verify password, apply login throttling, and link the teacher profile |
| GET | `/api/v1/students/me` | Read the signed-in student's profile |
| GET | `/api/v1/students/me/subjects` | List the student's subjects |
| GET | `/api/v1/students/me/attendance` | List the student's attendance |
| POST | `/api/v1/students/me/enrollments` | Join by invitation code |
| DELETE | `/api/v1/students/me/enrollments/{subject_id}` | Leave a subject |
| GET | `/api/v1/teachers/me/subjects` | List the signed-in teacher's subjects |
| GET | `/api/v1/teachers/me/attendance` | List attendance with optional filters |
| POST | `/api/v1/subjects` | Create a subject |
| GET | `/api/v1/subjects/{id}` | Read an accessible subject |
| GET | `/api/v1/subjects/by-join-code/{join_code}` | Preview a subject from its invitation code |
| GET | `/api/v1/subjects/{id}/students` | List the accessible roster (without biometric templates) |
| POST | `/api/v1/subjects/{id}/enrollments` | Enroll a student by ID in a teacher-owned subject |
| DELETE | `/api/v1/subjects/{id}/enrollments/{student_id}` | Remove a student from a teacher-owned subject |
| POST | `/api/v1/subjects/{id}/enrollments/by-usn` | Find a student by USN and enroll them, scoped to a teacher-owned subject |
| POST | `/api/v1/subjects/{id}/sessions` | Create an attendance session and its records |
| PATCH | `/api/v1/attendance/{log_id}` | Correct an attendance record |
| DELETE | `/api/v1/subjects/{id}` | Delete a teacher-owned subject |

Enrollment routes, teacher roster reads and scoped face-profile calls require
migrations `007_student_self_enrollment.sql` and `008_teacher_mfa.sql`.
Teacher data routes require a valid Supabase access token at AAL2 (MFA).
All routes require a valid Supabase Bearer token; `/auth/*` and the hidden
`/internal/*` adapter also require the internal token. `/docs` exposes the
public REST route schemas.

Job queue: Postgres `inference_jobs`, claimed with
`FOR UPDATE SKIP LOCKED` (`worker/queue.py`) — no Redis by default.
Run several worker replicas safely; each job is claimed by exactly one.

## Model weights — baked in at build time, never downloaded at runtime

**Weights are NOT in this repo and are NOT downloaded by the worker.**
`Dockerfile.worker` copies a local `worker/models/` directory into
`/models` at build time. Before building, place the files there:

| File (in `worker/models/`) | What it is | Source |
|---|---|---|
| `scrfd_10g_bnkps.onnx` | SCRFD detector | InsightFace model zoo — https://github.com/deepinsight/insightface |
| `arcface_r100.onnx` | ArcFace recognition (or an AdaFace ONNX export) | InsightFace; AdaFace — https://arxiv.org/abs/2204.00964 |
| `minifasnet.onnx` | Passive PAD | MiniFASNet — https://github.com/minivision-ai/Silent-Face-Anti-Spoofing (or a CDCN ONNX export — https://arxiv.org/abs/2003.04092) |
| `aasist.onnx` | Voice anti-spoofing | AASIST ONNX export — https://arxiv.org/abs/2110.01200 |

If a file is missing, the worker fails loudly at first use
(`ModelUnavailableError`, job → `failed`, `/readyz` → 503). It never
silently falls back to dlib and never silently accepts a face/voice.

ECAPA-TDNN (`speechbrain/spkrec-ecapa-voxceleb`) and pyannote
diarization (`pyannote/speaker-diarization-3.1`) are loaded by their
libraries from their caches — those caches must also be baked into the
image (or the model dir) at build time; the worker does not download
them at runtime either. The SpeechBrain/pyannote model **code** ships
in the image; the **weights** must be present in the image.

## Secrets (worker environment only)

| Variable | Purpose |
|---|---|
| `HF_TOKEN` | Hugging Face token for pyannote's gated diarization model. Worker env only — never in Streamlit, never in a file. |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Worker-only gallery loading, login throttling/profile linking and exact invitation-code lookup. The `service_role` key must never appear in Streamlit code. |
| `SUPABASE_ANON_KEY` | Project key used to validate user sessions on the REST API. It is safe to share with the UI; RLS protects data requests. |
| `API_INTERNAL_TOKEN` | Long random value shared between UI and worker for the private Streamlit database adapter. |
| `DATABASE_URL` | Postgres DSN for the job queue. Empty → in-memory job store (dev only, single replica). |
| `MODEL_DIR` | Weights directory (default `/models`). |
| `FACE_BACKEND` | `onnx` (default, required). `dlib` raises loudly — the worker has no dlib. |

## Raw media

Payloads are held in memory only and deleted after processing. The
worker never writes raw photos or audio to disk or object storage.
Multi-replica note: with the Postgres store, payloads live in the
submitting process's memory (`app.state.payloads`), so a job must be
claimed by the same replica that received it — run **one** replica
unless shared ephemeral payload storage is added (documented
limitation, not silently worked around).

## Thresholds

All matching / PAD / spoof thresholds in `worker/config.py` are
**uncalibrated starting points**. Calibrate them on a labelled
classroom set with `scripts/evaluate_biometrics.py` (ISO/IEC 19795-1
and 30107-3) before trusting any operating point.

## Local run (dev only)

```bash
docker compose up --build   # UI on :8501, worker on :8000
curl localhost:8000/healthz
```

No deployment is configured here — Phase 2 does not deploy anywhere.
The deployment decision (Streamlit Cloud vs container, Cloud Run vs
Render for the worker) still needs Naman.
