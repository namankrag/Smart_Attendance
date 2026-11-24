"""Phase 1 regression tests.

Covers: shared ISO parsing, pgvector RPC helpers, Google-first auth
session (mocked — no real Google), rehash write-back, voice helper,
paginated/filtered records + streaming CSV, SQL-view counts,
per-student gallery cache, missing-image tolerance, html escaping,
and the PIN-login fail-closed fix for an unavailable rate-limit store.
"""

import base64
import csv
import io
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import streamlit as st

# NOTE: import the pytest-loaded conftest module by its top-level name.
# `from tests.conftest import ...` would RE-EXECUTE conftest.py as a
# second module, replacing sys.modules["streamlit"] with a second fake
# — and then `st` here and `st` in src.* would be different objects,
# so monkeypatching st.login / st.session_state would silently miss.
import conftest as _conftest

FakeSupabase = _conftest.FakeSupabase
from src.database import db as dbmod  # noqa: E402
from src.database import vector as vectormod  # noqa: E402
from src.database.auth import hash_password  # noqa: E402
from src.database.timeutil import parse_iso_timestamp, format_iso_timestamp  # noqa: E402
from src.database.logging_utils import log_exception, new_correlation_id  # noqa: E402
from src.ui.images import img_to_base64, image_file  # noqa: E402
from src.components.dialog_utils import dialog_banner  # noqa: E402

TEACHER = "33333333-3333-3333-3333-333333333333"
SUBJECT = "44444444-4444-4444-4444-444444444444"
SUBJECT2 = "55555555-5555-5555-5555-555555555555"
STUDENT = "11111111-1111-1111-1111-111111111111"
STUDENT2 = "22222222-2222-2222-2222-222222222222"
REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Shared ISO parsing (one helper, never crashes on bad input)
# ---------------------------------------------------------------------------


def test_parse_iso_timestamp_valid_and_bad():
    assert parse_iso_timestamp("2026-09-01T00:00:00+00:00") == datetime(
        2026, 9, 1, tzinfo=timezone.utc
    )
    assert parse_iso_timestamp("2026-09-01T00:00:00Z") == datetime(2026, 9, 1, tzinfo=timezone.utc)
    # Naive input is assumed UTC, not crashed on.
    assert parse_iso_timestamp("2026-09-01T00:00:00").tzinfo is not None
    assert isinstance(parse_iso_timestamp(datetime(2026, 1, 1)), datetime)
    for bad in (None, "", "not a date", "2026-13-40T99:99:99", 12345, ["x"]):
        assert parse_iso_timestamp(bad) is None


def test_format_iso_timestamp_never_raises():
    assert format_iso_timestamp("2026-09-01T10:30:00+00:00") == "2026-09-01 10:30 AM"
    assert format_iso_timestamp("garbage") == "N/A"
    assert format_iso_timestamp(None) == "N/A"


def test_student_screen_uses_shared_parser():
    src = (REPO / "src" / "screen" / "student_screen.py").read_text(encoding="utf-8")
    assert "from src.database.timeutil import parse_iso_timestamp" in src
    assert "datetime.fromisoformat(str(value)" not in src


# ---------------------------------------------------------------------------
# Structured logging with correlation IDs
# ---------------------------------------------------------------------------


def test_log_exception_returns_id_and_json_line(caplog):
    logger = logging.getLogger("phase1-test-logger")
    with caplog.at_level(logging.ERROR, logger="phase1-test-logger"):
        try:
            raise ValueError("boom")
        except ValueError:
            cid = log_exception(logger, "test_event", identifier="u1")
    assert len(cid) == 12
    assert all(c in "0123456789abcdef" for c in cid)
    assert new_correlation_id() != cid
    line = caplog.records[-1].getMessage()
    payload = json.loads(line)
    assert payload["event"] == "test_event"
    assert payload["correlation_id"] == cid
    assert payload["identifier"] == "u1"


# ---------------------------------------------------------------------------
# pgvector helpers
# ---------------------------------------------------------------------------


def test_match_faces_validates_embedding():
    with pytest.raises(ValueError):
        vectormod.match_faces(SUBJECT, [0.1] * 128)  # legacy dlib dim: rejected
    with pytest.raises(ValueError):
        vectormod.match_faces(SUBJECT, [0.0] * 512)  # zero vector: no direction
    with pytest.raises(ValueError):
        vectormod.match_faces(SUBJECT, [float("nan")] * 512)
    with pytest.raises(ValueError):
        vectormod.match_faces(SUBJECT, [0.1] * 512, k=0)


def test_match_faces_calls_rpc(monkeypatch, fake_db):
    monkeypatch.setattr(vectormod, "supabase", fake_db)
    fake_db.rpc_data["match_faces"] = [{"student_id": STUDENT, "cosine_similarity": 0.97}]
    rows = vectormod.match_faces(SUBJECT, [0.1] * 512, k=3)
    assert rows[0]["student_id"] == STUDENT
    name, params = fake_db.last_rpc
    assert name == "match_faces"
    assert params["p_subject_id"] == SUBJECT
    assert params["p_k"] == 3
    assert len(params["p_query"]) == 512


def test_find_duplicate_face_owner_skips_excluded(monkeypatch, fake_db):
    monkeypatch.setattr(vectormod, "supabase", fake_db)
    fake_db.rpc_data["match_faces"] = [
        {"student_id": STUDENT, "cosine_similarity": 0.99},
        {"student_id": STUDENT2, "cosine_similarity": 0.98},
    ]
    assert vectormod.find_duplicate_face_owner([0.1] * 512, exclude_student_id=STUDENT) == STUDENT2
    fake_db.rpc_data["match_faces"] = []
    assert vectormod.find_duplicate_face_owner([0.1] * 512) is None


# ---------------------------------------------------------------------------
# Google-first auth session (mocked st.login / supabase)
# ---------------------------------------------------------------------------


def test_require_google_login_redirects_when_logged_out(monkeypatch):
    import src.database.auth_session as auth_sess

    calls = {}
    monkeypatch.setattr(st, "login", lambda provider: calls.setdefault("provider", provider))
    monkeypatch.setattr(st, "stop", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("stopped")))
    monkeypatch.setattr(st.user, "is_logged_in", False)
    with pytest.raises(RuntimeError, match="stopped"):
        auth_sess.require_google_login()
    assert calls["provider"] == "google"


def test_require_google_login_returns_user_when_logged_in(monkeypatch):
    import src.database.auth_session as auth_sess

    monkeypatch.setattr(st.user, "is_logged_in", True)
    assert auth_sess.require_google_login() is st.user


def test_authenticated_client_fails_closed_without_jwt(monkeypatch):
    import src.database.auth_session as auth_sess

    monkeypatch.setattr(st, "session_state", {})
    monkeypatch.setattr(st.user, "is_logged_in", False)
    monkeypatch.setattr(st.user, "access_token", None)
    monkeypatch.setattr(st.user, "id_token", None)
    with pytest.raises(RuntimeError, match="Google sign-in is required"):
        auth_sess.get_authenticated_supabase_client()


def test_authenticated_client_sends_jwt(monkeypatch):
    import src.database.auth_session as auth_sess

    class FakePostgrest:
        def __init__(self):
            self.token = None

        def auth(self, token):
            self.token = token

    class FakeClient:
        def __init__(self):
            self.postgrest = FakePostgrest()

    fake_client = FakeClient()
    monkeypatch.setattr(sys.modules["supabase"], "create_client", lambda *a, **k: fake_client)
    monkeypatch.setattr(
        st, "secrets", {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_KEY": "anon"}
    )
    monkeypatch.setattr(st, "session_state", {"supabase_access_token": "jwt-123"})
    client = auth_sess.get_authenticated_supabase_client()
    assert client is fake_client
    assert fake_client.postgrest.token == "jwt-123"  # noqa: S105  # dummy token in a test fixture


def test_exchange_google_id_token_stores_session(monkeypatch):
    import src.database.auth_session as auth_sess

    class FakeAuth:
        def sign_in_with_id_token(self, payload):
            assert payload == {"provider": "google", "token": "google-id-token"}
            return type(
                "R", (), {"session": {"access_token": "sb-jwt", "refresh_token": "sb-refresh"}}
            )()

    class FakeClient:
        def __init__(self):
            self.auth = FakeAuth()

    state = {}
    monkeypatch.setattr(st, "session_state", state)
    result = auth_sess.exchange_google_id_token("google-id-token", client=FakeClient())
    assert result["access_token"] == "sb-jwt"  # noqa: S105  # dummy token in a test fixture
    assert state["supabase_access_token"] == "sb-jwt"  # noqa: S105  # dummy token in a test fixture
    assert state["supabase_refresh_token"] == "sb-refresh"  # noqa: S105  # dummy token in a test fixture


def test_clear_session_on_logout_removes_namespaced_keys(monkeypatch):
    import src.database.auth_session as auth_sess

    state = {
        "theme": "dark",
        "student_data": {"student_id": STUDENT},
        "teacher_data": {"teacher_id": TEACHER},
        "smartclass_voice_x": "results",
        "reg_validated": b"bytes",
        "login_pin_val": "1234",
        "login_face_input": "photo",
        "modal_face_update_pin": "1",
        "supabase_access_token": "jwt",
        "current_teacher_tab": "take_attendance",
    }
    monkeypatch.setattr(st, "session_state", state)
    auth_sess.clear_session_on_logout()
    assert state["theme"] == "dark"  # non-identity preference is kept
    assert state["login_type"] is None
    assert state["is_logged_in"] is False
    for key in list(state):
        assert not key.startswith(
            ("smartclass_", "reg_", "login_pin_", "login_face", "modal_face_update")
        )
        assert key not in (
            "student_data",
            "teacher_data",
            "supabase_access_token",
            "current_teacher_tab",
        )


# ---------------------------------------------------------------------------
# Credential rehash write-back (carry-over a)
# ---------------------------------------------------------------------------


def test_teacher_login_with_rehash_upgrades_bcrypt(monkeypatch, fake_db):
    import bcrypt

    monkeypatch.setattr(dbmod, "supabase", fake_db)
    fake_db.tables["teachers"][0]["password"] = bcrypt.hashpw(
        b"secret123", bcrypt.gensalt()
    ).decode()
    result = dbmod.teacher_login_with_rehash("teach1", "secret123")
    assert result is not None
    teacher, needs_rehash = result
    assert "password" not in teacher  # hash never returned to callers
    assert needs_rehash is True
    dbmod.update_teacher_password_hash(teacher["teacher_id"], hash_password("secret123"))
    assert fake_db.tables["teachers"][0]["password"].startswith("$argon2id$")
    # Second login: current Argon2id hash, no rehash needed.
    assert dbmod.teacher_login_with_rehash("teach1", "secret123")[1] is False
    assert dbmod.teacher_login_with_rehash("teach1", "wrong") is None


def test_update_pin_hash_rejects_non_argon2(monkeypatch, fake_db):
    monkeypatch.setattr(dbmod, "supabase", fake_db)
    with pytest.raises(ValueError):
        dbmod.update_student_pin_hash(STUDENT, "plaintext")
    with pytest.raises(ValueError):
        dbmod.update_teacher_password_hash(TEACHER, "$2b$12$legacybcrypt")


def test_pin_login_rehash_writeback(monkeypatch, fake_db):
    """_handle_pin_login upgrades a legacy bcrypt PIN hash on success."""
    import bcrypt
    import src.screen.student_screen as ss

    class AttrDict(dict):
        """st.session_state supports attribute access in real Streamlit;
        the test stub's plain dict does not."""

        def __getattr__(self, name):
            try:
                return self[name]
            except KeyError:
                raise AttributeError(name) from None

        def __setattr__(self, name, value):
            self[name] = value

    monkeypatch.setattr(dbmod, "supabase", fake_db)
    pin_hash = bcrypt.hashpw(b"1234", bcrypt.gensalt()).decode()
    fake_db.tables["students"][0]["pin_hash"] = pin_hash
    student = dict(fake_db.tables["students"][0])
    monkeypatch.setattr(ss, "_login_allowed", lambda *a, **k: (True, 0))
    monkeypatch.setattr(ss, "_lookup_student_for_login", lambda ident: student)
    monkeypatch.setattr(ss, "_record_login_attempt", lambda *a, **k: None)
    monkeypatch.setattr(ss, "update_student_pin_hash", dbmod.update_student_pin_hash)
    monkeypatch.setattr(st, "session_state", AttrDict())
    ss._handle_pin_login("1MS21CS001", "1234")
    assert fake_db.tables["students"][0]["pin_hash"].startswith("$argon2id$")
    # The stored hash now verifies as current Argon2id (no rehash next time).
    from src.database.auth import verify_credential

    assert verify_credential("1234", fake_db.tables["students"][0]["pin_hash"]) == (True, False)


def test_pin_login_rate_limit_failure_fails_closed(monkeypatch):
    """Live finding 2026-11-22: an unavailable rate-limit store raised
    uncaught (StreamlitSecretNotFoundError) and crashed the app. It must
    fail closed with the generic login error instead."""
    import src.screen.student_screen as ss

    errors = []
    monkeypatch.setattr(st, "error", lambda *a, **k: errors.append(a[0] if a else ""))
    monkeypatch.setattr(
        ss,
        "_login_allowed",
        lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("StreamlitSecretNotFoundError: no secrets")
        ),
    )
    ss._handle_pin_login("1MS21CS001", "1234")  # must not raise
    assert errors == [ss.GENERIC_LOGIN_ERROR]


def test_face_login_uses_claimed_students_gallery(monkeypatch):
    """Face login compares against the row already fetched for this ID."""
    from PIL import Image
    import src.screen.student_auth as auth

    gallery = [[0.25] * 128]
    calls = {}

    def fake_predict(image, student_id, **kwargs):
        calls.update(student_id=student_id, **kwargs)
        return {"matched": True, "num_faces": 1}

    monkeypatch.setattr(auth, "predict_one_to_one", fake_predict)
    matched, num_faces = auth._verify_face_1to1(
        Image.new("RGB", (8, 8)),
        {"student_id": "student-1", "face_embedding": gallery},
    )

    assert (matched, num_faces) == (True, 1)
    assert calls["student_id"] == "student-1"
    assert calls["gallery_embeddings"] is gallery


# ---------------------------------------------------------------------------
# Voice embedding helper (carry-over b)
# ---------------------------------------------------------------------------


def test_update_voice_embedding(monkeypatch, fake_db):
    monkeypatch.setattr(dbmod, "supabase", fake_db)
    rows = dbmod.update_voice_embedding(STUDENT, [0.5] * 256)
    assert rows
    assert fake_db.tables["students"][0]["voice_embedding"] == [0.5] * 256
    for bad in ([], "not-a-list", [0.1, float("nan")], [0.1, "x"]):
        with pytest.raises(ValueError):
            dbmod.update_voice_embedding(STUDENT, bad)


def test_get_subject_by_id(monkeypatch, fake_db):
    monkeypatch.setattr(dbmod, "supabase", fake_db)
    assert dbmod.get_subject_by_id(SUBJECT)["name"] == "Mini Project"
    assert dbmod.get_subject_by_id("nope") is None


# ---------------------------------------------------------------------------
# Paginated / filtered records, SQL-view counts, streaming CSV
# ---------------------------------------------------------------------------


def _records_fake():
    def log(log_id, subject, ts, present, student=STUDENT, name="Asha"):
        return {
            "id": log_id,
            "session_id": f"s-{log_id}",
            "student_id": student,
            "subject_id": subject,
            "timestamp": ts,
            "is_present": present,
            "subjects": {
                "subject_id": subject,
                "name": "Mini Project",
                "subject_code": "MPW",
                "teacher_id": TEACHER,
            },
            "students": {"student_id": student, "usn": "1MS21CS001", "name": name},
        }

    return FakeSupabase(
        {
            "attendance_logs": [
                log("l1", SUBJECT, "2026-09-02T10:00:00+00:00", True),
                log("l2", SUBJECT, "2026-09-01T10:00:00+00:00", False),
                log("l3", SUBJECT2, "2026-09-03T10:00:00+00:00", True, name="Doe, Jane"),
            ],
            "v_session_counts": [
                {
                    "subject_id": SUBJECT,
                    "total_classes": 3,
                    "first_session_at": "2026-09-01T10:00:00+00:00",
                    "last_session_at": "2026-09-03T10:00:00+00:00",
                },
            ],
            "v_attendance_percentages": [
                {
                    "student_id": STUDENT,
                    "subject_id": SUBJECT,
                    "total_classes": 3,
                    "present_classes": 2,
                    "attendance_pct": 66.67,
                },
            ],
        }
    )


def test_get_attendance_records_pagination_and_filters(monkeypatch):
    fake = _records_fake()
    monkeypatch.setattr(dbmod, "supabase", fake)
    page1 = dbmod.get_attendance_records(TEACHER, limit=2, offset=0)
    assert [r["id"] for r in page1] == ["l3", "l1"]  # newest first
    page2 = dbmod.get_attendance_records(TEACHER, limit=2, offset=2)
    assert [r["id"] for r in page2] == ["l2"]
    assert [r["id"] for r in dbmod.get_attendance_records(TEACHER, subject_id=SUBJECT)] == [
        "l1",
        "l2",
    ]
    assert [r["id"] for r in dbmod.get_attendance_records(TEACHER, is_present=True)] == ["l3", "l1"]
    assert [
        r["id"] for r in dbmod.get_attendance_records(TEACHER, start="2026-09-02T00:00:00+00:00")
    ] == ["l3", "l1"]
    with pytest.raises(ValueError):
        dbmod.get_attendance_records(TEACHER, start="not-a-date")


def test_count_attendance_for_teacher(monkeypatch):
    fake = _records_fake()
    monkeypatch.setattr(dbmod, "supabase", fake)
    assert dbmod.count_attendance_for_teacher(TEACHER) == 3
    assert dbmod.count_attendance_for_teacher(TEACHER, subject_id=SUBJECT) == 2
    assert dbmod.count_attendance_for_teacher(TEACHER, is_present=False) == 1
    assert dbmod.count_attendance_for_teacher("other-teacher") == 0


def test_sql_view_counts(monkeypatch):
    fake = _records_fake()
    monkeypatch.setattr(dbmod, "supabase", fake)
    counts = dbmod.get_session_counts(SUBJECT)
    assert counts["total_classes"] == 3
    assert dbmod.get_session_counts(SUBJECT2)["total_classes"] == 0
    pct = dbmod.get_attendance_percentage(STUDENT, SUBJECT)
    assert pct == {"total_classes": 3, "present_classes": 2, "attendance_pct": 66.67}
    assert dbmod.get_attendance_percentage(STUDENT, SUBJECT2)["attendance_pct"] is None


def test_iter_attendance_csv_streams_pages_and_quotes(monkeypatch):
    fake = _records_fake()
    monkeypatch.setattr(dbmod, "supabase", fake)
    chunks = list(dbmod.iter_attendance_csv(TEACHER, page_size=2))
    assert len(chunks) == 3  # header + 2 pages of 2/1 rows
    text = "".join(chunks)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == 3
    assert rows[0]["timestamp"] == "2026-09-03T10:00:00+00:00"
    assert rows[0]["student_name"] == "Doe, Jane"  # comma quoted, not split
    assert rows[0]["is_present"] == "True"
    assert list(rows[0].keys()) == [
        "timestamp",
        "subject_code",
        "subject_name",
        "student_usn",
        "student_name",
        "is_present",
    ]
    with pytest.raises(ValueError):
        list(dbmod.iter_attendance_csv(TEACHER, page_size=0))


# ---------------------------------------------------------------------------
# Per-student gallery cache (replaces the 5-minute st.cache_data gallery)
# ---------------------------------------------------------------------------


def test_gallery_scoped_to_roster_with_per_student_invalidation(monkeypatch):
    import src.pipelines.face_pipeline as fp

    store = {}
    monkeypatch.setattr(fp, "_gallery_store", lambda: store)
    fetched = []

    def fake_get_by_id(sid):
        fetched.append(sid)
        return {"student_id": sid, "face_embedding": [0.1] * 128}

    monkeypatch.setattr(fp, "get_student_by_id", fake_get_by_id)
    model = fp.get_trained_model([STUDENT, STUDENT2])
    assert model is not None
    assert set(model["student_ids"]) == {STUDENT, STUDENT2}
    assert fetched == [STUDENT, STUDENT2]
    # Second build for one student reuses the cache: no refetch.
    fetched.clear()
    fp.get_trained_model([STUDENT])
    assert fetched == []
    # Per-student invalidation refetches only that student.
    fp.invalidate_student_gallery(STUDENT)
    fp.get_trained_model([STUDENT])
    assert fetched == [STUDENT]
    assert fp.train_classifier(STUDENT) is True
    assert STUDENT not in store
    assert fp.train_classifier() is True
    assert store == {}


def test_no_five_minute_cache_data_gallery():
    src = (REPO / "src" / "pipelines" / "face_pipeline.py").read_text(encoding="utf-8")
    # The old decorator line (exact) must be gone; prose may still
    # mention the old caching approach for context.
    assert "@st.cache_data(ttl=300, show_spinner=False)" not in src
    assert "_fetch_and_build_embeddings_matrix.clear()" not in src
    assert "invalidate_student_gallery" in src


def test_find_duplicate_face_owner_uses_rpc_for_512d(monkeypatch):
    import src.pipelines.face_pipeline as fp

    monkeypatch.setattr(
        "src.database.vector.match_faces",
        lambda *a, **k: [{"student_id": STUDENT, "cosine_similarity": 0.91}],
    )
    assert fp.find_duplicate_face_owner([0.01] * 512) == STUDENT
    monkeypatch.setattr(
        "src.database.vector.match_faces",
        lambda *a, **k: [{"student_id": STUDENT, "cosine_similarity": 0.5}],
    )
    assert fp.find_duplicate_face_owner([0.01] * 512) is None


def test_find_duplicate_face_owner_local_128d():
    import src.pipelines.face_pipeline as fp

    query = [1.0] + [0.0] * 127
    assert fp.find_duplicate_face_owner(query, [(STUDENT, [1.0] + [0.0] * 127)]) == STUDENT
    assert fp.find_duplicate_face_owner(query, [(STUDENT, [0.0, 1.0] + [0.0] * 126)]) is None


# ---------------------------------------------------------------------------
# Missing-image tolerance (live finding 2026-11-22)
# ---------------------------------------------------------------------------


def test_img_files_restored_from_github():
    for name in ("header.png", "student.png", "teacher.png", "NKA.png"):
        data = (REPO / "img" / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", name


def test_img_to_base64_missing_returns_empty(tmp_path):
    assert img_to_base64(tmp_path / "nope.png") == ""
    assert image_file(tmp_path / "nope.png") is None


def test_img_to_base64_roundtrip(tmp_path):
    payload = b"\x89PNG\r\n\x1a\nfake-bytes"
    path = tmp_path / "a.png"
    path.write_bytes(payload)
    assert base64.b64decode(img_to_base64(path)) == payload
    assert image_file(path) == path


def test_header_footer_render_without_images(monkeypatch, tmp_path):
    import src.components.header as header_mod
    import src.components.footer as footer_mod

    class _CM:
        def __enter__(self):
            return None

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(st, "columns", lambda *a, **k: [_CM(), _CM()])
    monkeypatch.setattr(header_mod, "BASE_DIR", tmp_path)  # no img/ here
    monkeypatch.setattr(footer_mod, "BASE_DIR", tmp_path)
    header_mod.header_home()  # must not raise FileNotFoundError
    header_mod.header_dashboard()
    footer_mod.footer_home()
    footer_mod.footer_dashboard()


# ---------------------------------------------------------------------------
# html escaping (Phase 1 hygiene item 4)
# ---------------------------------------------------------------------------


def test_dialog_banner_escapes_user_text(monkeypatch):
    captured = {}
    monkeypatch.setattr(st, "markdown", lambda text, **k: captured.setdefault("text", text))
    dialog_banner("<script>alert(1)</script>", subtitle='"><img src=x onerror=alert(2)>')
    assert "<script>" not in captured["text"]
    assert "&lt;script&gt;" in captured["text"]
    assert "<img" not in captured["text"]


def test_no_raw_exception_detail_shown_in_ui():
    src = (REPO / "src" / "components" / "dialog_attend_result.py").read_text(encoding="utf-8")
    assert 'st.error(f"❌ Sync failed: {e}")' not in src
    assert "Could not save attendance" in src


def test_screens_escape_dynamic_names():
    for rel in (
        "src/screen/teacher_screen.py",
        "src/screen/student_screen.py",
        "src/components/dialog_session_detail.py",
    ):
        assert "html.escape(" in (REPO / rel).read_text(encoding="utf-8"), rel
