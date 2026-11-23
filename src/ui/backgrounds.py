"""Page backgrounds (Phase 2 split of ``base_layout``).

``style_bg_home`` / ``style_bg_dashboard`` used to live in
``src/ui/base_layout.py``; they are small, self-contained and imported
by several screens, so they live here now. ``base_layout`` re-exports
them so existing imports keep working.
"""

from __future__ import annotations

import streamlit as st

from src.ui.theme import is_dark_theme

__all__ = ["style_bg_home", "style_bg_dashboard"]


def style_bg_home() -> None:
    """Apply the distinct, slightly richer backdrop used by the landing page."""
    if is_dark_theme():
        background = ("radial-gradient(circle at 14% 12%, #164e63 0, transparent 28%), radial-gradi"
            "ent(circle at 86% 82%, #312e81 0, transparent 28%), #07111f")
    else:
        background = ("radial-gradient(circle at 15% 12%, #ccfbf1 0, transparent 29%), radial-gradi"
            "ent(circle at 86% 85%, #e0e7ff 0, transparent 32%), #f8fafc")
    st.html(f"<style>.stApp {{ background: {background}; }}</style>")


def style_bg_dashboard() -> None:
    """Apply a quiet, readable dashboard backdrop in either theme."""
    if is_dark_theme():
        background = ("radial-gradient(circle at 94% 0%, rgba(20,184,166,.13), transparent 25%), ra"
            "dial-gradient(circle at 2% 100%, rgba(99,102,241,.14), transparent 30%), #09111f")
    else:
        background = ("radial-gradient(circle at 96% 0%, rgba(45,212,191,.16), transparent 24%), ra"
            "dial-gradient(circle at 0% 100%, rgba(199,210,254,.35), transparent 30%), #f6f8fc")
    st.html(f"<style>.stApp {{ background: {background}; }}</style>")
