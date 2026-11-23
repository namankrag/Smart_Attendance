"""Structured server-side error logging (Phase 1 hygiene).

Rules (SPEC Phase 1 item 4):
- Exceptions are logged SERVER-SIDE as one JSON line per event, with a
  correlation ID, so an operator can find the matching server log from
  the short reference the UI shows the user.
- The UI NEVER shows a stack trace, an exception message, or DB detail:
  it shows a generic message plus the correlation ID (``Ref: <id>``)
  when the flow has one. The correlation ID itself reveals nothing
  about the failure.
- Nothing secret is ever passed in ``fields``: no passwords, PINs,
  hashes, tokens, or embeddings — identifiers (USN / username) only,
  and only where the call site already logs them.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

__all__ = ["new_correlation_id", "log_exception"]


def new_correlation_id() -> str:
    """Short random correlation ID (12 hex chars) for one failure event."""
    return uuid.uuid4().hex[:12]


def log_exception(
    logger: logging.Logger, message: str, **fields: Any
) -> str:
    """Log an exception as one structured JSON line; return its ID.

    Call inside an ``except`` block: ``logger.exception`` attaches the
    traceback server-side. The returned ID can be shown to the user as
    ``Ref: <id>`` so support can find this exact log line.
    """
    correlation_id = new_correlation_id()
    payload = {
        "event": message,
        "correlation_id": correlation_id,
    }
    for key, value in fields.items():
        payload[key] = str(value)
    logger.exception(json.dumps(payload))
    return correlation_id
