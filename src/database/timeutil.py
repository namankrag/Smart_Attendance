"""Shared ISO-8601 timestamp parsing for Smart Attendance (Phase 1).

Single source of truth for turning a PostgREST ``timestamptz`` string
(or anything else a caller hands us) into an aware ``datetime``.

Rules:
- Accepts ``datetime`` (returned as-is, naive values are assumed UTC),
  ISO strings with ``Z`` or an explicit offset, and date-only strings.
- NEVER raises on bad input: unparseable / empty / wrong-typed values
  return ``None`` so a single corrupt timestamp cannot crash a page
  (Phase 0 audit 30: an unguarded ``datetime.fromisoformat`` crashed
  the Records page). Callers must handle ``None`` as "unknown time".
- All stored timestamps are UTC ``timestamptz`` (migrations 001/004);
  rendering in the user's time zone is the UI's job — this helper only
  parses, it never reformats.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def parse_iso_timestamp(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp; return ``None`` for anything unparseable.

    >>> parse_iso_timestamp("2026-09-01T00:00:00+00:00") is not None
    True
    >>> parse_iso_timestamp("not a date") is None
    True
    >>> parse_iso_timestamp(None) is None
    True
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        # PostgREST returns "...Z" for UTC; fromisoformat needs "+00:00".
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def format_iso_timestamp(value: Any) -> str:
    """Format a timestamp for display, or ``"N/A"`` when it cannot be parsed.

    Never raises. The format is deliberately fixed (UTC) — callers that
    need the user's time zone must convert the aware datetime first.
    """
    parsed = parse_iso_timestamp(value)
    if parsed is None:
        return "N/A"
    return parsed.strftime("%Y-%m-%d %I:%M %p")
