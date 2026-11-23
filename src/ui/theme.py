"""Shared UI theme: fonts and palette (Phase 2 split of ``base_layout``).

Phase 2.1 split ``src/ui/base_layout.py`` into smaller modules: this
module owns fonts + the colour palette, ``backgrounds.py`` owns the page
backgrounds, and ``base_layout.py`` keeps the (large) component CSS.
``base_layout`` re-exports the helpers here so existing imports keep
working.

Fonts
-----
Fonts are loaded with a ``<link>`` tag (``load_fonts``), never with a
CSS ``@import``: ``@import`` inside an injected ``<style>`` block is
render-blocking and, per audit 48, the old ``@import`` never actually
loaded the fonts it named. A ``<link rel="stylesheet">`` in the page
head loads them in parallel with the rest of the page.
"""

from __future__ import annotations

import streamlit as st

__all__ = ["FONT_LINK_URL", "FONT_LINK_TAG", "load_fonts", "theme_palette", "is_dark_theme"]

# Google Fonts: DM Sans (body) + Manrope (headings). Loaded via <link>,
# never @import (see module docstring).
FONT_LINK_URL = (
    "https://fonts.googleapis.com/css2?"
    "family=DM+Sans:wght@400;500;600;700&family=Manrope:wght@600;700;800&display=swap"
)
FONT_LINK_TAG = (
    f'<link rel="preconnect" href="https://fonts.googleapis.com">'
    f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    f'<link rel="stylesheet" href="{FONT_LINK_URL}">'
)


def load_fonts() -> None:
    """Emit the font ``<link>`` tags once per render.

    Call this at the top of ``style_base_layout`` (it already does).
    Idempotent per rerun: Streamlit re-renders the tag each run, which
    is harmless — the browser caches the stylesheet.
    """
    st.html(FONT_LINK_TAG)


def is_dark_theme() -> bool:
    """True when the user picked the dark theme (session key ``theme``)."""
    return st.session_state.get("theme", "light") == "dark"


def theme_palette(dark: bool) -> dict:
    """Colour palette for ``dark`` / light mode.

    This is the same palette ``base_layout.style_base_layout`` has
    always used, extracted verbatim so new screens/components can share
    it without duplicating the (long) colour tables. New code should
    read colours from here; ``base_layout`` keeps its own inline copy
    for now to avoid a risky mid-CSS refactor.
    """
    if dark:
        return {
            "surface": "#101c2d", "text": "#f4f8ff", "muted": "#c3d0e1",
            "line": "#38526e", "field": "#0c1727", "primary": "#0f9b8e",
            "primary_deep": "#0f766e", "accent": "#818cf8",
            "danger": "#fb7185", "shadow": "rgba(0,0,0,.32)",
            "dialog": "#101c2d",
        }
    return {
        "surface": "rgba(255,255,255,.88)", "text": "#10243e",
        "muted": "#475b73", "line": "#cbd8e6", "field": "#ffffff",
        "primary": "#0f766e", "primary_deep": "#115e59",
        "accent": "#4f46e5", "danger": "#e11d48",
        "shadow": "rgba(15,23,42,.10)", "dialog": "#ffffff",
    }
