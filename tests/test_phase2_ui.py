"""Phase 2.1 UI regression tests (mocked; no Streamlit server, no network).

Covers: upload ingest (downscale/hash/thumbnail), time-limited join
codes, font loading via <link> (no @import), cached logo, no
time.sleep() after toasts, worker client, fragments, screen splits.
"""

import base64
import io
import sys
from pathlib import Path

import pytest
from PIL import Image

REPO = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO)


def _jpeg(w, h, color="red"):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="JPEG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Upload ingest (src/ui/uploads.py)
# ---------------------------------------------------------------------------
def test_upload_group_downscales_to_2560():
    from src.ui.uploads import process_upload, GROUP_MAX_LONG_EDGE

    out = process_upload(_jpeg(4000, 3000), kind="group")
    assert max(out["image"].size) == GROUP_MAX_LONG_EDGE
    assert max(out["thumbnail"].size) <= 1024
    assert len(out["sha256"]) == 64


def test_upload_login_downscales_to_720():
    from src.ui.uploads import process_upload, LOGIN_MAX_LONG_EDGE

    out = process_upload(_jpeg(2000, 1500), kind="login")
    assert max(out["image"].size) == LOGIN_MAX_LONG_EDGE


def test_upload_small_image_unchanged():
    from src.ui.uploads import process_upload

    out = process_upload(_jpeg(100, 80), kind="group")
    assert out["image"].size == (100, 80)


def test_upload_sha256_is_stable_and_hex():
    from src.ui.uploads import sha256_bytes, process_upload

    data = _jpeg(50, 50)
    assert process_upload(data, kind="group")["sha256"] == sha256_bytes(data)
    assert (
        process_upload(data, kind="group")["sha256"] == process_upload(data, kind="group")["sha256"]
    )


def test_upload_unknown_kind_fails():
    from src.ui.uploads import process_upload

    with pytest.raises(ValueError):
        process_upload(_jpeg(10, 10), kind="nope")


def test_dialog_add_photo_dedupes_by_sha256_and_stores_2560_bytes():
    import streamlit as st
    from src.components.dialog_add_photo import _add_images_to_state, staged_image_bytes

    class FakeUpload:
        def __init__(self, data, name="photo.jpg"):
            self._data = data
            self.name = name
            self._buf = io.BytesIO(data)

        def getvalue(self):
            return self._data

        def read(self, *a):
            return self._buf.read(*a)

        def seek(self, *a):
            return self._buf.seek(*a)

        def tell(self):
            return self._buf.tell()

    st.session_state.clear()
    data = _jpeg(3000, 2000)
    assert _add_images_to_state([FakeUpload(data)]) == 1
    # Same bytes again: deduped, not staged twice.
    assert _add_images_to_state([FakeUpload(data)]) == 0
    assert len(st.session_state["attendance_images"]) == 1
    # Only a thumbnail is kept for display...
    assert max(st.session_state["attendance_images"][0].size) <= 1024
    # ...while the 2560 px ingest copy is keyed by hash for the worker.
    staged = staged_image_bytes()
    assert len(staged) == 1
    ingest = Image.open(io.BytesIO(next(iter(staged.values()))))
    assert max(ingest.size) == 2560


# ---------------------------------------------------------------------------
# Join codes (src/ui/join_codes.py)
# ---------------------------------------------------------------------------
def test_join_code_is_time_limited():
    from src.ui.join_codes import generate_join_code, validate_join_code

    code = generate_join_code(ttl_seconds=3600, now=1_700_000_000)
    assert validate_join_code(code, now=1_700_000_100) == code
    assert validate_join_code(code, now=1_700_003_601) is None  # expired
    assert validate_join_code("not a code!!") is None


def test_join_code_url_encoding_round_trip():
    from src.ui.join_codes import build_join_url, generate_join_code, validate_join_code

    code = generate_join_code(ttl_seconds=3600, now=1_700_000_000)
    url = build_join_url("https://example.com/", code)
    assert "?join-code=" in url
    raw = url.split("?join-code=", 1)[1]
    assert validate_join_code(raw, now=1_700_000_100) == code


def test_legacy_join_code_still_validates():
    from src.ui.join_codes import validate_join_code

    assert validate_join_code("abc-123_XYZ") == "abc-123_XYZ"


def test_auto_enroll_clears_join_code_param_on_open():
    # The dialog must clear ?join-code as soon as it opens (audit 31):
    # assert on the source — the dialog body clears query params before
    # any lookup, and app.py clears before calling it.
    src = (Path(REPO) / "src/components/dialog_auto_enroll.py").read_text()
    assert "st.query_params.clear()" in src
    assert src.index("st.query_params.clear()") < src.index("get_subject_by_join_code(clean_code)")


# ---------------------------------------------------------------------------
# Fonts, logo, fragments, no-sleep
# ---------------------------------------------------------------------------
def test_fonts_loaded_via_link_not_import():
    from src.ui.theme import FONT_LINK_TAG

    assert "<link" in FONT_LINK_TAG and "fonts.googleapis.com" in FONT_LINK_TAG
    base = (Path(REPO) / "src/ui/base_layout.py").read_text()
    assert "@import url(" not in base
    assert "load_fonts()" in base


def test_logo_is_cached(monkeypatch):
    from src.ui import images

    # cache_resource stub is an identity decorator; the test asserts the
    # cached entry point exists and degrades on a missing file.
    assert images.cached_logo_base64("/nonexistent/logo.png") == ""
    assert images.cached_logo_base64 is not None


def test_no_time_sleep_after_toasts():
    # Audit 42: time.sleep() after toasts is gone. The only remaining
    # sleep is the bounded retry backoff in config.db_retry_read —
    # never after a toast.
    for path in list(Path(REPO, "src/screen").glob("*.py")) + list(
        Path(REPO, "src/components").glob("*.py")
    ):
        assert "time.sleep" not in path.read_text(), f"time.sleep in {path}"
    assert "time.sleep" in (Path(REPO) / "src/database/config.py").read_text()


def test_style_base_layout_renders_without_import(monkeypatch):
    import streamlit as st
    from src.ui.base_layout import style_base_layout

    seen = []
    monkeypatch.setattr(st, "html", lambda *a, **k: seen.append(a[0] if a else ""))
    style_base_layout()
    assert seen, "style_base_layout should emit html"
    assert all("@import" not in s for s in seen)


def test_fragments_importable_and_job_poller_marks_done(monkeypatch):
    import streamlit as st
    from src.ui import fragments
    from src.ui.worker_client import WorkerClient

    calls = {"n": 0}

    def fake_get(url, timeout):
        calls["n"] += 1
        return {
            "id": "j1",
            "status": "done",
            "progress": 100,
            "result": {"detected": {}},
            "error": None,
        }

    client = WorkerClient("http://worker:8000", http_get=fake_get)
    st.session_state.clear()
    st.session_state[fragments.PENDING_JOB_KEY] = {"job_ids": ["j1"]}
    reran = {"n": 0}
    monkeypatch.setattr(st, "rerun", lambda *a, **k: reran.__setitem__("n", reran["n"] + 1))
    monkeypatch.setattr(st, "progress", lambda *a, **k: None, raising=False)
    fragments.job_progress_fragment(client, "j1")
    assert st.session_state.get(fragments.JOB_RESULT_KEY, {}).get("status") == "done"
    assert fragments.PENDING_JOB_KEY not in st.session_state


# ---------------------------------------------------------------------------
# Worker client (src/ui/worker_client.py)
# ---------------------------------------------------------------------------
def test_worker_client_submit_and_poll_with_fake_transport():
    from src.ui.worker_client import WorkerClient

    posted = {}

    def fake_post(url, payload, headers, timeout):
        posted["url"] = url
        import json

        assert json.loads(payload)["type"] == "face"
        return {"id": "job-1", "status": "queued", "progress": 0}

    def fake_get(url, timeout):
        assert url.endswith("/jobs/job-1")
        return {
            "id": "job-1",
            "status": "done",
            "progress": 100,
            "result": {"detected": {}},
            "error": None,
        }

    client = WorkerClient("http://worker:8000/", http_post=fake_post, http_get=fake_get)
    assert client.base_url == "http://worker:8000"
    job = client.submit_job(
        "face", subject_id="s1", candidate_ids=["a"], payload_b64=base64.b64encode(b"img").decode()
    )
    assert job["id"] == "job-1" and posted["url"].endswith("/jobs")
    assert client.get_job("job-1")["status"] == "done"


def test_worker_client_rejects_unknown_type():
    from src.ui.worker_client import WorkerClient

    client = WorkerClient("http://worker:8000")
    with pytest.raises(ValueError):
        client.submit_job("photo")


def test_worker_client_submit_failure_raises_worker_error():
    from src.ui.worker_client import WorkerClient, WorkerError
    import urllib.error

    def boom(url, payload, headers, timeout):
        raise urllib.error.URLError("down")

    client = WorkerClient("http://worker:8000", http_post=boom)
    with pytest.raises(WorkerError):
        client.submit_job("face")


def test_get_worker_client_none_when_unconfigured(monkeypatch):
    from src.ui.worker_client import get_worker_client

    monkeypatch.delenv("ML_WORKER_URL", raising=False)
    assert get_worker_client() is None
    monkeypatch.setenv("ML_WORKER_URL", "http://worker:8000")
    assert get_worker_client() is not None


# ---------------------------------------------------------------------------
# Screen splits keep public names working
# ---------------------------------------------------------------------------
def test_screen_split_reexports():
    from src.screen.student_screen import (
        clear_student_session,
        _login_allowed,
    )
    from src.screen.student_auth import _login_allowed as _la2, clear_student_session as _cs2
    from src.screen.teacher_screen import (
        register_teacher_action,
        _row_usn,
    )
    from src.screen.teacher_auth import register_teacher_action as _ra2
    from src.screen.teacher_roster import _row_usn as _ru2

    assert _login_allowed is _la2
    assert clear_student_session is _cs2
    assert register_teacher_action is _ra2
    assert _row_usn is _ru2
    assert _row_usn({"USN": " 1MS21CS001 "}) == "1MS21CS001"


def test_teacher_jobs_present_result_uses_dialog(monkeypatch):
    from src.screen import teacher_jobs

    seen = {}
    monkeypatch.setattr(
        teacher_jobs,
        "attend_result",
        lambda df, logs, subject_name=None: seen.setdefault("called", (df, logs, subject_name)),
    )
    teacher_jobs.present_attendance_result(
        [{"student_id": "s1", "name": "Asha"}], {"s1": ["Photo 1"]}, "sub-1", "Maths (MPW)"
    )
    df, logs, subject_name = seen["called"]
    assert subject_name == "Maths (MPW)"
    assert df.iloc[0]["Status"] == "✅ Present"
    assert logs[0]["is_present"] is True


def test_header_uses_cached_logo():
    src = (Path(REPO) / "src/components/header.py").read_text()
    assert "cached_logo_base64" in src


def test_voice_job_poller_fragment_marks_done(monkeypatch):
    import streamlit as st
    from src.components import dialog_voice_attend as dva
    from src.ui.worker_client import WorkerClient

    def fake_get(url, timeout):
        return {
            "id": "j1",
            "status": "done",
            "progress": 100,
            "result": {"identified": {"s1": 0.9}},
            "error": None,
        }

    client = WorkerClient("http://worker:8000", http_get=fake_get)
    st.session_state.clear()
    key = "smartclass_voice_t1_sub1"
    st.session_state[f"{key}_voice_job_pending"] = {
        "job_id": "j1",
        "enroll_stud": [{"students": {"student_id": "s1", "name": "Asha"}}],
        "missing_voiceprint_names": [],
    }
    monkeypatch.setattr(st, "progress", lambda *a, **k: None, raising=False)
    dva._voice_job_poller_fragment(client, key, "sub1")
    assert f"{key}_voice_job_pending" not in st.session_state
    df_res, logs, missing = st.session_state[key]
    assert df_res.iloc[0]["Status"] == "✅ Present"
    assert logs[0]["is_present"] is True


def test_voice_job_poller_fragment_marks_failed(monkeypatch):
    import streamlit as st
    from src.components import dialog_voice_attend as dva
    from src.ui.worker_client import WorkerClient

    def fake_get(url, timeout):
        return {"id": "j1", "status": "failed", "progress": 0, "result": {}, "error": "boom"}

    client = WorkerClient("http://worker:8000", http_get=fake_get)
    st.session_state.clear()
    key = "smartclass_voice_t1_sub1"
    st.session_state[f"{key}_voice_job_pending"] = {
        "job_id": "j1",
        "enroll_stud": [],
        "missing_voiceprint_names": [],
    }
    monkeypatch.setattr(st, "progress", lambda *a, **k: None, raising=False)
    dva._voice_job_poller_fragment(client, key, "sub1")
    assert st.session_state.get(f"{key}_voice_job_failed") is True
    assert key not in st.session_state
