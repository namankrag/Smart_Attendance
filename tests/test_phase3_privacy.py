"""Phase 3 regression tests: DPDP Act 2023 / GDPR Art. 9 privacy,
template protection, engineering hygiene (SPEC Phase 3).

Mocked (no network, no Supabase keys, no live migration): the fake
DB from conftest.py stands in for Supabase; the worker tests use
fake pipelines. Section numbers cited here were verified against
the Act text on 2026-11-22 (see src/database/privacy.py header).
"""
import io
import json
import re
import sys
from datetime import date as _date
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.database import privacy as priv  # noqa: E402
from src.database import db as dbmod  # noqa: E402

STUDENT = "11111111-1111-1111-1111-111111111111"
STUDENT2 = "22222222-2222-2222-2222-222222222222"
TEACHER = "33333333-3333-3333-3333-333333333333"
OTHER_TEACHER = "99999999-9999-9999-9999-999999999999"
SUBJECT = "44444444-4444-4444-4444-444444444444"


@pytest.fixture
def pdb(monkeypatch, fake_db):
    """privacy module pointed at the fake DB, with template tables seeded."""
    monkeypatch.setattr(priv, "supabase", fake_db)
    fake_db.tables.setdefault("consent_records", [])
    fake_db.tables.setdefault("parental_consents", [])
    fake_db.tables.setdefault("audit_log", [])
    fake_db.tables.setdefault("face_embeddings", [
        {"student_id": STUDENT, "model_version": "arcface_r100",
         "created_at": "2026-11-01T00:00:00+00:00",
         "embedding": [0.1] * 512},
        {"student_id": STUDENT, "model_version": "arcface_r100",
         "created_at": "2026-11-02T00:00:00+00:00",
         "embedding": [0.2] * 512},
    ])
    fake_db.tables.setdefault("voice_embeddings", [
        {"student_id": STUDENT, "model_version": "ecapa",
         "created_at": "2026-11-01T00:00:00+00:00",
         "embedding": [0.3] * 192},
    ])
    fake_db.tables["attendance_logs"] = [
        {"id": "log-1", "student_id": STUDENT, "subject_id": SUBJECT,
         "is_present": True},
    ]
    return fake_db


def _audit_rows(fake_db, action=None):
    rows = fake_db.tables.get("audit_log", [])
    if action is None:
        return rows
    return [r for r in rows if r.get("action") == action]


# ---------------------------------------------------------------------------
# 1. Consent (DPDP Sec. 6) — record + withdraw, versioned, audited
# ---------------------------------------------------------------------------
def test_consent_recorded_with_version_and_audit(pdb):
    row = priv.record_consent(STUDENT, purpose="biometric_attendance")
    assert row["granted"] is True
    assert row["notice_version"] == priv.PRIVACY_NOTICE_VERSION
    assert row["purpose"] == "biometric_attendance"
    assert len(pdb.tables["consent_records"]) == 1
    assert priv.has_active_consent(STUDENT) is True
    audit = _audit_rows(pdb, "consent_recorded")
    assert len(audit) == 1
    assert audit[0]["details"]["notice_version"] == priv.PRIVACY_NOTICE_VERSION


def test_consent_rejects_unknown_purpose(pdb):
    with pytest.raises(ValueError):
        priv.record_consent(STUDENT, purpose="marketing")


def test_consent_withdrawal_is_recorded_and_active_consent_ends(pdb, monkeypatch):
    timestamps = iter((
        "2026-11-24T12:00:00+00:00",
        "2026-11-24T12:00:01+00:00",
    ))
    monkeypatch.setattr(priv, "_utcnow_iso", lambda: next(timestamps))
    priv.record_consent(STUDENT)
    assert priv.has_active_consent(STUDENT) is True
    priv.withdraw_consent(STUDENT)
    assert priv.has_active_consent(STUDENT) is False
    latest = priv.get_latest_consent(STUDENT)
    assert latest["granted"] is False
    audit = _audit_rows(pdb, "consent_withdrawn")
    assert len(audit) == 1
    # Withdrawal notes erasure is still owed (DPDP Sec. 8(7)) until done.
    assert audit[0]["details"]["erasure_pending"] is True


def test_no_consent_record_means_no_active_consent(pdb):
    assert priv.has_active_consent(STUDENT2) is False
    assert priv.get_latest_consent(STUDENT2) is None


# ---------------------------------------------------------------------------
# 2. Children / parental consent (DPDP Sec. 9) — fail-closed gate
# ---------------------------------------------------------------------------
def test_is_under_18_from_dob():
    assert priv.is_under_18("2015-06-01", today=_date(2026, 11, 22)) is True
    assert priv.is_under_18("2000-01-01", today=_date(2026, 11, 22)) is False
    # Exactly 18 on the day: not a child.
    assert priv.is_under_18("2008-11-22", today=_date(2026, 11, 22)) is False
    assert priv.is_under_18("2008-11-23", today=_date(2026, 11, 22)) is True


def test_is_under_18_fails_closed_on_unknown_or_bad_age():
    assert priv.is_under_18(None) is True
    assert priv.is_under_18("not-a-date") is True
    assert priv.is_under_18(None, is_minor=True) is True
    assert priv.is_under_18(None, is_minor=False) is False


def test_parental_consent_gate_blocks_minor_without_record(pdb):
    with pytest.raises(PermissionError):
        priv.require_biometric_enrolment_allowed(STUDENT, date_of_birth="2015-01-01")
    # Unknown age also fails closed.
    with pytest.raises(PermissionError):
        priv.require_biometric_enrolment_allowed(STUDENT)


def test_parental_consent_gate_passes_minor_with_record_and_adults(pdb):
    priv.record_parental_consent(
        STUDENT, guardian_name="Meera Keshri",
        verified_by_teacher_id=TEACHER, method="in_person")
    assert priv.has_parental_consent(STUDENT) is True
    priv.require_biometric_enrolment_allowed(STUDENT, date_of_birth="2015-01-01")
    # Adults pass without any parental record.
    priv.require_biometric_enrolment_allowed(STUDENT2, date_of_birth="2000-01-01")
    audit = _audit_rows(pdb, "parental_consent_recorded")
    assert len(audit) == 1
    # The audit row must not contain the guardian's contact details.
    assert "guardian_contact" not in json.dumps(audit[0]["details"])


def test_parental_consent_rejects_unknown_method(pdb):
    with pytest.raises(ValueError):
        priv.record_parental_consent(
            STUDENT, guardian_name="X", verified_by_teacher_id=TEACHER,
            method="email_otp")
    with pytest.raises(ValueError):
        priv.record_parental_consent(
            STUDENT, guardian_name="  ", verified_by_teacher_id=TEACHER)


# ---------------------------------------------------------------------------
# 3. Access summary (DPDP Sec. 11) + correction (Sec. 12)
# ---------------------------------------------------------------------------
def test_access_summary_never_exposes_pin_hash_or_vectors(pdb):
    summary = priv.get_access_summary(STUDENT)
    blob = json.dumps(summary)
    assert "pin_hash" not in blob
    assert "PLACEHOLDER" not in blob  # the seeded fake hash must not leak
    assert summary["face_templates"]["count"] == 2
    assert summary["voice_templates"]["count"] == 1
    assert summary["face_templates"]["model_versions"] == ["arcface_r100"]
    assert summary["attendance"]["total_logs"] == 1
    assert summary["attendance"]["present"] == 1
    assert summary["enrolments"][0]["subject_id"] == SUBJECT
    assert summary["student"]["usn"] == "1MS21CS001"
    # Sec. 11(1)(b): who the data was shared with is disclosed.
    assert summary["shared_with"]


def test_correct_student_profile_updates_name_and_audits(pdb):
    out = priv.correct_student_profile(STUDENT, name="Asha Verma")
    assert pdb.tables["students"][0]["name"] == "Asha Verma"
    assert out["name"] == "Asha Verma"
    audit = _audit_rows(pdb, "profile_corrected")
    assert len(audit) == 1
    # The audit row records the fact, not the old/new name value.
    assert "Asha" not in json.dumps(audit[0]["details"])
    with pytest.raises(ValueError):
        priv.correct_student_profile(STUDENT, name="   ")
    with pytest.raises(ValueError):
        priv.correct_student_profile(STUDENT)


# ---------------------------------------------------------------------------
# 4. "Delete My Biometric Data" (DPDP Sec. 12(2), 8(7)) — real delete
# ---------------------------------------------------------------------------
def test_delete_my_biometric_data_removes_templates_and_legacy(pdb):
    summary = priv.delete_my_biometric_data(STUDENT)
    assert summary["face_templates_deleted"] == 2
    assert summary["voice_templates_deleted"] == 1
    assert pdb.tables["face_embeddings"] == []
    assert pdb.tables["voice_embeddings"] == []
    student = pdb.tables["students"][0]
    assert student["face_embedding"] is None
    assert student["voice_embedding"] is None
    # Attendance (the academic record) and the identity row survive.
    assert pdb.tables["attendance_logs"] != []
    assert student["name"] == "Asha"
    audit = _audit_rows(pdb, "biometric_data_erased")
    assert len(audit) == 1
    assert audit[0]["details"]["face_templates_deleted"] == 2
    blob = json.dumps(audit[0])
    assert "0.1" not in blob and "embedding" not in audit[0]["details"]


def test_delete_my_biometric_data_is_idempotent(pdb):
    priv.delete_my_biometric_data(STUDENT)
    second = priv.delete_my_biometric_data(STUDENT)
    assert second["face_templates_deleted"] == 0
    assert second["voice_templates_deleted"] == 0


# ---------------------------------------------------------------------------
# 5. Breach logging (DPDP Sec. 8(5)-(6)) — counts, never personal data
# ---------------------------------------------------------------------------
def test_breach_log_records_counts_not_identities(pdb):
    details = priv.log_breach_event(
        breach_id="BR-2026-001",
        description="Worker host disk imaged by mistake",
        categories=["face_templates"],
        affected_student_ids=[STUDENT, STUDENT2],
        notified_board=False,
        notified_principals=False,
    )
    assert details["affected_count"] == 2
    assert details["notified_board"] is False
    audit = _audit_rows(pdb, "security_breach")
    assert len(audit) == 1
    blob = json.dumps(audit[0])
    assert STUDENT not in blob and STUDENT2 not in blob
    assert "BR-2026-001" in blob


def test_breach_log_requires_breach_id_description_categories(pdb):
    with pytest.raises(ValueError):
        priv.log_breach_event(breach_id="", description="x", categories=["a"])
    with pytest.raises(ValueError):
        priv.log_breach_event(breach_id="B1", description="x", categories=[])


def test_audit_never_accepts_forbidden_keys(pdb):
    with pytest.raises(ValueError):
        priv._audit("template_access", STUDENT, {"embedding": [0.1, 0.2]})
    with pytest.raises(ValueError):
        priv._audit("template_access", STUDENT, {"photo": b"bytes"})
    with pytest.raises(ValueError):
        priv._audit("template_access", STUDENT, {"pin": "1234"})


# ---------------------------------------------------------------------------
# 6. Template-access audit logging (GDPR Art. 9) — UI match path
# ---------------------------------------------------------------------------
def test_match_faces_writes_template_access_audit(monkeypatch, fake_db):
    monkeypatch.setattr(priv, "supabase", fake_db)
    fake_db.tables.setdefault("audit_log", [])
    fake_db.rpc_data["match_faces"] = [
        {"student_id": STUDENT, "cosine_similarity": 0.9},
    ]
    from src.database import vector
    results = vector.match_faces(SUBJECT, [0.01] * 512, client=fake_db)
    assert len(results) == 1
    audit = _audit_rows(fake_db, "template_access")
    assert len(audit) == 1
    assert audit[0]["details"]["template_kind"] == "face"
    assert audit[0]["details"]["access"] == "match"
    assert audit[0]["record_id"] == STUDENT
    assert "0.01" not in json.dumps(audit[0])


def test_match_faces_still_returns_results_when_audit_sink_fails(monkeypatch, fake_db):
    # Audit failure must never break matching: make the privacy audit
    # insert raise, and matching must still return its results.
    fake_db.rpc_data["match_faces"] = [
        {"student_id": STUDENT, "cosine_similarity": 0.9},
    ]
    from src.database import vector

    def _broken_audit(*args, **kwargs):
        raise RuntimeError("audit_log unavailable")

    monkeypatch.setattr(priv, "_audit", _broken_audit)
    results = vector.match_faces(SUBJECT, [0.01] * 512, client=fake_db)
    assert len(results) == 1


def test_log_template_access_validates_kind(pdb):
    with pytest.raises(ValueError):
        priv.log_template_access(STUDENT, template_kind="fingerprint", action="match")
    priv.log_template_access(STUDENT, template_kind="voice", action="verify_1to1",
                             subject_id=SUBJECT, matched=True)
    audit = _audit_rows(pdb, "template_access")
    assert audit[0]["details"]["template_kind"] == "voice"
    assert audit[0]["details"]["matched"] is True


# ---------------------------------------------------------------------------
# 7. Worker template-access audit (gallery load + match, mocked)
# ---------------------------------------------------------------------------
def test_gallery_load_audits_template_read_without_vectors():
    from worker.gallery import GalleryLoader

    class FakeClient:
        def table(self, name):
            return self
        def select(self, cols):
            return self
        def eq(self, col, val):
            return self
        def in_(self, col, vals):
            return self
        def execute(self):
            class R:
                data = [
                    {"student_id": STUDENT, "vector": [0.1] * 512},
                ]
            return R()

    # subject_students lookup returns the enrolled id first, then the
    # embeddings query; the fake returns the same rows for both calls.
    events = []
    loader = GalleryLoader(
        config=type("C", (), {"supabase_url": "https://x", "supabase_service_role_key": "k"})(),
        client=FakeClient(),
        on_template_access=events.append,
    )
    gallery = loader.load_face_gallery(SUBJECT)
    assert STUDENT in gallery
    assert len(events) == 1
    assert events[0]["template_kind"] == "face"
    assert events[0]["access"] == "gallery_load"
    assert events[0]["students_loaded"] == 1
    assert "vector" not in json.dumps(events[0])
    assert "0.1" not in json.dumps(events[0])


def test_runner_face_job_audits_match_without_vectors():
    from worker.runner import run_face_job

    class FakeGallery:
        def load_face_gallery(self, subject_id):
            return {STUDENT: [np.ones(512, dtype=np.float32)]}

    class FakeFacePipeline:
        def match_group(self, img, gallery):
            return {"detected": {STUDENT: {"cosine": 0.9, "margin": 0.2, "face_index": 0}},
                    "num_faces": 1, "low_quality_face_indices": []}

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(buf, format="JPEG")
    events = []
    ctx = {"audit_template_access": events.append}
    result = run_face_job(buf.getvalue(), SUBJECT, [STUDENT], FakeGallery(),
                          FakeFacePipeline(), ctx=ctx)
    assert result["detected"][STUDENT]["cosine"] == 0.9
    assert len(events) == 1
    assert events[0]["template_kind"] == "face"
    assert events[0]["matched_student_ids"] == [STUDENT]
    assert events[0]["students_compared"] == 1


# ---------------------------------------------------------------------------
# 8. Non-biometric fallback is explicit (GDPR Art. 9 / AEPD)
# ---------------------------------------------------------------------------
def test_non_biometric_fallback_is_explicit_in_ui_and_docs():
    screen = (REPO / "src/screen/student_screen.py").read_text(encoding="utf-8")
    assert "No face or voice needed" in screen
    assert "with no penalty" in screen
    assert "My data & privacy" in screen
    assert "Delete My Biometric Data" in screen
    assert "Withdraw biometric consent" in screen
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "non-biometric" in readme.lower()
    assert "PIN" in readme
    # The session methods include the non-biometric ones.
    assert "pin" in dbmod.SESSION_METHODS
    assert "manual" in dbmod.SESSION_METHODS


def test_privacy_notice_text_covers_required_points():
    text = priv.PRIVACY_NOTICE_TEXT
    for phrase in ("never stored", "no penalty", "withdraw",
                   "under 18", "delete your face/voice templates"):
        assert phrase in text
    assert priv.PRIVACY_NOTICE_VERSION == "1.0"
    # Grievance contact is a clearly-marked placeholder, never a real inbox.
    assert priv.GRIEVANCE_CONTACT["email"].endswith(".invalid")
    assert "TO BE CONFIGURED" in priv.GRIEVANCE_CONTACT["name"]
    assert priv.GRIEVANCE_CONTACT["response_within_days"] == 90


# ---------------------------------------------------------------------------
# 9. No raw photo/audio retention (SPEC constraint)
# ---------------------------------------------------------------------------
_MEDIA_PATHS = [
    "worker/runner.py", "worker/app.py", "worker/stores.py",
    "worker/gallery.py", "src/ui/uploads.py", "src/ui/worker_client.py",
    "src/pipelines/face_pipeline.py", "src/pipelines/voice_pipeline.py",
    "src/screen/student_screen.py", "src/screen/student_face_dialog.py",
    "src/components/dialog_add_photo.py",
]

_WRITE_PATTERNS = [
    re.compile(r"""\bopen\s*\([^)]*,\s*["'][wax][b+t]?["']"""),
    re.compile(r"""\btempfile\b"""),
    re.compile(r"""\bos\.write\b"""),
    re.compile(r"""Path\s*\([^)]*\)\s*\.\s*write_(?:bytes|text)\b"""),
    re.compile(r"""\.write_bytes\s*\("""),
    re.compile(r"""storage.*\.upload\b""", re.IGNORECASE),
    re.compile(r"""supabase\.storage"""),
]


def test_no_raw_media_written_to_disk_or_object_storage():
    offenders = []
    for rel in _MEDIA_PATHS:
        text = (REPO / rel).read_text(encoding="utf-8")
        for pat in _WRITE_PATTERNS:
            for m in pat.finditer(text):
                offenders.append(f"{rel}: {m.group(0)!r}")
    assert offenders == [], (
        "Raw media must be processed in memory and deleted after "
        f"inference, never written to disk/object storage: {offenders}"
    )


def test_worker_payload_deleted_after_processing_even_on_failure():
    from worker.runner import process_one_job
    from worker.stores import MemoryJobStore
    from worker.config import WorkerConfig

    class FakeGallery:
        def load_face_gallery(self, subject_id):
            return {}
        def load_voice_gallery(self, subject_id):
            return {}

    class FakeFacePipeline:
        def match_group(self, img, gallery):
            return {"detected": {}, "num_faces": 0, "low_quality_face_indices": []}

    store = MemoryJobStore()
    job = store.create_job("face", subject_id=SUBJECT, candidate_ids=[])
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buf, format="JPEG")
    store.put_payload(job["id"], buf.getvalue())
    ctx = {"config": WorkerConfig(), "gallery_loader": FakeGallery(),
           "face_pipeline": FakeFacePipeline(),
           "diarizer": None, "embedder": None}
    done = process_one_job(store, ctx)
    assert done["status"] == "done"
    assert store.take_payload(job["id"]) is None  # raw photo deleted
    assert store.payloads == {}
    # And on failure: a bad payload is also dropped, not kept.
    bad = store.create_job("face", subject_id=SUBJECT, candidate_ids=[])
    store.put_payload(bad["id"], b"not-an-image")
    done = process_one_job(store, ctx)
    assert done["status"] == "failed"
    assert store.take_payload(bad["id"]) is None
    assert store.payloads == {}


def test_uploads_process_only_in_memory():
    from src.ui.uploads import process_upload
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, format="JPEG")
    out = process_upload(buf.getvalue(), kind="login")
    assert out["sha256"]
    assert out["image_bytes"]
    # Nothing on disk: the module writes only to BytesIO (covered by
    # the static scan above); here assert the ingest round-trips bytes.
    assert Image.open(io.BytesIO(out["image_bytes"])).size[0] <= 720


# ---------------------------------------------------------------------------
# 10. Unenrol confirmation + transactional subject delete (audit 51)
# ---------------------------------------------------------------------------
def test_unenrol_requires_confirmation_step():
    screen = (REPO / "src/screen/student_screen.py").read_text(encoding="utf-8")
    assert "confirm_unenroll_" in screen
    assert "Yes, unenroll" in screen
    assert "Keep me enrolled" in screen
    # The unenrol call must only happen inside the confirmation branch.
    assert screen.count("unenroll_student_to_subject(stud_id, bound_sid)") == 1


def test_transactional_subject_delete_uses_rpc(monkeypatch, fake_db):
    monkeypatch.setattr(dbmod, "supabase", fake_db)
    fake_db.rpc_data["delete_subject_tx"] = [{
        "subject_id": SUBJECT, "attendance_logs_deleted": 1,
        "attendance_sessions_deleted": 0, "enrolments_deleted": 1,
    }]
    result = dbmod.delete_subject_transactional(SUBJECT, teacher_id=TEACHER)
    assert result["attendance_logs_deleted"] == 1
    assert fake_db.last_rpc[0] == "delete_subject_tx"
    assert fake_db.last_rpc[1] == {"p_subject_id": SUBJECT, "p_teacher_id": TEACHER}
    # Nothing was deleted by the app layer itself: the RPC owns it.
    assert len(fake_db.tables["subjects"]) == 2


def test_transactional_subject_delete_blocks_other_teacher(monkeypatch, fake_db):
    monkeypatch.setattr(dbmod, "supabase", fake_db)
    with pytest.raises(PermissionError):
        dbmod.delete_subject_transactional(SUBJECT, teacher_id=OTHER_TEACHER)
    assert fake_db.last_rpc is None  # RPC never called


def test_delete_dialog_uses_transactional_delete():
    dialog = (REPO / "src/components/dialog_delete_subject.py").read_text(encoding="utf-8")
    assert "delete_subject_transactional" in dialog


# ---------------------------------------------------------------------------
# 11. XSRF / CORS stay on (audit 44)
# ---------------------------------------------------------------------------
def test_xsrf_and_cors_protection_on():
    # devcontainer.json has // comments, so check the actual command
    # (comment lines stripped) rather than the prose around it.
    lines = [
        line for line in (REPO / ".devcontainer/devcontainer.json").read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("//")
    ]
    devcontainer = "\n".join(lines)
    assert "enableCORS false" not in devcontainer
    assert "enableXsrfProtection false" not in devcontainer
    assert "streamlit run app.py" in devcontainer
    config = (REPO / ".streamlit/config.toml").read_text(encoding="utf-8")
    assert "enableXsrfProtection = true" in config
    assert "enableCORS = true" in config


# ---------------------------------------------------------------------------
# 12. Example secrets contain placeholders only — no real secrets
# ---------------------------------------------------------------------------
def test_local_secret_files_stay_gitignored():
    rules = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in rules
    assert ".streamlit/*" in rules
    assert "!.streamlit/config.toml" in rules
    assert "!.streamlit/secrets.toml.example" in rules


# ---------------------------------------------------------------------------
# 13. Migration 005 exists and is honest about encryption
# ---------------------------------------------------------------------------
def test_migration_005_privacy_tables_and_rpc():
    sql = (REPO / "migrations/005_phase3_privacy.sql").read_text(encoding="utf-8")
    assert "consent_records" in sql
    assert "parental_consents" in sql
    assert "date_of_birth" in sql
    assert "delete_subject_tx" in sql
    assert "begin;" in sql and "commit;" in sql
    # Honest about encryption: platform setting, not app-level.
    assert "NOT app-level" in sql or "platform setting" in sql.lower()
    assert "cancelable" in sql.lower()


def test_privacy_docs_exist_and_mark_cancelable_templates_future():
    notice = (REPO / "docs/privacy/privacy-notice.md").read_text(encoding="utf-8")
    assert "Sec. 6(4)" in notice  # withdrawal — verified, not 6(5)
    assert "Sec. 8(7)" in notice  # erasure
    assert "Sec. 13" in notice
    dpia = (REPO / "docs/privacy/dpia.md").read_text(encoding="utf-8")
    assert "non-biometric fallback" in dpia.lower()
    assert "Supabase platform setting" in dpia
    cancelable = (REPO / "docs/privacy/cancelable-templates.md").read_text(encoding="utf-8")
    assert "NOT BUILT" in cancelable
    assert "24745" in cancelable


def test_lockfiles_exist_and_exclude_unused_direct_deps():
    ui_lock = (REPO / "requirements-ui.lock").read_text(encoding="utf-8")
    worker_lock = (REPO / "worker/requirements.lock").read_text(encoding="utf-8")
    assert "argon2-cffi==" in ui_lock
    assert "scipy==" in ui_lock
    assert "httpx==" in ui_lock
    assert "onnxruntime==" in worker_lock
    # scikit-learn / webrtcvad are not direct deps anywhere; no code
    # imports them (checked by grep in the report). sklearn appears
    # in the worker lock ONLY as a transitive dep of speechbrain/pyannote.
    # (requirements.txt mentions scikit-learn in a comment explaining
    # its removal — comments do not count.)
    for rel in ("requirements.txt", "requirements-ui.txt", "worker/requirements.txt"):
        req_lines = [
            line for line in (REPO / rel).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert not any("scikit-learn" in line or "webrtcvad" in line for line in req_lines), rel
    assert "webrtcvad" not in ui_lock
    assert "webrtcvad" not in worker_lock
