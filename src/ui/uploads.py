"""Upload ingest: downscale, hash, thumbnail (Phase 2.1).

Every image entering the app goes through here before it is stored in
session state or sent to the ML worker:

* **Downscale on ingest** — group photos to ``GROUP_MAX_LONG_EDGE``
  (2560 px) and login/registration frames to ``LOGIN_MAX_LONG_EDGE``
  (720 px). Full-resolution phone photos (4000+ px) only slow
  detection down and bloat session state; the ONNX detector works on
  tiles of the 2560 px image (see ``worker/face_onnx.py``) and a login
  frame never needs more than 720 px.
* **SHA-256 of the raw file bytes** — reruns and re-uploads of the same
  file are recognised without repeating detection (audit 21, 25).
  MD5 is not used: it is broken for collision resistance.
* **Thumbnails only in session state** — the session holds a small
  preview (``THUMBNAIL_MAX_LONG_EDGE``); the 2560 px ingest copy is
  kept only in the hash-keyed ``attendance_image_bytes`` staging dict
  that the worker submission reads, and it is dropped when photos are
  cleared / on logout. Raw photos are never written to disk.

The legacy ``dialog_add_photo`` helpers now delegate to this module;
its public names (``_hash_bytes`` etc.) are kept as thin wrappers so
existing imports keep working.
"""

from __future__ import annotations

import hashlib
import io
import logging
from typing import Optional

from PIL import Image

__all__ = [
    "GROUP_MAX_LONG_EDGE",
    "LOGIN_MAX_LONG_EDGE",
    "THUMBNAIL_MAX_LONG_EDGE",
    "sha256_bytes",
    "downscale_image",
    "downscale_image_bytes",
    "thumbnail_image",
    "process_upload",
]

logger = logging.getLogger(__name__)

# Phase 2.1 ingest sizes (long edge, px).
GROUP_MAX_LONG_EDGE = 2560  # group / classroom photos for the worker
LOGIN_MAX_LONG_EDGE = 720  # login / registration frames
THUMBNAIL_MAX_LONG_EDGE = 1024  # previews kept in st.session_state


def sha256_bytes(data: bytes) -> str:
    """SHA-256 hex digest of raw file bytes (dedupe key)."""
    return hashlib.sha256(data).hexdigest()


def downscale_image(img: Image.Image, max_long_edge: int) -> Image.Image:
    """Return ``img`` downscaled so its long edge is <= ``max_long_edge``.

    Images already at or below the limit are returned unchanged (a copy
    is not forced). Uses ``Image.LANCZOS`` — higher quality than the
    bilinear resampling the old code used, which matters for small /
    back-row faces.
    """
    img = img.convert("RGB")
    if max(img.size) <= max_long_edge:
        return img
    out = img.copy()
    out.thumbnail((max_long_edge, max_long_edge), Image.LANCZOS)
    return out


def downscale_image_bytes(data: bytes, max_long_edge: int, fmt: str = "JPEG") -> bytes:
    """Downscale raw image bytes; returns re-encoded image bytes."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img = downscale_image(img, max_long_edge)
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=88)
    return buf.getvalue()


def thumbnail_image(img: Image.Image) -> Image.Image:
    """Small preview copy for session-state display only."""
    return downscale_image(img, THUMBNAIL_MAX_LONG_EDGE)


def process_upload(data: bytes, *, kind: str = "group") -> dict:
    """Ingest one uploaded file.

    ``kind`` is ``"group"`` (2560 px) or ``"login"`` (720 px).
    Returns ``{"sha256", "image" (PIL, downscaled), "image_bytes",
    "thumbnail" (PIL)}``. Raises ``ValueError`` for unknown kinds and
    propagates PIL errors for unreadable files — callers decide how to
    report those; this module never touches Streamlit.
    """
    if kind == "group":
        max_edge = GROUP_MAX_LONG_EDGE
    elif kind == "login":
        max_edge = LOGIN_MAX_LONG_EDGE
    else:
        raise ValueError(f"unknown upload kind: {kind!r} (want 'group' or 'login')")
    digest = sha256_bytes(data)
    img = downscale_image(Image.open(io.BytesIO(data)).convert("RGB"), max_edge)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return {
        "sha256": digest,
        "image": img,
        "image_bytes": buf.getvalue(),
        "thumbnail": thumbnail_image(img),
    }


def raw_bytes_of(f) -> Optional[bytes]:
    """Raw uploaded file bytes, if available, else None.

    Streamlit ``UploadedFile`` exposes ``.getvalue()``; generic
    file-likes are read (and rewound) instead.
    """
    try:
        if hasattr(f, "getvalue"):
            return f.getvalue()
        if hasattr(f, "read"):
            pos = f.tell() if hasattr(f, "tell") else None
            data = f.read()
            if pos is not None and hasattr(f, "seek"):
                f.seek(pos)
            return data if isinstance(data, (bytes, bytearray)) else None
    except Exception:
        return None
    return None
