"""Teacher auth screens (Phase 2 split of ``teacher_screen``).

Moved verbatim from ``src/screen/teacher_screen.py`` (Phase 2.1):
``register_teacher_action``, ``teacher_scrn_login`` and
``teacher_scrn_register``. ``teacher_screen`` re-exports them, so
existing imports keep working.
"""

import logging
from typing import Any, Dict, Tuple

import streamlit as st

from src.components.footer import footer_dashboard
from src.components.header import header_dashboard, theme_toggle
from src.database.db import (
    check_teacher_exists,
    create_teacher,
    teacher_login,
)
from src.database.logging_utils import log_exception

try:
    from src.database.db import (
        teacher_login_with_rehash,
        update_teacher_password_hash,
    )
except ImportError:  # pragma: no cover
    teacher_login_with_rehash = None  # type: ignore[assignment]
    update_teacher_password_hash = None  # type: ignore[assignment]

try:
    from src.database.auth import hash_password
except ImportError:  # pragma: no cover
    hash_password = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def _public_teacher_record(teacher: Dict[str, Any]) -> Dict[str, Any]:
    """Only the fields the session may hold — never a password hash."""
    return {
        "teacher_id": str(teacher["teacher_id"]),
        "name": teacher.get("name"),
        "username": teacher.get("username"),
    }


def register_teacher_action(
    username: str, name: str, pwd: str, pwd_confirm: str
) -> Tuple[bool, str]:
    if not username.strip() or not name.strip() or not pwd:
        return False, "All fields are required!"
    if len(pwd) < 6:
        return False, "Password must be at least 6 characters long."
    if pwd != pwd_confirm:
        return False, "Passwords do not match."
    if check_teacher_exists(username):
        return False, "Username is already taken."

    try:
        create_teacher(username, pwd, name)
        return True, "Account created successfully! Please login."
    except Exception:
        logger.exception("Teacher registration failed")
        return False, "Registration failed. Please try again."


def teacher_scrn_login():
    c1, c2 = st.columns(2, vertical_alignment="center", gap="xxlarge")
    with c1:
        header_dashboard()
    with c2:
        b1, b2 = st.columns(2, vertical_alignment="center")
        with b1:
            if st.button("Go to Home", type="secondary", key="backbtn", width="stretch"):
                st.session_state["login_type"] = None
                st.session_state["teacher_login_type"] = "login"
                st.rerun()
        with b2:
            theme_toggle("teacher_login")

    st.header("Teacher Portal Sign In", text_alignment="center")
    st.space()

    username = st.text_input("Username", placeholder="@username", key="teacher_login_user")
    password = st.text_input(
        "Password", type="password", placeholder="Enter Password", key="teacher_login_pwd"
    )

    st.divider()
    btn1, btn2 = st.columns(2)

    with btn1:
        if st.button("Login", icon=":material/passkey:", width="stretch", key="btn_teacher_login"):
            if username and password:
                login_error = False
                needs_rehash = False
                try:
                    # Phase 1: prefer the rehash-reporting login so legacy
                    # bcrypt hashes are transparently upgraded to Argon2id
                    # on successful login (OWASP Password Storage Cheat
                    # Sheet). Falls back to teacher_login when the Phase 1
                    # helper has not landed.
                    if teacher_login_with_rehash is not None:
                        result = teacher_login_with_rehash(username, password)
                        teacher, needs_rehash = result if result else (None, False)
                    else:
                        teacher = teacher_login(username, password)
                except Exception:
                    ref = log_exception(logger, "teacher_login_failed", username=username)
                    teacher = None
                    login_error = True
                    st.error(f"Login failed. Please try again. (Ref: {ref})")
                if teacher:
                    if needs_rehash:
                        # Phase 1 carry-over (a): write the new Argon2id
                        # hash back in the same login flow. A failed write
                        # is logged and never blocks the login.
                        try:
                            if (
                                update_teacher_password_hash is not None
                                and hash_password is not None
                            ):
                                update_teacher_password_hash(
                                    str(teacher["teacher_id"]), hash_password(password)
                                )
                            else:
                                logger.warning(
                                    "Rehash helper unavailable; teacher hash not upgraded"
                                )
                        except Exception:
                            logger.exception("Teacher rehash write-back failed for %s", username)
                    st.session_state.user_role = "teacher"
                    st.session_state.teacher_data = _public_teacher_record(teacher)
                    st.session_state.is_logged_in = True
                    st.toast(f"Welcome back, {teacher['name']}! 👋")
                    st.rerun()
                elif not login_error:
                    st.error("Invalid Username or Password")
            else:
                st.warning("Please enter username and password")

    with btn2:
        if st.button(
            "Register New Account",
            type="primary",
            icon=":material/person_add:",
            width="stretch",
            key="btn_to_teacher_reg",
        ):
            st.session_state.teacher_login_type = "register"
            st.rerun()

    footer_dashboard()


def teacher_scrn_register():
    c1, c2 = st.columns(2, vertical_alignment="center", gap="xxlarge")
    with c1:
        header_dashboard()
    with c2:
        b1, b2 = st.columns(2, vertical_alignment="center")
        with b1:
            if st.button("Go to Home", type="secondary", key="backbtn", width="stretch"):
                st.session_state["login_type"] = None
                st.session_state["teacher_login_type"] = "login"
                st.rerun()
        with b2:
            theme_toggle("teacher_reg")

    st.header("Register Teacher Profile")
    st.space()

    username = st.text_input("Username", placeholder="@username", key="reg_teach_user")
    name = st.text_input("Full Name", placeholder="e.g. Dr. Jane Smith", key="reg_teach_name")
    password = st.text_input(
        "Password", type="password", placeholder="Minimum 6 characters", key="reg_teach_pwd"
    )
    pass_conf = st.text_input(
        "Confirm Password",
        type="password",
        placeholder="Re-enter password",
        key="reg_teach_pwd_confirm",
    )

    st.divider()
    btn1, btn2 = st.columns(2)

    with btn1:
        if st.button(
            "Complete Registration",
            icon=":material/how_to_reg:",
            width="stretch",
            key="btn_teacher_reg_submit",
        ):
            succ, msg = register_teacher_action(username, name, password, pass_conf)
            if succ:
                st.success(msg)
                st.session_state.teacher_login_type = "login"
                st.rerun()
            else:
                st.error(msg)

    with btn2:
        if st.button(
            "Already have an account? Sign In",
            type="primary",
            icon=":material/login:",
            width="stretch",
            key="btn_back_to_teacher_login",
        ):
            st.session_state.teacher_login_type = "login"
            st.rerun()

    footer_dashboard()
