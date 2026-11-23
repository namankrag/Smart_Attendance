"""Phase 0 mocked test setup.

No network, no Supabase keys, no Streamlit/dlib execution.
- streamlit / supabase / httpx / dlib / resemblyzer / librosa are stubbed
  in sys.modules before any src.* import.
- A FakeSupabase implements the PostgREST-style chain used by
  src/database/* (table/select/eq/gte/order/limit/range/insert/update/
  delete/upsert/execute) over in-memory tables, recording the last
  select string so tests can assert pin_hash is (not) fetched.
"""

import copy
import sys
import types

import pytest

# ---- streamlit stub ----
st = types.ModuleType("streamlit")


class _Cache:
    def __call__(self, *a, **k):
        def deco(fn):
            fn.clear = lambda: None
            return fn

        # support @st.cache_resource without parens
        if a and callable(a[0]) and not k:
            fn = a[0]
            fn.clear = lambda: None
            return fn
        return deco


st.cache_resource = _Cache()
st.cache_data = _Cache()
st.secrets = {}
st.session_state = {}


class _User:
    """Minimal stand-in for Streamlit's st.user (OIDC user info)."""

    is_logged_in = False
    email = None
    sub = None
    access_token = None
    id_token = None


st.user = _User()
st.login = lambda *a, **k: None
st.logout = lambda *a, **k: None


def _dialog(*a, **k):
    def deco(fn):
        return fn

    return deco


st.dialog = _dialog


def _fragment(*a, **k):
    """Identity stand-in for st.fragment (incl. run_every kwarg)."""

    def deco(fn):
        return fn

    if a and callable(a[0]) and not k:
        return a[0]
    return deco


st.fragment = _fragment
for _n in (
    "error",
    "warning",
    "info",
    "success",
    "toast",
    "rerun",
    "stop",
    "spinner",
    "markdown",
    "caption",
    "button",
    "text_input",
    "camera_input",
    "audio_input",
    "header",
    "subheader",
    "columns",
    "container",
    "divider",
    "space",
    "html",
    "dataframe",
    "selectbox",
    "file_uploader",
    "checkbox",
    "set_page_config",
    "download_button",
):
    setattr(st, _n, lambda *a, **k: None)
st.query_params = {}
sys.modules["streamlit"] = st

# ---- supabase stub ----
sup = types.ModuleType("supabase")


class Client:
    pass


sup.Client = Client
sup.create_client = lambda *a, **k: None
sys.modules["supabase"] = sup

# ---- httpx stub ----
httpx = types.ModuleType("httpx")


class _HttpxErr(Exception):
    pass


for _n in (
    "ConnectError",
    "RemoteProtocolError",
    "ReadTimeout",
    "ConnectTimeout",
    "ReadError",
    "WriteTimeout",
    "PoolTimeout",
    "TimeoutException",
    "HTTPStatusError",
):
    setattr(httpx, _n, _HttpxErr)


class ClientOptions:
    def __init__(self, **k):
        self.kwargs = k


httpx.ClientOptions = ClientOptions
sys.modules["httpx"] = httpx

# ---- heavy ML stubs (never executed in Phase 0 tests) ----
for _name in ("dlib", "face_recognition_models", "resemblyzer", "librosa"):
    sys.modules[_name] = types.ModuleType(_name)
sys.modules["resemblyzer"].VoiceEncoder = object
sys.modules["resemblyzer"].preprocess_wav = lambda x: x

sys.path.insert(0, __file__.rsplit("/tests/", 1)[0])


# ---- Fake Supabase ----
class Resp:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class Query:
    def __init__(self, fake, table):
        self.fake = fake
        self.table = table
        self.filters = []
        self.select_str = None
        self._limit = None
        self._range = None
        self._order = None
        self._op = "select"
        self._insert = None
        self._update = None
        self._upsert = None
        self._conflict = None
        self._count = None

    def select(self, cols, count=None):
        self.select_str = cols
        self.fake.last_select[(self.table)] = cols
        self._count = count
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def gte(self, col, val):
        self.filters.append(("gte", col, val))
        return self

    def lte(self, col, val):
        self.filters.append(("lte", col, val))
        return self

    def in_(self, col, vals):
        self.filters.append(("in", col, vals))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def range(self, a, b):
        self._range = (a, b)
        return self

    def order(self, col, desc=False):
        self._order = (col, desc)
        return self

    def insert(self, data):
        self._op = "insert"
        self._insert = data
        return self

    def update(self, data):
        self._op = "update"
        self._update = data
        return self

    def delete(self):
        self._op = "delete"
        return self

    def upsert(self, data, on_conflict=None):
        self._op = "upsert"
        self._upsert = data
        self._conflict = on_conflict
        return self

    def _match(self, row):
        for kind, col, val in self.filters:
            # embedded "subjects.teacher_id" etc: walk nested dicts.
            v = row
            for part in str(col).split("."):
                if isinstance(v, dict):
                    v = v.get(part)
                else:
                    v = None
                    break
            if kind == "eq" and v != val:
                return False
            if kind == "gte" and str(v or "") < str(val):
                return False
            if kind == "lte" and str(v or "") > str(val):
                return False
            if kind == "in" and v not in val:
                return False
        return True

    def _project(self, row):
        if not self.select_str or "*" in self.select_str:
            return copy.deepcopy(row)
        # embedded selects like "students(...)" / "subjects(...)" / "(count)": return row as-is
        if "(" in self.select_str:
            return copy.deepcopy(row)
        out = {}
        for col in [c.strip() for c in self.select_str.split(",")]:
            if col in row:
                out[col] = copy.deepcopy(row[col])
        return out

    def execute(self):
        rows = self.fake.tables.setdefault(self.table, [])
        if self._op == "insert":
            import uuid as _uuid

            data = self._insert if isinstance(self._insert, list) else [self._insert]
            for d in data:
                # Real Supabase generates server-side defaults; the fake
                # must do the same or create_session() returns no session_id.
                if self.table == "attendance_sessions" and not d.get("session_id"):
                    d["session_id"] = str(_uuid.uuid4())
                rows.append(copy.deepcopy(d))
            return Resp(copy.deepcopy(data))
        if self._op == "upsert":
            data = self._upsert if isinstance(self._upsert, list) else [self._upsert]
            keys = [k.strip() for k in (self._conflict or "").split(",")] if self._conflict else []
            out = []
            for d in data:
                existing = None
                if keys:
                    for r in rows:
                        if all(r.get(k) == d.get(k) for k in keys):
                            existing = r
                            break
                if existing is not None:
                    existing.update(copy.deepcopy(d))
                    out.append(copy.deepcopy(existing))
                else:
                    rows.append(copy.deepcopy(d))
                    out.append(copy.deepcopy(d))
            return Resp(out)
        if self._op == "update":
            out = []
            for r in rows:
                if self._match(r):
                    r.update(copy.deepcopy(self._update))
                    out.append(copy.deepcopy(r))
            return Resp(out)
        if self._op == "delete":
            kept, out = [], []
            for r in rows:
                if self._match(r):
                    out.append(copy.deepcopy(r))
                else:
                    kept.append(r)
            self.fake.tables[self.table] = kept
            return Resp(out)
        matched = [r for r in rows if self._match(r)]
        if self._order:
            col, desc = self._order
            matched.sort(key=lambda r: str(r.get(col) or ""), reverse=desc)
        count = len(matched) if self._count == "exact" else None
        if self._range is not None:
            a, b = self._range
            matched = matched[a : b + 1]
        elif self._limit is not None:
            matched = matched[: self._limit]
        return Resp([self._project(r) for r in matched], count=count)


class FakeSupabase:
    def __init__(self, tables=None):
        self.tables = copy.deepcopy(tables or {})
        self.last_select = {}
        self.last_rpc = None
        self.rpc_data = {}

    def table(self, name):
        return Query(self, name)

    def rpc(self, name, params):
        """Record the RPC call; return seeded rows for that function."""
        self.last_rpc = (name, params)
        return _RpcCall(self, name, params)


class _RpcCall:
    def __init__(self, fake, name, params):
        self.fake = fake
        self.name = name
        self.params = params

    def execute(self):
        return Resp(copy.deepcopy(self.fake.rpc_data.get(self.name, [])))


@pytest.fixture
def fake_db():
    return FakeSupabase(
        {
            "students": [
                {
                    "student_id": "11111111-1111-1111-1111-111111111111",
                    "usn": "1MS21CS001",
                    "name": "Asha",
                    "pin_hash": None,
                    "face_embedding": [0.1] * 128,
                    "voice_embedding": None,
                },
                {
                    "student_id": "22222222-2222-2222-2222-222222222222",
                    "usn": "1MS21CS002",
                    "name": "Ben",
                    "pin_hash": "PLACEHOLDER",
                    "face_embedding": [0.2] * 128,
                    "voice_embedding": [0.3] * 256,
                },
            ],
            "teachers": [
                {
                    "teacher_id": "33333333-3333-3333-3333-333333333333",
                    "username": "teach1",
                    "password": "PLACEHOLDER",
                    "name": "Teacher One",
                },
            ],
            "subjects": [
                {
                    "subject_id": "44444444-4444-4444-4444-444444444444",
                    "subject_code": "MPW",
                    "name": "Mini Project",
                    "section": "C",
                    "teacher_id": "33333333-3333-3333-3333-333333333333",
                    "join_code": "abc-123_XYZ",
                },
                {
                    "subject_id": "55555555-5555-5555-5555-555555555555",
                    "subject_code": "MPW",
                    "name": "Mini Project",
                    "section": "D",
                    "teacher_id": "33333333-3333-3333-3333-333333333333",
                    "join_code": "def-456_UVW",
                },
            ],
            "subject_students": [
                {
                    "student_id": "11111111-1111-1111-1111-111111111111",
                    "subject_id": "44444444-4444-4444-4444-444444444444",
                    "enrolled_at": "2026-09-01T00:00:00+00:00",
                },
            ],
            "attendance_logs": [],
            "attendance_sessions": [],
            "login_attempts": [],
        }
    )
