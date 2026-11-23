"""Phase 2.2 worker regression tests (mocked; no FastAPI server, no DB).

Covers: Postgres FOR UPDATE SKIP LOCKED claiming, in-memory job store
lifecycle, job processing (face + voice) with fake pipelines, payload
deletion after processing, and the FastAPI app's routes/health with a
minimal stubbed fastapi module (fastapi is not installed in this env).
"""
import asyncio
import base64
import io
import json
import sys
import types
import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, REPO)


# ---------------------------------------------------------------------------
# Queue SQL (worker/queue.py) with a fake DB-API connection
# ---------------------------------------------------------------------------
class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = [("id",), ("type",), ("status",), ("progress",),
                            ("result_json",), ("error",), ("created_at",), ("expires_at",)]
        self._row = None
    def execute(self, sql, params=None):
        self.conn.executed.append((sql, params))
        if "FOR UPDATE SKIP LOCKED" in sql:
            self._row = self.conn.next_claim
        elif sql.strip().startswith("UPDATE inference_jobs SET progress"):
            self.conn.progress_set = params
        elif "status = 'done'" in sql:
            self.conn.completed = params
        elif "status = 'failed'" in sql:
            self.conn.failed = params
    def fetchone(self):
        return self._row
    def close(self):
        pass


class FakeConn:
    def __init__(self, next_claim=None):
        self.next_claim = next_claim
        self.executed = []
        self.committed = 0
    def cursor(self):
        return FakeCursor(self)
    def commit(self):
        self.committed += 1
    def close(self):
        pass


def test_claim_sql_uses_skip_locked():
    from worker.queue import CLAIM_JOB_SQL
    assert "FOR UPDATE SKIP LOCKED" in CLAIM_JOB_SQL
    assert "status = 'queued'" in CLAIM_JOB_SQL
    assert "ORDER BY created_at" in CLAIM_JOB_SQL


def test_claim_next_job_returns_claimed_row():
    from worker.queue import claim_next_job
    row = {"id": "j1", "type": "face", "status": "running", "progress": 0,
           "result_json": {}, "error": None, "created_at": "x", "expires_at": None}
    conn = FakeConn(next_claim=row)
    assert claim_next_job(conn) == row
    assert any("FOR UPDATE SKIP LOCKED" in sql for sql, _ in conn.executed)


def test_claim_next_job_none_when_queue_empty():
    from worker.queue import claim_next_job
    assert claim_next_job(FakeConn(next_claim=None)) is None


def test_mark_progress_clamps_and_complete_serialises_result():
    from worker.queue import mark_progress, complete_job, fail_job
    conn = FakeConn()
    mark_progress(conn, "j1", 250)
    assert conn.progress_set == (100, "j1")
    complete_job(conn, "j1", {"detected": {"s1": 0.9}})
    assert json.loads(conn.completed[0]) == {"detected": {"s1": 0.9}}
    fail_job(conn, "j1", "boom")
    assert conn.failed == ("boom", "j1")


# ---------------------------------------------------------------------------
# In-memory job store (worker/stores.py)
# ---------------------------------------------------------------------------
def test_memory_store_lifecycle():
    from worker.stores import MemoryJobStore
    store = MemoryJobStore()
    assert store.ping() is True
    job = store.create_job("face", subject_id="s", candidate_ids=["a"])
    assert job["status"] == "queued" and job["progress"] == 0
    store.put_payload(job["id"], b"bytes")
    claimed = store.claim_next()
    assert claimed["id"] == job["id"] and claimed["status"] == "running"
    assert store.claim_next() is None  # already claimed
    store.mark_progress(job["id"], 42)
    store.complete_job(job["id"], {"detected": {}})
    done = store.get_job(job["id"])
    assert done["status"] == "done" and done["progress"] == 100
    assert store.take_payload(job["id"]) == b"bytes"
    assert store.take_payload(job["id"]) is None  # payload deleted after take
    with pytest.raises(ValueError):
        store.create_job("photo")


def test_memory_store_fail():
    from worker.stores import MemoryJobStore
    store = MemoryJobStore()
    job = store.create_job("voice")
    store.fail_job(job["id"], "x" * 600)
    assert store.get_job(job["id"])["status"] == "failed"
    assert len(store.get_job(job["id"])["error"]) <= 500


# ---------------------------------------------------------------------------
# Runner (worker/runner.py) with fake pipelines
# ---------------------------------------------------------------------------
def _jpeg_bytes(w=64, h=64):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="JPEG")
    return buf.getvalue()


def _wav_bytes(seconds=1.0, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


class FakeGallery:
    def load_face_gallery(self, subject_id):
        return {"s1": [np.ones(512, dtype=np.float32)]}
    def load_voice_gallery(self, subject_id):
        return {"s1": [np.ones(192, dtype=np.float32)]}


class FakeFacePipeline:
    def match_group(self, img, gallery):
        assert img.shape == (64, 64, 3)
        assert "s1" in gallery
        return {"detected": {"s1": {"cosine": 0.9, "margin": 0.2, "face_index": 0}},
                "num_faces": 1, "low_quality_face_indices": []}


class FakeDiarizer:
    def diarize(self, wav):
        return [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"}]


class FakeEmbedder:
    def embed(self, clip):
        return np.ones(192, dtype=np.float32)


def _ctx(face=True):
    from worker.config import WorkerConfig
    cfg = WorkerConfig()
    return {"config": cfg, "gallery_loader": FakeGallery(),
            "face_pipeline": FakeFacePipeline() if face else None,
            "diarizer": FakeDiarizer(), "embedder": FakeEmbedder()}


def test_process_face_job_completes_and_deletes_payload():
    from worker.runner import process_one_job
    from worker.stores import MemoryJobStore
    store = MemoryJobStore()
    job = store.create_job("face", subject_id="sub", candidate_ids=["s1"])
    store.put_payload(job["id"], _jpeg_bytes())
    done = process_one_job(store, _ctx())
    assert done["status"] == "done"
    assert done["result_json"]["detected"]["s1"]["cosine"] == 0.9
    assert store.take_payload(job["id"]) is None  # raw photo deleted


def test_process_voice_job_identifies_speaker():
    from worker.runner import process_one_job
    from worker.stores import MemoryJobStore
    store = MemoryJobStore()
    job = store.create_job("voice", subject_id="sub", candidate_ids=["s1"])
    store.put_payload(job["id"], _wav_bytes())
    done = process_one_job(store, _ctx())
    assert done["status"] == "done"
    assert done["result_json"]["identified"]["s1"] == pytest.approx(1.0)
    assert done["result_json"]["num_segments"] == 1


def test_process_job_fails_closed_on_bad_payload():
    from worker.runner import process_one_job
    from worker.stores import MemoryJobStore
    store = MemoryJobStore()
    job = store.create_job("face", subject_id="sub", candidate_ids=[])
    store.put_payload(job["id"], b"not-an-image")
    done = process_one_job(store, _ctx())
    assert done["status"] == "failed"
    assert done["error"]
    assert "Traceback" not in (done["error"] or "")


def test_process_one_job_none_when_empty():
    from worker.runner import process_one_job
    from worker.stores import MemoryJobStore
    assert process_one_job(MemoryJobStore(), _ctx()) is None


def test_decode_wav_rejects_wrong_rate():
    from worker.runner import decode_wav_bytes
    with pytest.raises(ValueError):
        decode_wav_bytes(_wav_bytes(rate=8000))


# ---------------------------------------------------------------------------
# FastAPI app (worker/app.py) with stubbed fastapi
# ---------------------------------------------------------------------------
def _install_fastapi_stub():
    if "fastapi" in sys.modules:
        return sys.modules["fastapi"]
    fastapi = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code, detail=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class Request:
        def __init__(self, body):
            self._body = body
        async def json(self):
            return self._body

    class BackgroundTasks:
        def __init__(self):
            self.tasks = []
        def add_task(self, fn, *a, **k):
            self.tasks.append((fn, a, k))

    class FastAPI:
        def __init__(self, title=None):
            self.title = title
            self.routes = []  # (method, path, func)
            self.state = types.SimpleNamespace()
        def get(self, path, **k):
            def deco(fn):
                self.routes.append(("GET", path, fn))
                return fn

            return deco

        def post(self, path, **k):
            def deco(fn):
                self.routes.append(("POST", path, fn))
                return fn

            return deco

    fastapi.FastAPI = FastAPI
    fastapi.HTTPException = HTTPException
    fastapi.Request = Request
    fastapi.BackgroundTasks = BackgroundTasks
    sys.modules["fastapi"] = fastapi
    return fastapi


def _route(app, method, path):
    for m, p, fn in app.routes:
        if m == method and p == path:
            return fn
    raise AssertionError(f"route {method} {path} not registered")


def test_app_registers_routes_and_healthz_readyz():
    _install_fastapi_stub()
    import importlib
    import worker.app as app_mod
    importlib.reload(app_mod)
    from worker.config import WorkerConfig
    from worker.stores import MemoryJobStore
    cfg = WorkerConfig(model_dir="/nonexistent-models")
    app = app_mod.create_app(config=cfg, store=MemoryJobStore())
    paths = {(m, p) for m, p, _ in app.routes}
    assert ("GET", "/healthz") in paths
    assert ("GET", "/readyz") in paths
    assert ("POST", "/jobs") in paths
    assert ("GET", "/jobs/{job_id}") in paths
    assert _route(app, "GET", "/healthz")() == {"status": "ok"}
    # readyz fails loudly without baked weights
    with pytest.raises(Exception) as excinfo:
        _route(app, "GET", "/readyz")()
    assert getattr(excinfo.value, "status_code", None) == 503


def test_app_submit_and_poll_job_end_to_end():
    _install_fastapi_stub()
    import importlib
    import worker.app as app_mod
    importlib.reload(app_mod)
    from worker.config import WorkerConfig
    from worker.stores import MemoryJobStore
    from worker.runner import process_one_job  # noqa: F401 (ensures import works)

    cfg = WorkerConfig(model_dir="/nonexistent-models")
    store = MemoryJobStore()
    app = app_mod.create_app(config=cfg, store=store, ctx={
        "gallery_loader": FakeGallery(),
        "face_pipeline": FakeFacePipeline(),
        "diarizer": FakeDiarizer(),
        "embedder": FakeEmbedder(),
    })
    fastapi = sys.modules["fastapi"]
    submit = _route(app, "POST", "/jobs")
    payload_b64 = base64.b64encode(_jpeg_bytes()).decode()
    bg = fastapi.BackgroundTasks()
    job = asyncio.run(submit(fastapi.Request(
        {"type": "face", "subject_id": "sub", "candidate_ids": ["s1"],
         "payload_b64": payload_b64, "metadata": {}}), bg))
    assert job["status"] == "queued"
    assert job["id"]
    # Run the background task the app scheduled (claims + processes).
    assert len(bg.tasks) == 1
    fn, args, kwargs = bg.tasks[0]
    asyncio.run(fn(*args, **kwargs))
    got = _route(app, "GET", "/jobs/{job_id}")(job["id"])
    assert got["status"] == "done"
    assert got["result"]["detected"]["s1"]["cosine"] == 0.9


def test_app_rejects_bad_job_type_and_missing_job():
    _install_fastapi_stub()
    import importlib
    import worker.app as app_mod
    importlib.reload(app_mod)
    from worker.config import WorkerConfig
    from worker.stores import MemoryJobStore
    app = app_mod.create_app(config=WorkerConfig(), store=MemoryJobStore())
    fastapi = sys.modules["fastapi"]
    submit = _route(app, "POST", "/jobs")
    with pytest.raises(Exception) as excinfo:
        asyncio.run(submit(fastapi.Request({"type": "photo"}),
                           fastapi.BackgroundTasks()))
    assert getattr(excinfo.value, "status_code", None) == 400
    with pytest.raises(Exception) as excinfo:
        _route(app, "GET", "/jobs/{job_id}")("nope")
    assert getattr(excinfo.value, "status_code", None) == 404
