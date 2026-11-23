"""Tolerant image loading for Smart Attendance (Phase 1).

Live finding, 2026-11-22: the repo copy shipped with NO ``img/``
directory at all, so ``open("img/header.png")`` raised
``FileNotFoundError`` and startup died before any screen rendered.
The four images (``header.png``, ``student.png``, ``teacher.png``,
``NKA.png``) were restored from GitHub main — but a missing asset must
never crash the app again. Every loader in this module returns a safe
fallback (empty string / ``None``) when the file is absent or
unreadable, and the UI renders without the image instead of crashing.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Optional, Union

import streamlit as st

logger = logging.getLogger(__name__)

__all__ = ["img_to_base64", "image_file", "cached_logo_base64"]


@st.cache_resource(show_spinner=False)
def cached_logo_base64(img_path: Union[str, Path]) -> str:
    """Base64 logo, cached per process (Phase 2.1, audit 48).

    The old header re-encoded the logo file on EVERY rerun. This
    caches the encoding once per process; a missing file still returns
    ``""`` (degraded UI, never a crash) — see :func:`img_to_base64`.
    """
    return img_to_base64(img_path)


def img_to_base64(img_path: Union[str, Path]) -> str:
    """Base64-encode an image file; return ``""`` when it cannot be read.

    A missing asset is a degraded UI (no logo), not a crash: callers
    must render without the ``<img>`` tag when this returns ``""``.
    """
    path = Path(img_path)
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except (OSError, ValueError) as exc:
        logger.warning("Image unavailable, rendering without it: %s (%s)", path, exc)
        return ""


def image_file(img_path: Union[str, Path]) -> Optional[Path]:
    """Return ``Path`` when the image exists and is a file, else ``None``.

    Use with ``st.image``: pass the result only when it is not ``None``.
    """
    path = Path(img_path)
    return path if path.is_file() else None
