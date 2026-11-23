"""Login rate limiting for Smart Attendance (Phase 0).

Single source of truth for login throttling. ``src/database/db.py``
re-exports :func:`record_login_attempt`, :func:`check_login_allowed`,
:func:`is_locked_out` and :func:`check_rate_limit` from here -- do not
duplicate this logic elsewhere.

Policy (OWASP Authentication Cheat Sheet -- account lockout / brute-force
protection, and OWASP Password Storage Cheat Sheet):
https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
- Sliding window: 5 failed attempts for one ``(identifier, kind)`` in
  15 minutes trigger a lockout.
- Exponential lockout: 15 minutes * 2**n, where n is the number of failures
  beyond the 5th (5 failures -> 15 min, 6 -> 30 min, 7 -> 60 min, ...),
  capped at 24 hours. The lockout clock runs from the *most recent*
  failure, so continued guessing extends the lockout.
- Successful logins are recorded too (for audit) but never count toward
  the failure total. A successful login does NOT reset the failure count
  by itself -- the count decays only as failures age out of the window /
  the lockout expires. (Clearing the counter on success would let an
  attacker alternate one good login with 4 guesses forever; the window
  already bounds this.)

Storage: the ``login_attempts`` table (Phase 0 migration) with columns
``identifier`` (TEXT), ``kind`` (TEXT), ``success`` (BOOLEAN),
``attempted_at`` (TIMESTAMPTZ, server default ``now()``). All functions
work purely through Supabase table calls, so tests can substitute a mock
client via the ``client`` argument (or by patching
``src.database.rate_limit.supabase``). No raw SQL is used here.

Fail-closed behaviour: if the ``login_attempts`` store itself errors,
:func:`check_login_allowed` propagates the exception instead of silently
allowing the login -- the caller must treat a rate-limit-store outage as
"login unavailable", never as "rate limiting is off".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.database.config import supabase
from src.database.timeutil import parse_iso_timestamp

# --- Policy constants (OWASP Authentication Cheat Sheet) ------------------
MAX_FAILURES = 5
WINDOW_MINUTES = 15
BASE_LOCKOUT_MINUTES = 15
MAX_LOCKOUT_HOURS = 24

LOGIN_ATTEMPTS_TABLE = "login_attempts"

# ``kind`` values used by callers. Free-form strings are accepted, but
# these are the kinds the login flows must use so one kind's failures
# cannot lock out (or be confused with) another.
KIND_PIN = "pin"
KIND_PASSWORD = "password"  # noqa: S105  # kind label, not a credential


def _normalise_identifier(identifier: str) -> str:
    if not isinstance(identifier, str) or not identifier.strip():
        raise ValueError("identifier must be a non-empty string")
    # Case-insensitive so "1ABC234" and "1abc234" share one counter.
    return identifier.strip().lower()


def _normalise_kind(kind: str) -> str:
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError("kind must be a non-empty string")
    return kind.strip().lower()


def _parse_attempted_at(value: Any) -> Optional[datetime]:
    """Parse a PostgREST timestamptz string into an aware datetime.

    Phase 1: delegates to the shared parser (never raises on bad
    input); naive values are assumed UTC.
    """
    parsed = parse_iso_timestamp(value)
    if parsed is None:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _client(client: Any) -> Any:
    return supabase if client is None else client


def record_login_attempt(
    identifier: str,
    kind: str,
    success: bool,
    client: Any = None,
) -> list:
    """Record one login attempt in ``login_attempts``.

    ``attempted_at`` is left to the server default (``now()``) so the
    timestamp cannot be forged by the caller. Returns the inserted rows
    (usually one row) or ``[]``.
    """
    data = {
        "identifier": _normalise_identifier(identifier),
        "kind": _normalise_kind(kind),
        "success": bool(success),
    }
    response = _client(client).table(LOGIN_ATTEMPTS_TABLE).insert(data).execute()
    return response.data or []


def _recent_failures(
    identifier: str,
    kind: str,
    client: Any = None,
    now: Optional[datetime] = None,
) -> list[datetime]:
    """Timestamps of failed attempts inside the sliding window, newest first."""
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=WINDOW_MINUTES)
    response = (
        _client(client)
        .table(LOGIN_ATTEMPTS_TABLE)
        .select("attempted_at")
        .eq("identifier", _normalise_identifier(identifier))
        .eq("kind", _normalise_kind(kind))
        .eq("success", False)
        .gte("attempted_at", window_start.isoformat())
        .order("attempted_at", desc=True)
        .execute()
    )
    stamps: list[datetime] = []
    for row in response.data or []:
        parsed = _parse_attempted_at(row.get("attempted_at"))
        if parsed is not None:
            stamps.append(parsed)
    stamps.sort(reverse=True)
    return stamps


def _lockout_seconds(failure_count: int) -> int:
    """Exponential lockout for ``failure_count`` failures (>= MAX_FAILURES)."""
    extra = max(0, failure_count - MAX_FAILURES)
    seconds = BASE_LOCKOUT_MINUTES * 60 * (2 ** extra)
    return min(seconds, MAX_LOCKOUT_HOURS * 3600)


def check_login_allowed(
    identifier: str,
    kind: str,
    client: Any = None,
    now: Optional[datetime] = None,
) -> tuple[bool, int]:
    """Return ``(allowed, retry_after_seconds)`` for ``(identifier, kind)``.

    ``(True, 0)`` when fewer than ``MAX_FAILURES`` failures are in the
    window, or when the exponential lockout from the most recent failure
    has expired. Otherwise ``(False, seconds_remaining)``. Raises (fail
    closed) if the ``login_attempts`` store errors -- see module docstring.
    """
    now = now or datetime.now(timezone.utc)
    failures = _recent_failures(identifier, kind, client=client, now=now)
    if len(failures) < MAX_FAILURES:
        return True, 0
    lock_end = failures[0] + timedelta(seconds=_lockout_seconds(len(failures)))
    remaining = int((lock_end - now).total_seconds())
    if remaining <= 0:
        return True, 0
    return False, remaining


def is_locked_out(
    identifier: str,
    kind: str,
    client: Any = None,
    now: Optional[datetime] = None,
) -> bool:
    """True when :func:`check_login_allowed` would refuse the login."""
    allowed, _ = check_login_allowed(identifier, kind, client=client, now=now)
    return not allowed


# Alias matching the name used in the Phase 0 spec / db.py surface.
check_rate_limit = check_login_allowed
