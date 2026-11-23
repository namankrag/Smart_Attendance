"""Supabase client, retry policy and startup guards (Phase 0).

Security notes (read before changing anything here):
- The Streamlit app MUST use the Supabase **anon** key only, with Row Level
  Security (RLS) enforced server-side. The **service_role** key bypasses
  RLS entirely and must NEVER be placed in ``st.secrets`` / used by this
  client -- a leaked service_role key is full database access. If a
  privileged operation is ever needed, it belongs in a separate, server-side
  service, not in Streamlit. See Supabase docs on RLS / service_role.
- Retry policy is split deliberately (Phase 0 audit finding: the old
  ``db_retry`` retried *writes* on string-matched error messages, which can
  double-apply a non-idempotent write):
  * ``db_retry_read`` -- bounded exponential backoff, idempotent READS only,
    transient ``httpx`` / ``OSError`` failures only. No string matching.
  * ``db_retry_write`` -- NO retry at all. A write is executed exactly once;
    callers that need safe retry must make the write idempotent by design
    (e.g. ``upsert(..., on_conflict=...)``) instead of retrying blindly.
  * ``db_retry`` is a deprecated alias for ``db_retry_read`` kept only so
    old read call sites keep importing; do NOT use it on writes.
- All Supabase calls go through explicit client timeouts
  (:func:`get_client_timeout_seconds`) so a hung connection cannot block
  the Streamlit session forever.
"""

import time
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

import httpx
import streamlit as st
from supabase import Client, create_client

try:
    from supabase import ClientOptions  # supabase-py >= 2.x re-export
except ImportError:  # pragma: no cover - older supabase-py layout
    try:
        from supabase.lib.client_options import ClientOptions
    except ImportError:  # pragma: no cover
        ClientOptions = None  # type: ignore[assignment]

F = TypeVar("F", bound=Callable[..., Any])

# --- Timeouts ----------------------------------------------------------------
# A single explicit timeout for every Supabase (PostgREST / Storage) call.
# 10s is long enough for a normal query on a healthy connection and short
# enough that a hung backend fails visibly instead of hanging Streamlit.
# It is also Supavisor / PgBouncer compatible: short, bounded waits with
# no server-side cursors or prepared-statement assumptions, so the client
# works in Supavisor transaction mode (the default pooler mode on
# Supabase) without holding a pooled connection open.
CLIENT_TIMEOUT_SECONDS = 10


def get_client_timeout_seconds() -> int:
    """Explicit timeout (seconds) applied to all Supabase client calls."""
    return CLIENT_TIMEOUT_SECONDS


# --- Transient failures that are safe to retry (reads only) ------------------
# Only transport-level, transient errors. Note what is deliberately NOT
# here: ``httpx.HTTPStatusError`` (a 4xx/5xx *response* -- retrying a
# rejected write could double-apply it), PostgREST errors, and any
# string-matched error message (the old code retried on substrings like
# "connection" / "timeout" appearing in *any* exception, including
# application errors).
TRANSIENT_READ_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.TimeoutException,
    httpx.RemoteProtocolError,
    httpx.ReadError,
    ConnectionError,
    OSError,
)

MAX_READ_ATTEMPTS = 3
READ_INITIAL_DELAY_SECONDS = 0.5
READ_MAX_DELAY_SECONDS = 4.0


@st.cache_resource(show_spinner=False)
def _init_supabase_client() -> Client:
    """Thread-safe singleton Supabase client cached in Streamlit resource pool.

    Uses the anon key from ``st.secrets["SUPABASE_KEY"]`` only -- see the
    module docstring: the service_role key must never be used here.
    """
    supabase_url = st.secrets["SUPABASE_URL"]
    supabase_key = st.secrets["SUPABASE_KEY"]
    timeout = get_client_timeout_seconds()
    if ClientOptions is not None:
        options = ClientOptions(
            postgrest_client_timeout=timeout,
            storage_client_timeout=timeout,
        )
        return create_client(supabase_url, supabase_key, options=options)
    # Fallback for supabase-py versions without ClientOptions: the client
    # is still created, but without an explicit timeout -- upgrade supabase.
    return create_client(supabase_url, supabase_key)


def get_supabase() -> Client:
    """Retrieve the shared Supabase client."""
    return _init_supabase_client()


class SupabaseProxy:
    """Transparent thread-safe proxy forwarding calls to the cached client.

    SECURITY: this proxy only ever forwards to the anon-key client created
    by :func:`_init_supabase_client`. It must never be pointed at a
    service_role client in Streamlit -- RLS is the only thing standing
    between a logged-in user and another user's rows.
    """

    def __getattr__(self, name):
        return getattr(get_supabase(), name)


supabase = SupabaseProxy()


def db_retry_read(
    max_retries: int = MAX_READ_ATTEMPTS, initial_delay: float = READ_INITIAL_DELAY_SECONDS
):
    """Bounded exponential-backoff retry for IDEMPOTENT READS only.

    ``max_retries`` is the maximum number of *attempts* (default 3).
    Only :data:`TRANSIENT_READ_ERRORS` are retried; every other exception
    propagates immediately. Delays are ``initial_delay * 2**attempt``,
    capped at :data:`READ_MAX_DELAY_SECONDS`. Do NOT apply this to writes.
    """
    if max_retries < 1:
        raise ValueError("max_retries must be >= 1")

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_err: Optional[BaseException] = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except TRANSIENT_READ_ERRORS as exc:
                    last_err = exc
                    if attempt == max_retries - 1:
                        break
                    sleep_time = min(
                        initial_delay * (2 ** attempt), READ_MAX_DELAY_SECONDS
                    )
                    time.sleep(sleep_time)
            assert last_err is not None  # max_retries >= 1 guarantees this
            raise last_err

        return wrapper  # type: ignore[return-value]

    return decorator


def db_retry_write(func: F) -> F:
    """No-retry marker for WRITES -- executes the function exactly once.

    A failed write must surface to the caller, never be silently retried:
    retrying a non-idempotent insert/update can double-apply it. If a
    write needs retry safety, make it idempotent first (e.g. upsert with
    ``on_conflict``) and only then consider a retry -- that is a deliberate
    per-call decision, not a default. Usable as ``@db_retry_write`` (bare)
    or ``@db_retry_write()``.
    """
    if callable(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    def decorator(inner: F) -> F:
        @wraps(inner)
        def inner_wrapper(*args, **kwargs):
            return inner(*args, **kwargs)

        return inner_wrapper  # type: ignore[return-value]

    return decorator  # type: ignore[return-value]


# Deprecated alias: the old ``db_retry`` retried writes too. It now means
# exactly ``db_retry_read``. New code must use ``db_retry_read`` /
# ``db_retry_write`` explicitly; do not use ``db_retry`` on writes.
db_retry = db_retry_read


def check_pin_schema_guard(supabase_client: Any = None) -> None:
    """Startup guard: fail loudly if the ``students.pin_hash`` column is unusable.

    Raises ``RuntimeError`` when:
    - the ``students.pin_hash`` column does not exist (PostgREST
      ``PGRST204`` / "column ... does not exist" -- i.e. the Phase 0
      migration has not been applied), or
    - any sampled student row has a NULL / empty ``pin_hash`` (an account
      that could log in with no PIN -- see the old
      ``student_screen.py`` "allow initial login" path this guard exists
      to kill).

    This is a *startup* check only: call it once from the app entrypoint
    after the client is created. It is deliberately NOT called on import
    (importing ``config`` must never touch the network). It samples the
    first 100 student rows -- it is a smoke guard, not an exhaustive audit;
    the migration and RLS policies remain the authoritative enforcement.
    An empty ``students`` table passes (no active accounts to check).
    Other (e.g. transient network) errors propagate unchanged.
    """
    client = supabase if supabase_client is None else supabase_client
    try:
        response = (
            client.table("students")
            .select("student_id,pin_hash")
            .limit(100)
            .execute()
        )
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        if "pin_hash" in lowered and (
            "does not exist" in lowered
            or "pgrst204" in lowered
            or "column" in lowered
        ):
            raise RuntimeError(
                "students.pin_hash column is missing: apply the Phase 0 "
                "database migration before starting the app"
            ) from exc
        raise
    rows = response.data or []
    missing = [row for row in rows if not row.get("pin_hash")]
    if missing:
        raise RuntimeError(
            f"{len(missing)} of {len(rows)} sampled student account(s) have "
            "a NULL/empty pin_hash; every active student account must have "
            "a PIN hash (see Phase 0 migration / backfill) before login is enabled"
        )
