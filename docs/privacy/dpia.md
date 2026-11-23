# Data Protection Impact Assessment (DPIA) + proportionality notes

Smart Attendance processes biometric data (face/voice templates) to
mark classroom attendance. Biometric data is a special category
(GDPR Art. 9, https://gdpr-info.eu/art-9-gdpr/) and, under the
India DPDP Act 2023, needs consent with notice (Secs. 5–6) and
verifiable parental consent for under-18s (Sec. 9(1)). This note is
the proportionality assessment and the DPIA record for the project.
It is a living document: re-review it before any deployment, and
again whenever the purpose, the data, or the vendors change.

## 1. Purpose and necessity

- **Purpose:** mark attendance in a class the student joined.
  Nothing else. No tracking, no profiling, no advertising, no
  emotion/behaviour analysis, no sharing with third parties.
- **Why biometrics at all:** speed and convenience for large
  classes (group photo / classroom audio instead of a roll call).
  Attendance itself does not need biometrics — a teacher with a
  list can do it — so biometrics are an optional convenience, not
  a necessity. That is exactly why the non-biometric fallback is
  load-bearing (see §3).

## 2. Proportionality

| Question | Answer |
|---|---|
| Is the data minimised? | Yes: only a template (512-d face / 192-d voice numbers) is stored, never a photo or recording. Raw media is processed in memory and deleted immediately after inference (SPEC constraint; `worker/stores.py`, `worker/runner.py`, `src/ui/uploads.py`). |
| Is the scope limited? | Yes: 1:N matching is scoped to the enrolled roster of one subject only; 1:1 login verifies against the claimed student's template only. |
| Is retention limited? | Templates are deleted on consent withdrawal, on purpose end (DPDP Sec. 8(7)), or via self-service "Delete My Biometric Data" (Sec. 12(2)). Attendance logs (the academic record) are retained separately and are not biometric data. |
| Are children protected? | Under-18s need verifiable parental consent before any template is made (Sec. 9(1)). Registration fails closed to PIN-only for minors with no parental record. No tracking or behavioural monitoring of children (Sec. 9(3)) — the app does none of it for anyone. |
| Is consent genuinely free? | Only because the fallback exists (§3). Without it, "consent or no attendance" would not be free consent (GDPR Art. 7(4); DPDP Sec. 6(1)). |

## 3. Non-biometric fallback (consent must be free)

A student can attend without biometrics, with no penalty:

- **Student ID + PIN login** (in-app, "Student ID & PIN" tab) — stated
  explicitly on the login screen.
- **Teacher manual marking** — the teacher can mark any student
  present/absent from Attendance Records / session detail.
- **QR / join code** enrolment does not require biometrics.

A student who deletes their templates keeps their account, their
enrolments and their attendance record, and can still attend by PIN
or manual marking. Withdrawing consent never deletes attendance
already recorded (that would falsify the academic record) and never
blocks future attendance.

## 4. Risks and mitigations

| Risk | Likelihood / impact | Mitigation (implemented) |
|---|---|---|
| Template leak → irreversible biometric compromise (templates cannot be revoked like a password) | Medium / High | Templates separated from identity data (`face_embeddings` / `voice_embeddings` hold only student_id + vector + model metadata — no names/USNs/PINs); strict RLS (student sees own rows; teacher sees only students they teach); encryption at rest is the Supabase platform setting (see §5); audit_log records every template read/match. Cancelable templates are future work (§6). |
| Spoofing (printed photo / replayed audio) | Medium / Medium | Phase 2 PAD (MiniFASNet/CDCN) + AASIST + active challenges; heuristic liveness is NOT claimed as PAD. **Not evaluated yet** — no labelled classroom set, thresholds uncalibrated. Face login is a convenience factor, not a security boundary. |
| Function creep (templates reused for another purpose) | Low / High | Consent is purpose-limited (`consent_records.purpose`); the notice states the single purpose; any new purpose needs a new notice + new consent (DPDP Sec. 6). |
| Child enrolled without parental consent | Medium / High | Fail-closed gate at registration (PIN-only for minors) + gate on face re-enrolment for known minors + teacher-recorded `parental_consents` table. **Known gap:** students registered before migration 005 have no date of birth on file, so the re-enrolment gate cannot evaluate them — DOB backfill is an open task for Naman (see §7). |
| Breach goes unnoticed / unreported | Low / High | Structured breach log (`privacy.log_breach_event`, audit_log `security_breach`): what to log (breach id, categories, affected COUNT, notification status) and what never to log (no personal data from the breach, no credentials/templates/media). Board + affected principals must be told (DPDP Sec. 8(6); Rules 2025 Rule 7: first intimation without delay, detailed report within 72 hours). |
| Over-collection via raw media retention | Low / High | Raw photos/audio are never written to disk or object storage after processing (tested: `tests/test_phase3_privacy.py::test_no_raw_media_written_to_disk`). Worker payloads live in memory and are popped after use. |
| Leaked service_role key | Low / Critical | The key lives in the worker environment only, never in Streamlit code or secrets; the UI uses the anon key + RLS. |

## 5. Templates: storage, encryption, RLS

- **Separation:** templates live in `face_embeddings` / `voice_embeddings`
  (migration 004), separate from the `students` identity rows. The
  embedding tables carry no names, USNs or PIN hashes.
- **Encryption at rest:** this is a **Supabase platform setting**
  (Supabase encrypts Postgres data at rest), NOT app-level
  encryption. The app does not encrypt vectors itself and does not
  claim to. If a deployment needs app-level encryption, that is a
  separate design decision (key management) — not built here.
- **RLS:** students can read/write only their own template rows
  (`student_is_self`); teachers can read templates only of students
  enrolled in subjects they own (`teacher_teaches_student`); anon
  sees nothing (migrations 001/003/004/005).
- **Access logging:** every template read/match is written to
  `audit_log` (`template_access`) — UI side in
  `src/database/vector.py:match_faces`, worker side in
  `worker/gallery.py` (gallery load) and `worker/runner.py` (match).
  Audit rows carry identifiers + counts only, never vectors.

## 6. Cancelable templates (future / optional — NOT built)

See `docs/privacy/cancelable-templates.md`. ISO/IEC 24745
biometric template protection (cancelable / renewable templates)
is documented as a future option only. Do not claim it exists.

## 7. Open items before production use

- [ ] DOB backfill for the 8 legacy students (or record them as adults
      with evidence) so the under-18 gate covers re-enrolment.
- [ ] Real grievance officer name/email (currently a `.invalid`
      placeholder) + a published rights-request process (DPDP Rules
      2025, Rule 14).
- [ ] Run migration 005 live (consent tables + `delete_subject_tx`).
- [ ] Calibrate PAD + matching thresholds on a labelled classroom set
      (`scripts/evaluate_biometrics.py`) — until then, PAD and the
      0.38/0.85 thresholds are uncalibrated starting points.
- [ ] Legal review of this DPIA + the privacy notice by a qualified
      data-protection lawyer; this document is an engineering record,
      not legal advice.
- [ ] Confirm the institution's retention period for attendance logs
      and the purpose-end erasure schedule (DPDP Sec. 8(7)–(8)).

## References

- DPDP Act 2023 official text: https://www.indiacode.nic.in/bitstream/123456789/22037/2/a2023-22.pdf
- GDPR Art. 9: https://gdpr-info.eu/art-9-gdpr/
- AEPD biometric attendance guidelines: https://www.aepd.es/guides/guidelines-clocking-and-attendance-control-processing-using-biometric-systems.pdf
- ISO/IEC 24745 (template protection): see cancelable-templates.md
- OWASP Authentication / Password Storage cheat sheets: https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
