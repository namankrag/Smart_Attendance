import logging

import streamlit as st
from PIL import Image
from src.components.dialog_utils import dialog_banner
from src.ui.base_layout import is_dark_theme

# Phase 2.1: canonical ingest lives in src/ui/uploads.py (2560 px group
# ingest, SHA-256 of raw bytes, thumbnails only). The helpers below are
# thin wrappers kept so existing imports keep working.
from src.ui import uploads as _uploads

logger = logging.getLogger(__name__)

# Session storage note: only downscaled copies (thumbnails, max 1024 px
# on the long edge — see _downscale_for_session) are kept in
# st.session_state.attendance_images. Full-resolution originals are NOT
# stored in session state long-term: they would bloat the session,
# slow reruns, and keep raw biometric-adjacent photos in memory longer
# than needed. The 2560 px ingest copies the worker needs are kept in
# the hash-keyed ``attendance_image_bytes`` dict (see
# _add_images_to_state) and dropped together with the thumbnails.

_SESSION_MAX_DIM = 1024


def _hash_bytes(data: bytes) -> str:
    """SHA-256 hex digest of raw bytes.

    SHA-256 (not MD5): MD5 is broken for collision resistance, so two
    different photos could share an MD5 and be wrongly treated as
    duplicates. SHA-256 dedupe is collision-resistant in practice.
    """
    return _uploads.sha256_bytes(data)


def _get_image_hash(img: Image.Image) -> str:
    """SHA-256 hash of a PIL image's decoded pixel bytes (fallback path).

    Prefer hashing the raw uploaded file bytes (see _add_images_to_state);
    this is used when only a PIL image is available (e.g. camera input
    already converted).
    """
    return _hash_bytes(img.tobytes())


def _downscale_for_session(img: Image.Image) -> Image.Image:
    """Return a thumbnail-sized copy for session storage (see module note)."""
    return _uploads.thumbnail_image(img)


def _get_existing_hashes() -> set:
    """Collect SHA-256 hashes of all currently staged images."""
    existing = set()
    if "attendance_images" in st.session_state and isinstance(
        st.session_state["attendance_images"], list
    ):
        for img in st.session_state["attendance_images"]:
            try:
                existing.add(_get_image_hash(img))
            except Exception:
                pass
    return existing


def _raw_bytes_of(f):
    """Raw uploaded file bytes, if available, else None.

    Streamlit UploadedFile exposes .getvalue(); generic file-likes are
    read (and rewound) instead. Returns None when bytes cannot be read.
    """
    return _uploads.raw_bytes_of(f)


def staged_image_bytes() -> dict:
    """Hash -> 2560 px ingest bytes for staged photos (worker payloads).

    The worker submits these bytes (never the thumbnails, never the
    original full-resolution files). Empty when nothing is staged.
    """
    store = st.session_state.get("attendance_image_bytes")
    return dict(store) if isinstance(store, dict) else {}


def _add_images_to_state(files) -> int:
    """Safely convert, deduplicate, and append images to attendance_images.

    Dedupe hashes the raw uploaded FILE BYTES (SHA-256) when available,
    so identical uploads are caught even if they decode differently;
    only a downscaled thumbnail copy is staged in session state.
    """
    if "attendance_images" not in st.session_state or not isinstance(
        st.session_state["attendance_images"], list
    ):
        st.session_state["attendance_images"] = []
    if "attendance_image_bytes" not in st.session_state or not isinstance(
        st.session_state["attendance_image_bytes"], dict
    ):
        st.session_state["attendance_image_bytes"] = {}

    existing_hashes = _get_existing_hashes()
    added_count = 0

    for f in files:
        try:
            raw = _raw_bytes_of(f)
            if isinstance(f, Image.Image):
                img = f.convert("RGB")
                h_raw = None
            else:
                img = Image.open(f).convert("RGB")
                # Hash the raw file bytes, not the decoded pixels.
                h_raw = _hash_bytes(raw) if raw else None
            # Phase 2.1 ingest: downscale to 2560 px long edge for the
            # worker (back-row faces need the resolution; full-res
            # phone photos do not help and only cost time/memory).
            # The ingest copy is keyed by its SHA-256 so a rerun never
            # repeats detection for the same file.
            source_bytes = raw if raw is not None else _pil_to_jpeg_bytes(img)
            ingested = _uploads.process_upload(source_bytes, kind="group")
            staged = _downscale_for_session(img)
            # Staged images only retain downscaled pixels, so their
            # stored hash is a pixel hash; check BOTH hashes so a
            # re-upload is caught in either domain.
            h_px = _get_image_hash(staged)
            if (
                h_raw in existing_hashes
                or h_px in existing_hashes
                or ingested["sha256"] in existing_hashes
            ):
                continue
            st.session_state["attendance_images"].append(staged)
            st.session_state["attendance_image_bytes"][ingested["sha256"]] = ingested["image_bytes"]
            existing_hashes.add(h_px)
            existing_hashes.add(ingested["sha256"])
            if h_raw:
                existing_hashes.add(h_raw)
            added_count += 1
        except Exception:
            logger.debug("Skipping staged image that failed ingest", exc_info=True)
            continue

    return added_count


def _pil_to_jpeg_bytes(img: Image.Image) -> bytes:
    """Encode a PIL image as JPEG bytes (camera-input path, no raw file)."""
    import io as _io

    buf = _io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=88)
    return buf.getvalue()


@st.dialog("Add Classroom Photos", width="large")
def add_photos_dialog():
    dialog_banner(
        "Add Photos", subtitle="Capture or upload photos to scan for attendance", theme="orange"
    )
    dark = is_dark_theme()

    if "attendance_images" not in st.session_state:
        st.session_state.attendance_images = []
    if "photo_tab" not in st.session_state:
        st.session_state.photo_tab = "upload"

    t1, t2 = st.columns(2)
    with t1:
        typ = "primary" if st.session_state.photo_tab == "upload" else "tertiary"
        if st.button("🖼️  Upload Files", type=typ, width="stretch", key="tab_upload"):
            st.session_state.photo_tab = "upload"
            st.rerun()
    with t2:
        typ = "primary" if st.session_state.photo_tab == "camera" else "tertiary"
        if st.button("📷  Camera Snapshot", type=typ, width="stretch", key="tab_cam"):
            st.session_state.photo_tab = "camera"
            st.rerun()

    st.markdown("<div style='margin-top:12px'></div>", unsafe_allow_html=True)

    # ── Upload Mode ──
    uploaded_files = None
    if st.session_state.photo_tab == "upload":
        uploaded_files = st.file_uploader(
            "Choose classroom image files",
            type=["jpg", "png", "jpeg", "webp"],
            accept_multiple_files=True,
            key="dialog_upload_files",
            help="Select one or more photos of the classroom to detect student faces.",
        )

        if uploaded_files:
            st.caption(f"📁 **{len(uploaded_files)} file(s) selected for upload**")

            # Show preview thumbnails of selected files
            preview_cols = st.columns(min(4, len(uploaded_files)))
            for p_idx, f in enumerate(uploaded_files[:8]):
                try:
                    thumb_img = Image.open(f).convert("RGB")
                    with preview_cols[p_idx % len(preview_cols)]:
                        st.image(
                            thumb_img,
                            width="stretch",
                            caption=getattr(f, "name", f"Image {p_idx + 1}"),
                        )
                except Exception:
                    pass

            if len(uploaded_files) > 8:
                st.caption(f"... and {len(uploaded_files) - 8} more photo(s)")

            st.space()
            if st.button(
                "💾  Save & Add to Workspace",
                type="primary",
                width="stretch",
                key="btn_confirm_upload",
            ):
                added = _add_images_to_state(uploaded_files)
                if added > 0:
                    st.toast(f"✅ Added {added} photo(s) to workspace!", icon="📸")
                else:
                    st.info("ℹ️ Selected photo(s) are already staged in your workspace.")
                st.rerun()

    # ── Camera Mode ──
    if st.session_state.photo_tab == "camera":
        cam_photo = st.camera_input("Take Snapshot", key="dialog_camera_stream")
        if cam_photo:
            added = _add_images_to_state([cam_photo])
            if added > 0:
                st.toast("📸 Snapshot added to workspace!", icon="✅")
                st.rerun()

    # ── Staged Photos Summary & Preview ──
    staged_count = len(st.session_state.attendance_images)
    if staged_count > 0:
        pill_bg = (
            "linear-gradient(135deg, #7c2d12 0%, #451a03 100%)"
            if dark
            else "linear-gradient(135deg, #fff7ed, #ffedd5)"
        )
        border_col = "#f97316" if dark else "#fa8231"
        text_col = "#ffedd5" if dark else "#c2410c"

        st.markdown(
            f"""
            <div style="
                background: {pill_bg};
                border-left: 4px solid {border_col};
                border-radius: 10px;
                padding: 10px 14px;
                margin: 14px 0 10px;
                font-family: Outfit, sans-serif;
                font-size: 0.9rem;
                font-weight: 600;
                color: {text_col};
                display: flex;
                justify-content: space-between;
                align-items: center;
            ">
                <span>📸 {staged_count} photo{"s" if staged_count != 1 else ""} currently ready in workspace</span>
            </div>
        """,
            unsafe_allow_html=True,
        )

        with st.expander(f"👁️ View/Manage Staged Photos ({staged_count})", expanded=False):
            staged_cols = st.columns(4)
            for s_idx, s_img in enumerate(st.session_state.attendance_images):
                with staged_cols[s_idx % 4]:
                    st.image(s_img, width="stretch", caption=f"Photo {s_idx + 1}")
                    if st.button(
                        "🗑️ Remove", key=f"dlg_del_{s_idx}", width="stretch", type="secondary"
                    ):
                        st.session_state.attendance_images.pop(s_idx)
                        st.rerun()

            if st.button("🗑️ Clear All Photos", key="dlg_clear_all", type="secondary"):
                st.session_state.attendance_images = []
                st.rerun()

    st.divider()

    # ── Action Buttons ──
    col_close, col_save_done = st.columns(2)
    with col_close:
        if st.button(
            "✕  Cancel / Close", type="secondary", width="stretch", key="btn_close_dialog"
        ):
            st.rerun()
    with col_save_done:
        if st.button("✅  Save & Done", type="primary", width="stretch", key="btn_done_dialog"):
            # Automatically save any pending uploaded files if not yet added
            if uploaded_files:
                added = _add_images_to_state(uploaded_files)
                if added > 0:
                    st.toast(f"✅ Saved {added} photo(s) to workspace!", icon="📸")
            st.rerun()
