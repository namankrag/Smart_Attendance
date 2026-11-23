"""Privacy rights implementation for Smart Attendance (Phase 3).

Implements the India Digital Personal Data Protection Act, 2023
(DPDP Act) and GDPR Art. 9 / AEPD biometric-attendance guidance in
code, not just in docs. Every section number below was verified
against the Act text (official text:
https://www.indiacode.nic.in/bitstream/123456789/22037/2/a2023-22.pdf
— also mirrored at https://indiankanoon.org/doc/3510545/) on
2026-11-22. Where the SPEC's shorthand was imprecise, the verified
citation is given here:

- Notice (plain language, before/with consent): DPDP Act Sec. 5;
  DPDP Rules 2025 Rule 3 (notice contents). Sec. 5(3) requires the
  notice in English or a language in the Eighth Schedule.
- Consent (free, specific, informed, unconditional, unambiguous,
  clear affirmative action): Sec. 6(1). Withdrawal as easy as
  giving consent: Sec. 6(4) — NOT Sec. 6(5) (that sub-section is
  about the consequences of withdrawal). On withdrawal the
  fiduciary must cease processing within a reasonable time:
  Sec. 6(6). Burden of proving notice + consent is on the
  fiduciary: Sec. 6(10) — hence every consent is recorded here
  with timestamp + notice version (audit_log).
- Children (under 18): verifiable parental / lawful-guardian
  consent before processing: Sec. 9(1). No tracking, behavioural
  monitoring or targeted advertising directed at children:
  Sec. 9(3). "Child" is anyone below 18: Sec. 2(3).
- Security safeguards: Sec. 8(5) (reasonable security safeguards;
  DPDP Rules 2025 Rule 6 sets the minimum: encryption, access
  controls, logging/monitoring, backups). Breach intimation to the
  Board and each affected Data Principal: Sec. 8(6); Rules 2025
  Rule 7 (first intimation without delay; detailed report within
  72 hours). Erasure when consent is withdrawn or the purpose is
  no longer served: Sec. 8(7) (unless retention is required by law).
- Access (summary of personal data + processing activities, and
  who it was shared with): Sec. 11(1). Correction, completion,
  updating and erasure: Sec. 12(1)-(2); the fiduciary must also
  cause its Data Processors to erase: Sec. 12(3).
- Grievance redressal (the Data Principal's right): Sec. 13 — the
  fiduciary must first be approached through its own mechanism;
  the DUTY to establish that mechanism is Sec. 8(10), and to
  publish a contact who can answer data questions is Sec. 8(9).
  DPDP Rules 2025 Rule 14: publish how to exercise rights;
  grievance response within 90 days.
- Commencement: the core duties (Secs. 3-17) come into force
  13 May 2027 (G.S.R. 843(E), 13 Nov 2025). This code implements
  them now, ahead of that date.
- GDPR Art. 9 (biometric data is a special category; processing
  needs explicit consent or another Art. 9(2) condition):
  https://gdpr-info.eu/art-9-gdpr/ — hence the non-biometric
  fallback (PIN / manual / QR): consent is only "freely given"
  (GDPR Art. 7(4); DPDP Sec. 6(1)) if refusing biometrics has no
  penalty. AEPD biometric attendance guidelines:
  https://www.aepd.es/guides/guidelines-clocking-and-attendance-control-processing-using-biometric-systems.pdf

What this module NEVER logs or stores: raw photos, raw audio,
embeddings, PINs, passwords, hashes, tokens. Audit entries carry
identifiers (student_id / USN), counts and timestamps only — see
``log_template_access`` / ``log_breach_event``.

Storage (migration 005_phase3_privacy.sql, LOCAL-ONLY until Naman
runs it — do NOT run live migrations from the app):
- ``consent_records`` — one row per consent grant/withdrawal.
- ``parental_consents`` — one row per verified parental consent.
- ``students.date_of_birth`` — needed to decide under-18 status.
- ``audit_log`` — append-only (created in 001, ensured in 004);
  every action in this module writes one row there.
- ``delete_subject_tx()`` — the transactional subject delete RPC.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from src.database.config import supabase

logger = logging.getLogger(__name__)

__all__ = [
    "PRIVACY_NOTICE_VERSION",
    "PRIVACY_NOTICE_TEXT",
    "GRIEVANCE_CONTACT",
    "CONSENT_PURPOSES",
    "record_consent",
    "withdraw_consent",
    "get_latest_consent",
    "has_active_consent",
    "record_parental_consent",
    "has_parental_consent",
    "get_student_dob",
    "is_under_18",
    "require_biometric_enrolment_allowed",
    "log_template_access",
    "log_breach_event",
    "get_access_summary",
    "delete_my_biometric_data",
    "correct_student_profile",
]

# --- Privacy notice ---------------------------------------------------------
# DPDP Act Sec. 5: every consent request must be preceded or
# accompanied by a notice, in clear and plain language, stating the
# personal data, the specified purpose, how rights may be exercised
# and how to complain to the Board. Versioned so a consent record
# can prove WHICH notice was shown (Sec. 6(10) burden of proof).
PRIVACY_NOTICE_VERSION = "1.0"

PRIVACY_NOTICE_TEXT = (
    "Smart Attendance — privacy notice (plain language).\n"
    "What we collect: your name, USN, a 4-6 digit PIN (stored only as a "
    "scrambled hash, never as the digits themselves), and — only if you "
    "choose face or voice login — a mathematical face/voice template "
    "(numbers describing your face/voice, not a photo or recording).\n"
    "Why: to mark your attendance in the subjects you join, and nothing "
    "else. We do not track you, profile you, or show you adverts.\n"
    "Photos and voice recordings are used once to make the template and "
    "then deleted immediately; they are never stored.\n"
    "Your choice: you never have to use face or voice. You can attend "
    "with your Student ID + PIN, or your teacher can mark you present "
    "manually — with no penalty and no difference in your record.\n"
    "Your rights: you can see everything we hold about you, correct "
    "your name, withdraw your consent, or delete your face/voice "
    "templates at any time from the 'My data & privacy' section. "
    "Withdrawing consent deletes your templates.\n"
    "Under 18: if you are under 18, a parent or guardian must also "
    "agree before any face/voice template is made.\n"
    "How long we keep it: your templates are deleted when you withdraw "
    "consent, when you leave the institution, or when the purpose ends. "
    "Attendance records are kept only as long as the institution needs "
    "them for academic records.\n"
    "Questions or complaints: contact the grievance officer below. "
    "You can also complain to the Data Protection Board of India."
)

# Grievance contact — DPDP Act Sec. 8(9) (publish a contact who can
# answer data questions) and Sec. 8(10) / Sec. 13 (grievance
# mechanism). PLACEHOLDER: there is no real grievance officer yet.
# Naman must fill in a real name/email before any deployment holding
# real student data; the placeholder address is deliberately invalid
# (".invalid" — RFC 2606) so it can never receive mail by accident.
GRIEVANCE_CONTACT = {
    "role": "Grievance Officer / Data Protection contact",
    "name": "TO BE CONFIGURED BY THE INSTITUTION",
    "email": "grievance-officer@example.invalid",
    "response_within_days": 90,  # DPDP Rules 2025 Rule 14(3): max 90 days
}

# Consent is purpose-limited (DPDP Sec. 6(1)): a grant for one purpose
# authorises nothing else. These are the only purposes this app records.
CONSENT_PURPOSES = ("biometric_attendance", "voice_attendance")

# Audit actions written to audit_log by this module. The action names
# are stable strings — do not rename them, operators query on them.
_AUDIT_CONSENT_RECORDED = "consent_recorded"
_AUDIT_CONSENT_WITHDRAWN = "consent_withdrawn"
_AUDIT_PARENTAL_CONSENT_RECORDED = "parental_consent_recorded"
_AUDIT_TEMPLATE_ACCESS = "template_access"
_AUDIT_BIOMETRIC_DATA_ERASED = "biometric_data_erased"
_AUDIT_PROFILE_CORRECTED = "profile_corrected"
_AUDIT_BREACH = "security_breach"

# Fields that must NEVER appear in an audit_log details object (or
# anywhere in logs): raw media, templates, credentials, tokens.
FORBIDDEN_AUDIT_KEYS = frozenset({
    "pin", "password", "pin_hash", "password_hash", "hash",
    "embedding", "face_embedding", "voice_embedding", "vector",
    "photo", "image", "audio", "recording", "token", "secret",
    "service_role", "api_key",
})


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit(action: str, actor_id: Optional[str], details: Dict[str, Any],
           record_id: Optional[str] = None,
           table_name: Optional[str] = None,
           client: Any = None) -> None:
    """Insert one append-only audit_log row. Never raises for a bad
    details payload: forbidden keys are rejected loudly (a caller bug),
    but a DB failure is logged, not raised, so auditing can never
    break the user-facing flow it records. ``client`` overrides the
    module Supabase client (tests pass their fake DB)."""
    bad = FORBIDDEN_AUDIT_KEYS.intersection(details.keys())
    if bad:
        raise ValueError(
            f"audit details must never contain {sorted(bad)} "
            "(raw media / templates / credentials are never logged)"
        )
    row = {
        "actor_id": actor_id,
        "action": action,
        "table_name": table_name,
        "record_id": record_id,
        "details": dict(details),
    }
    db = supabase if client is None else client
    try:
        db.table("audit_log").insert(row).execute()
    except Exception:
        # Audit failure must not break the flow; it is logged
        # server-side so the operator notices the gap.
        logger.exception("audit_log insert failed for action %s", action)


# --- Consent (DPDP Sec. 6) --------------------------------------------------

def record_consent(
    student_id: str,
    *,
    purpose: str = "biometric_attendance",
    version: str = PRIVACY_NOTICE_VERSION,
    granted_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a consent grant: clear affirmative action (Sec. 6(1)).

    Writes a ``consent_records`` row (student, purpose, version,
    granted=True, timestamp) AND an audit_log row, so the fiduciary
    can prove notice was given and consent taken (Sec. 6(10)).
    Returns the inserted consent row. Raises ValueError for an
    unknown purpose or an empty student id.
    """
    if not isinstance(student_id, str) or not student_id.strip():
        raise ValueError("student_id must be a non-empty string")
    if purpose not in CONSENT_PURPOSES:
        raise ValueError(f"unknown consent purpose: {purpose!r}")
    row = {
        "student_id": student_id.strip(),
        "purpose": purpose,
        "notice_version": version,
        "granted": True,
        "granted_at": _utcnow_iso(),
        "granted_by": granted_by,
    }
    response = supabase.table("consent_records").insert(row).execute()
    _audit(
        _AUDIT_CONSENT_RECORDED,
        actor_id=student_id.strip(),
        details={"purpose": purpose, "notice_version": version, "granted": True},
        record_id=student_id.strip(),
        table_name="consent_records",
    )
    rows = response.data or []
    return rows[0] if rows else dict(row)


def withdraw_consent(
    student_id: str,
    *,
    purpose: str = "biometric_attendance",
) -> Dict[str, Any]:
    """Record a consent withdrawal (DPDP Sec. 6(4)).

    Withdrawal must be as easy as giving consent, so this is a single
    call with no extra steps. It records granted=False AND an
    audit_log row. Withdrawing consent does not by itself erase
    templates — call :func:`delete_my_biometric_data` (or the
    combined ``withdraw_and_erase`` flow in the UI) so that the
    Sec. 8(7) erasure duty is also discharged; the audit row notes
    that erasure is still owed until it happens.
    """
    if not isinstance(student_id, str) or not student_id.strip():
        raise ValueError("student_id must be a non-empty string")
    if purpose not in CONSENT_PURPOSES:
        raise ValueError(f"unknown consent purpose: {purpose!r}")
    row = {
        "student_id": student_id.strip(),
        "purpose": purpose,
        "notice_version": PRIVACY_NOTICE_VERSION,
        "granted": False,
        "granted_at": _utcnow_iso(),
    }
    response = supabase.table("consent_records").insert(row).execute()
    _audit(
        _AUDIT_CONSENT_WITHDRAWN,
        actor_id=student_id.strip(),
        details={
            "purpose": purpose,
            "notice_version": PRIVACY_NOTICE_VERSION,
            "granted": False,
            "erasure_pending": True,
        },
        record_id=student_id.strip(),
        table_name="consent_records",
    )
    rows = response.data or []
    return rows[0] if rows else dict(row)


def get_latest_consent(
    student_id: str, *, purpose: str = "biometric_attendance"
) -> Optional[Dict[str, Any]]:
    """Latest consent record for a student+purpose, or None."""
    if not isinstance(student_id, str) or not student_id.strip():
        raise ValueError("student_id must be a non-empty string")
    response = (
        supabase.table("consent_records")
        .select("student_id, purpose, notice_version, granted, granted_at")
        .eq("student_id", student_id.strip())
        .eq("purpose", purpose)
        .order("granted_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return dict(rows[0]) if rows else None


def has_active_consent(
    student_id: str, *, purpose: str = "biometric_attendance"
) -> bool:
    """True iff the latest consent record for this purpose is a grant."""
    latest = get_latest_consent(student_id, purpose=purpose)
    return bool(latest and latest.get("granted") is True)


# --- Children / parental consent (DPDP Sec. 9) -------------------------------

def is_under_18(
    date_of_birth: Optional[Any] = None,
    *,
    is_minor: Optional[bool] = None,
    today: Optional[date] = None,
) -> bool:
    """True iff the student is under 18 (DPDP Sec. 2(3): child < 18).

    Pass ``date_of_birth`` ("YYYY-MM-DD" or a ``date``) or an explicit
    ``is_minor`` flag. If neither is given, FAIL CLOSED: return True
    (treat as a child) so the parental-consent gate cannot be skipped
    by omitting the age. An unparseable date also fails closed.
    """
    if is_minor is not None:
        return bool(is_minor)
    if date_of_birth is None:
        return True
    try:
        if isinstance(date_of_birth, date):
            dob = date_of_birth
        else:
            dob = date.fromisoformat(str(date_of_birth).strip()[:10])
    except (ValueError, TypeError):
        return True
    ref = today or date.today()
    age = ref.year - dob.year - ((ref.month, ref.day) < (dob.month, dob.day))
    return age < 18


def record_parental_consent(
    student_id: str,
    *,
    guardian_name: str,
    verified_by_teacher_id: str,
    method: str = "in_person",
    guardian_contact: Optional[str] = None,
) -> Dict[str, Any]:
    """Record verifiable parental / lawful-guardian consent (Sec. 9(1)).

    "Verifiable" here means: a named guardian, a verification method
    (``in_person`` — guardian showed ID to the teacher — is the only
    method this app accepts today; a phone/email OTP flow does not
    exist yet), and the teacher who verified it. The guardian's
    contact is stored only if supplied, for follow-up; it is never
    used for marketing or tracking (Sec. 9(3) forbids tracking /
    behavioural monitoring of children).
    """
    if not isinstance(student_id, str) or not student_id.strip():
        raise ValueError("student_id must be a non-empty string")
    if not isinstance(guardian_name, str) or not guardian_name.strip():
        raise ValueError("guardian_name must be a non-empty string")
    if not isinstance(verified_by_teacher_id, str) or not verified_by_teacher_id.strip():
        raise ValueError("verified_by_teacher_id must be a non-empty string")
    if method not in ("in_person",):
        raise ValueError(
            f"unknown parental-consent method: {method!r} "
            "(only 'in_person' verification exists today)"
        )
    row = {
        "student_id": student_id.strip(),
        "guardian_name": guardian_name.strip(),
        "guardian_contact": guardian_contact,
        "verification_method": method,
        "verified_by_teacher_id": verified_by_teacher_id.strip(),
        "verified_at": _utcnow_iso(),
    }
    response = supabase.table("parental_consents").insert(row).execute()
    _audit(
        _AUDIT_PARENTAL_CONSENT_RECORDED,
        actor_id=verified_by_teacher_id.strip(),
        details={
            "student_id": student_id.strip(),
            "verification_method": method,
        },
        record_id=student_id.strip(),
        table_name="parental_consents",
    )
    rows = response.data or []
    return rows[0] if rows else dict(row)


def has_parental_consent(student_id: str) -> bool:
    """True iff a parental-consent record exists for this student."""
    if not isinstance(student_id, str) or not student_id.strip():
        raise ValueError("student_id must be a non-empty string")
    response = (
        supabase.table("parental_consents")
        .select("student_id, verified_at")
        .eq("student_id", student_id.strip())
        .limit(1)
        .execute()
    )
    return bool(response.data)


def get_student_dob(student_id: str) -> Optional[str]:
    """A student's recorded date_of_birth ("YYYY-MM-DD"), or None.

    Returns None when the student has no DOB on file (all rows
    created before migration 005) — callers must decide what
    "unknown age" means for their flow; the registration flow fails
    closed on unknown age, while re-enrolment can only enforce the
    gate for students whose DOB is known (see
    ``student_face_dialog.add_face_scan_dialog`` and docs/privacy/dpia.md).
    """
    if not isinstance(student_id, str) or not student_id.strip():
        raise ValueError("student_id must be a non-empty string")
    response = (
        supabase.table("students")
        .select("student_id, date_of_birth")
        .eq("student_id", student_id.strip())
        .limit(1)
        .execute()
    )
    rows = response.data or []
    if not rows:
        return None
    return rows[0].get("date_of_birth")


def require_biometric_enrolment_allowed(
    student_id: str,
    *,
    date_of_birth: Optional[Any] = None,
    is_minor: Optional[bool] = None,
) -> None:
    """Fail-closed gate for biometric enrolment (DPDP Sec. 9(1)).

    Raises ``PermissionError`` when the student is under 18 and no
    parental-consent record exists. Adults pass. Age unknown also
    fails closed (see :func:`is_under_18`). Call this BEFORE any
    face/voice template is created or stored; the registration and
    re-enrolment screens must call it and refuse enrolment on
    ``PermissionError``.
    """
    if is_under_18(date_of_birth, is_minor=is_minor):
        if not has_parental_consent(student_id):
            raise PermissionError(
                "Biometric enrolment refused: student is under 18 and no "
                "verifiable parental consent is on record "
                "(DPDP Act 2023, Sec. 9(1)). Ask a parent or guardian to "
                "give consent in person to the teacher first."
            )


# --- Template-access audit logging (GDPR Art. 9 / SPEC Phase 3 item 2) -------

def log_template_access(
    student_id: str,
    *,
    template_kind: str,
    action: str,
    actor_id: Optional[str] = None,
    subject_id: Optional[str] = None,
    matched: Optional[bool] = None,
    client: Any = None,
) -> None:
    """Log one biometric-template read/match in audit_log.

    ``template_kind`` is ``"face"`` or ``"voice"``; ``action`` is a
    short verb such as ``"match"``, ``"gallery_load"`` or
    ``"verify_1to1"``. Only identifiers, counts and outcomes are
    logged — NEVER an embedding, a photo, audio, a score that could
    identify a person, or a credential (enforced by ``_audit``).
    Never raises: a logging failure must not break matching.
    """
    if template_kind not in ("face", "voice"):
        raise ValueError(f"template_kind must be 'face' or 'voice', got {template_kind!r}")
    if not isinstance(action, str) or not action.strip():
        raise ValueError("action must be a non-empty string")
    details: Dict[str, Any] = {
        "template_kind": template_kind,
        "access": action.strip(),
        "subject_id": subject_id,
    }
    if matched is not None:
        details["matched"] = bool(matched)
    _audit(
        _AUDIT_TEMPLATE_ACCESS,
        actor_id=actor_id or (student_id if isinstance(student_id, str) else None),
        details=details,
        record_id=student_id if isinstance(student_id, str) else None,
        table_name="face_embeddings" if template_kind == "face" else "voice_embeddings",
        client=client,
    )


# --- Breach logging (DPDP Sec. 8(5)-(6); Rules 2025 Rule 7) -----------------

def log_breach_event(
    *,
    breach_id: str,
    description: str,
    categories: List[str],
    affected_student_ids: Optional[List[str]] = None,
    notified_board: bool = False,
    notified_principals: bool = False,
    actor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Write a structured breach-log entry to audit_log.

    What is logged: a stable ``breach_id``, a plain-language
    description, the data categories involved (e.g. ``["face_templates"]``),
    HOW MANY principals are affected (a count — never their names,
    USNs, photos or templates), and whether the Board / affected
    principals have been told yet (Sec. 8(6) duty; Rule 7: first
    intimation to the Board without delay, detailed report within
    72 hours). What is NEVER logged: any personal data from the
    breach itself, any credential, template or raw media — enforced
    by ``_audit``'s forbidden-key check and by taking only a count
    of affected principals, not their identities.
    Returns the audit details written, so callers can show a
    reference to the operator.
    """
    if not isinstance(breach_id, str) or not breach_id.strip():
        raise ValueError("breach_id must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description must be a non-empty string")
    if not categories:
        raise ValueError("categories must be a non-empty list")
    details: Dict[str, Any] = {
        "breach_id": breach_id.strip(),
        "description": description.strip(),
        "categories": list(categories),
        "affected_count": len(affected_student_ids or []),
        "notified_board": bool(notified_board),
        "notified_principals": bool(notified_principals),
        "logged_at": _utcnow_iso(),
    }
    _audit(_AUDIT_BREACH, actor_id=actor_id, details=details)
    return details


# --- Access summary (DPDP Sec. 11) -------------------------------------------

def get_access_summary(student_id: str) -> Dict[str, Any]:
    """What data is held about one student (Sec. 11(1)(a)).

    Returns identity fields (never ``pin_hash``), enrolments, whether
    face/voice templates exist and how many (counts + model versions
    + newest date — NEVER the vectors themselves), the latest consent
    state, and attendance totals. This is what the in-app
    "My data & privacy" screen shows; the student never sees another
    student's summary (callers must check the requester owns this id).
    """
    if not isinstance(student_id, str) or not student_id.strip():
        raise ValueError("student_id must be a non-empty string")
    sid = student_id.strip()
    student_resp = (
        supabase.table("students")
        .select("student_id, usn, name")
        .eq("student_id", sid)
        .limit(1)
        .execute()
    )
    student = dict((student_resp.data or [{}])[0]) if student_resp.data else {}
    enrol_resp = (
        supabase.table("subject_students")
        .select("student_id, subject_id, enrolled_at")
        .eq("student_id", sid)
        .execute()
    )
    enrolments = enrol_resp.data or []
    face_resp = (
        supabase.table("face_embeddings")
        .select("student_id, model_version, created_at")
        .eq("student_id", sid)
        .execute()
    )
    face_rows = face_resp.data or []
    voice_resp = (
        supabase.table("voice_embeddings")
        .select("student_id, model_version, created_at")
        .eq("student_id", sid)
        .execute()
    )
    voice_rows = voice_resp.data or []
    logs_resp = (
        supabase.table("attendance_logs")
        .select("id, is_present")
        .eq("student_id", sid)
        .execute()
    )
    logs = logs_resp.data or []
    consent = get_latest_consent(sid)
    return {
        "student": student,
        "enrolments": [
            {"subject_id": e.get("subject_id"), "enrolled_at": e.get("enrolled_at")}
            for e in enrolments
        ],
        "face_templates": {
            "count": len(face_rows),
            "model_versions": sorted(
                {r.get("model_version") for r in face_rows if r.get("model_version")}
            ),
            "newest_at": max((r.get("created_at") or "" for r in face_rows), default=None),
        },
        "voice_templates": {
            "count": len(voice_rows),
            "model_versions": sorted(
                {r.get("model_version") for r in voice_rows if r.get("model_version")}
            ),
            "newest_at": max((r.get("created_at") or "" for r in voice_rows), default=None),
        },
        "attendance": {
            "total_logs": len(logs),
            "present": sum(1 for r in logs if r.get("is_present")),
        },
        "consent": consent,
        # Sec. 11(1)(b): who the data was shared with. This deployment
        # shares personal data with nobody except the Supabase host
        # (processor) and the ML worker (processor); both are listed in
        # the privacy notice. There is no third-party sharing to list.
        "shared_with": [
            {"recipient": "Supabase (database host / processor)", "data": "all stored rows"},
            {"recipient": "ML worker (processor)",
             "data": "templates + job payloads, in memory only"},
        ],
    }


# --- Correction + erasure (DPDP Sec. 12) --------------------------------------

def correct_student_profile(
    student_id: str, *, name: Optional[str] = None
) -> Dict[str, Any]:
    """Self-service correction of a student's own name (Sec. 12(1)).

    Only the name can be corrected here — USN is the institutional
    identifier and is corrected by the teacher, not self-service.
    Writes the change and an audit_log row (old value is NOT put in
    the audit row: it is personal data, and the audit trail needs
    only the fact of the correction, not a copy of the data).
    """
    if not isinstance(student_id, str) or not student_id.strip():
        raise ValueError("student_id must be a non-empty string")
    if name is None:
        raise ValueError("nothing to correct: pass name=")
    clean = name.strip()
    if not clean or len(clean) > 100:
        raise ValueError("name must be 1-100 characters")
    response = (
        supabase.table("students")
        .update({"name": clean})
        .eq("student_id", student_id.strip())
        .execute()
    )
    _audit(
        _AUDIT_PROFILE_CORRECTED,
        actor_id=student_id.strip(),
        details={"field": "name"},
        record_id=student_id.strip(),
        table_name="students",
    )
    rows = response.data or []
    return rows[0] if rows else {"student_id": student_id.strip(), "name": clean}


def delete_my_biometric_data(
    student_id: str,
    *,
    reason: str = "data_principal_request",
) -> Dict[str, Any]:
    """Self-service "Delete My Biometric Data" (DPDP Sec. 12(2), 8(7)).

    REAL delete path, not a stub: removes every row for this student
    from ``face_embeddings`` and ``voice_embeddings`` (the Phase 1
    pgvector template tables), AND nulls the legacy
    ``students.face_embedding`` / ``students.voice_embedding``
    columns, then writes an audit_log row. Attendance logs and the
    identity row are NOT deleted — attendance is the academic record
    (retention for that purpose is separate), and erasing the
    identity row would orphan it; a full account deletion is a
    teacher/admin action, not self-service. The audit row records
    counts only, never template data. Returns a summary dict.
    """
    if not isinstance(student_id, str) or not student_id.strip():
        raise ValueError("student_id must be a non-empty string")
    sid = student_id.strip()
    face_resp = (
        supabase.table("face_embeddings").delete().eq("student_id", sid).execute()
    )
    voice_resp = (
        supabase.table("voice_embeddings").delete().eq("student_id", sid).execute()
    )
    legacy_resp = (
        supabase.table("students")
        .update({"face_embedding": None, "voice_embedding": None})
        .eq("student_id", sid)
        .execute()
    )
    summary = {
        "student_id": sid,
        "face_templates_deleted": len(face_resp.data or []),
        "voice_templates_deleted": len(voice_resp.data or []),
        "legacy_templates_cleared": bool(legacy_resp.data),
        "reason": reason,
        "deleted_at": _utcnow_iso(),
    }
    _audit(
        _AUDIT_BIOMETRIC_DATA_ERASED,
        actor_id=sid,
        details={
            "face_templates_deleted": summary["face_templates_deleted"],
            "voice_templates_deleted": summary["voice_templates_deleted"],
            "reason": reason,
        },
        record_id=sid,
        table_name="face_embeddings",
    )
    return summary
