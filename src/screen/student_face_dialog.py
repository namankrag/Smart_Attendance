"""Student "Update Face Profile" dialog (Phase 2 split of ``student_screen``).

Moved verbatim from ``src/screen/student_screen.py`` (Phase 2.1).
Fresh PIN re-authentication is required before a new face scan can be
added (Phase 0 item 3); the dialog is re-exported by
``student_screen`` so existing imports keep working.
"""

import logging
from typing import Any

import streamlit as st
from PIL import Image

from src.pipelines.face_pipeline import (
    get_face_embeddings,
    train_classifier,
    validate_liveness,
)
from src.database.rest_db import add_student_face_embedding
from src.screen.student_auth import (
    FACE_UPDATE_REAUTH_KEY,
    GENERIC_LOCKOUT_ERROR,
    GENERIC_LOGIN_ERROR,
    LIVENESS_NOTE,
    _login_allowed,
    _lookup_student_for_login,
    _record_login_attempt,
    _verify_pin,
)

try:
    # Phase 3 (DPDP Act Sec. 9(1)): a KNOWN minor needs verifiable
    # parental consent before any new template is stored. Imported
    # defensively; a missing module fails the dialog closed.
    from src.database.rest_db import (
        get_student_dob,
        require_biometric_enrolment_allowed,
    )
except ImportError:  # pragma: no cover - privacy module not present
    get_student_dob = None  # type: ignore[assignment]
    require_biometric_enrolment_allowed = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Add-face-scan dialog — fresh PIN re-authentication required
# ---------------------------------------------------------------------------
@st.dialog("📸 Update Face Profile", width="medium")
def add_face_scan_dialog(student_id: Any):
    st.markdown("### Update Your Face Profile")
    st.caption(
        "Add an additional face scan (e.g. with/without glasses, different hairstyle or lighting) s"
            "o FaceID recognizes you under any condition."
    )
    st.caption(
        "For security, confirm your PIN first. This re-authentication applies to this dialog only."
    )

    if not st.session_state.get(FACE_UPDATE_REAUTH_KEY):
        reauth_pin = st.text_input(
            "Confirm your PIN",
            type="password",
            max_chars=6,
            placeholder="Enter your 4-6 digit PIN",
            key="modal_face_update_pin",
        )
        if st.button(
            "Verify PIN", type="primary", width="stretch", key="btn_face_update_verify_pin"
        ):
            identifier = str(st.session_state.get("student_data", {}).get("usn") or student_id)
            allowed, _retry = _login_allowed(identifier, "pin")
            if not allowed:
                st.error(GENERIC_LOCKOUT_ERROR)
            elif not reauth_pin:
                st.warning("Please enter your PIN.")
            else:
                record = _lookup_student_for_login(identifier)
                pin_hash = (record or {}).get("pin_hash")
                if not record or not pin_hash:
                    _record_login_attempt(identifier, False, "pin")
                    st.error(GENERIC_LOGIN_ERROR)
                else:
                    ok, _needs_rehash = _verify_pin(reauth_pin, pin_hash)
                    _record_login_attempt(identifier, ok, "pin")
                    if ok:
                        st.session_state[FACE_UPDATE_REAUTH_KEY] = True
                        st.rerun()
                    else:
                        st.error(GENERIC_LOGIN_ERROR)
        return

    # Phase 3 (DPDP Act Sec. 9(1)): refuse a new template for a KNOWN
    # minor with no parental-consent record. When no date of birth is
    # on file (rows created before migration 005) the age is unknown
    # and the gate cannot be evaluated — that gap is documented in
    # docs/privacy/dpia.md (DOB backfill) and the registration flow
    # already fails closed on unknown age for new students.
    if get_student_dob is not None and require_biometric_enrolment_allowed is not None:
        try:
            _dob = get_student_dob(student_id)
        except Exception:
            logger.exception("DOB lookup failed for face re-enrolment")
            _dob = None
        if _dob is not None:
            try:
                require_biometric_enrolment_allowed(student_id, date_of_birth=_dob)
            except PermissionError as exc:
                st.error(str(exc))
                return

    cam_scan = st.camera_input("Capture face snapshot", key="modal_face_update_cam")
    if cam_scan:
        img = Image.open(cam_scan).convert("RGB")
        with st.spinner("Analyzing biometric features..."):
            is_live, liveness_msg = validate_liveness(img)
            if not is_live:
                st.error(f"Liveness check: {liveness_msg}")
                st.caption(LIVENESS_NOTE)
            else:
                encodings = get_face_embeddings(img, num_jitters=3, is_single_face=True)
                if not encodings:
                    st.error(
                        "❌ No face detected. Ensure good lighting "
                        "and look directly into the camera."
                    )
                elif len(encodings) > 1:
                    st.warning("⚠️ Multiple faces detected! Ensure only you are in the frame.")
                else:
                    new_emb = encodings[0].tolist()
                    try:
                        res = add_student_face_embedding(student_id, new_emb, reauthenticated=True)
                    except TypeError:
                        # Pre-Phase-0 db signature without the flag; the
                        # PIN re-auth above has already been enforced here.
                        logger.warning("add_student_face_embedding has no reauthenticated flag yet")
                        res = add_student_face_embedding(student_id, new_emb)
                    if res:
                        train_classifier()
                        st.session_state.pop(FACE_UPDATE_REAUTH_KEY, None)
                        st.toast("✅ Biometric profile updated successfully!")
                        st.rerun()
                    else:
                        st.error("Failed to update biometric profile.")
