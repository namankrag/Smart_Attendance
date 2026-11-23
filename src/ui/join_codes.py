"""Time-limited, URL-encoded join codes (Phase 2.1, audit 31/32).

A join code is ``v1.<random>.<expiry_epoch>``:

* ``<random>`` (16 URL-safe chars from ``secrets``) is the unguessable
  part — it is what the DB looks up (``get_subject_by_join_code``).
  It is separate from the human ``subject_code`` so sections can share
  a subject code (audit 32).
* ``<expiry_epoch>`` is a Unix timestamp. ``validate_join_code``
  rejects expired codes, so a leaked link stops working — the old
  codes never expired. Default lifetime is 7 days
  (``DEFAULT_JOIN_CODE_TTL_SECONDS``); teachers can re-share to mint a
  fresh code.
* The whole code is URL-safe (``[A-Za-z0-9_-.]``) and is always
  percent-encoded with ``urllib.parse.quote(..., safe='')`` when placed
  in ``?join-code=`` (``build_join_url``), and URL-decoded on read.

Expiry is enforced at validation time in the app. The random part is
still the DB lookup key, so an attacker who edits the expiry segment
still needs the random part — but note the expiry itself is not
HMAC-signed: a holder of a valid code could extend its expiry text.
That is acceptable here because the code *is* the secret (anyone
holding it can already enrol until it expires) and rotation/revocation
happens by issuing a new code; a future migration can add a
``join_code_expires_at`` column for server-side expiry. This is
documented, not hidden.
"""

from __future__ import annotations

import re
import secrets
import time
from urllib.parse import quote, unquote_plus
from typing import Optional

__all__ = [
    "DEFAULT_JOIN_CODE_TTL_SECONDS",
    "JOIN_CODE_RE",
    "generate_join_code",
    "validate_join_code",
    "is_join_code_expired",
    "build_join_url",
]

DEFAULT_JOIN_CODE_TTL_SECONDS = 7 * 24 * 3600  # 7 days

# v1.<16 url-safe chars>.<10-digit unix expiry>
JOIN_CODE_RE = re.compile(r"^v1\.([A-Za-z0-9_-]{16})\.(\d{10})$")
# Legacy (pre-Phase-2) codes: bare token_urlsafe(9) strings, no expiry.
# They keep working (validated by format only) until teachers re-share
# a time-limited code; they are NOT rejected, so old links do not break.
LEGACY_JOIN_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")


def generate_join_code(*, ttl_seconds: int = DEFAULT_JOIN_CODE_TTL_SECONDS,
                       now: Optional[float] = None) -> str:
    """Mint a time-limited join code expiring ``ttl_seconds`` from now."""
    if ttl_seconds <= 0:
        raise ValueError("ttl_seconds must be positive")
    expiry = int((now if now is not None else time.time()) + ttl_seconds)
    return f"v1.{secrets.token_urlsafe(12)[:16]}.{expiry}"


def _expiry_of(code: str) -> Optional[int]:
    m = JOIN_CODE_RE.fullmatch(code)
    return int(m.group(2)) if m else None


def is_join_code_expired(code: str, *, now: Optional[float] = None) -> bool:
    """True if a v1 code is past its expiry. Legacy codes never expire
    by this check (they predate expiry); rotation is the remedy."""
    expiry = _expiry_of(code)
    if expiry is None:
        return False
    return (now if now is not None else time.time()) > expiry


def validate_join_code(raw: Optional[str], *, now: Optional[float] = None) -> Optional[str]:
    """URL-decode and validate a join code. Returns the clean code or None.

    Rejects empty / malformed codes and expired v1 codes. Legacy
    bare-token codes pass format validation (see module docstring).
    """
    if raw is None:
        return None
    clean = unquote_plus(str(raw)).strip()
    if JOIN_CODE_RE.fullmatch(clean):
        return None if is_join_code_expired(clean, now=now) else clean
    if LEGACY_JOIN_CODE_RE.fullmatch(clean):
        return clean
    return None


def build_join_url(base_url: str, join_code: str) -> str:
    """Join link with the code percent-encoded (``quote(..., safe='')``).

    Never interpolate a raw code into a URL: ``+`` / ``/`` / ``=`` in a
    token would be mangled or mis-parsed by the browser otherwise.
    """
    return f"{base_url.rstrip('/')}/?join-code={quote(join_code, safe='')}"
