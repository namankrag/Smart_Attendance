# Privacy notice — Smart Attendance (plain language)

Version 1.0 — the same text is shown in the app at registration
(`src/database/privacy.py: PRIVACY_NOTICE_TEXT`) and in the
"My data & privacy" section of the student dashboard. The in-app
text is authoritative; this file is the reviewable copy.

> **Smart Attendance — privacy notice (plain language).**
> What we collect: your name, USN, a 4–6 digit PIN (stored only as a
> scrambled hash, never as the digits themselves), and — only if you
> choose face or voice login — a mathematical face/voice template
> (numbers describing your face/voice, not a photo or recording).
> Why: to mark your attendance in the subjects you join, and nothing
> else. We do not track you, profile you, or show you adverts.
> Photos and voice recordings are used once to make the template and
> then deleted immediately; they are never stored.
> Your choice: you never have to use face or voice. You can attend
> with your Student ID + PIN, or your teacher can mark you present
> manually — with no penalty and no difference in your record.
> Your rights: you can see everything we hold about you, correct
> your name, withdraw your consent, or delete your face/voice
> templates at any time from the "My data & privacy" section.
> Withdrawing consent deletes your templates.
> Under 18: if you are under 18, a parent or guardian must also
> agree before any face/voice template is made.
> How long we keep it: your templates are deleted when you withdraw
> consent, when you leave the institution, or when the purpose ends.
> Attendance records are kept only as long as the institution needs
> them for academic records.
> Questions or complaints: contact the grievance officer below. You
> can also complain to the Data Protection Board of India.

## Legal basis (verified against the Act text, 2026-11-22)

| Requirement | Citation |
|---|---|
| Notice in plain language, before/with consent | DPDP Act 2023, Sec. 5; DPDP Rules 2025, Rule 3 |
| Consent: free, specific, informed, unconditional, unambiguous, clear affirmative action | Sec. 6(1) |
| Withdrawal as easy as giving consent | Sec. 6(4) — not Sec. 6(5) (consequences of withdrawal) |
| Cease processing within a reasonable time after withdrawal | Sec. 6(6) |
| Burden of proving notice + consent is on the fiduciary | Sec. 6(10) — hence consent is recorded with timestamp + notice version |
| Verifiable parental consent for under-18s | Sec. 9(1); child = under 18, Sec. 2(3) |
| No tracking / behavioural monitoring / targeted ads at children | Sec. 9(3) |
| Security safeguards; breach intimation to Board + affected principals | Sec. 8(5), 8(6); Rules 2025, Rules 6–7 |
| Erasure when consent withdrawn or purpose no longer served | Sec. 8(7) |
| Publish a contact who can answer data questions | Sec. 8(9) |
| Grievance redressal mechanism | Sec. 8(10) (duty) / Sec. 13 (the Data Principal's right) |
| Access: summary of data + processing + who it was shared with | Sec. 11(1) |
| Correction, completion, updating, erasure | Sec. 12(1)–(2); processors must erase too, Sec. 12(3) |
| Grievance response time | DPDP Rules 2025, Rule 14(3): max 90 days |
| Biometric data is a special category | GDPR Art. 9 — https://gdpr-info.eu/art-9-gdpr/ |

Official text: https://www.indiacode.nic.in/bitstream/123456789/22037/2/a2023-22.pdf

Commencement note: the core duties (Secs. 3–17) come into force
13 May 2027 (G.S.R. 843(E), 13 Nov 2025). This app implements them
now, ahead of that date.

## Grievance contact

**PLACEHOLDER — fill in before any deployment holding real student data.**

- Role: Grievance Officer / Data Protection contact
- Name: TO BE CONFIGURED BY THE INSTITUTION
- Email: grievance-officer@example.invalid (deliberately invalid — RFC 2606
  `.invalid` — so it can never receive mail by accident)
- Response within: 90 days (DPDP Rules 2025, Rule 14(3))
