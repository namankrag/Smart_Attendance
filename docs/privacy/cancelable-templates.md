# Cancelable templates — FUTURE / OPTIONAL, NOT BUILT

> **Status: documented only. Do not claim this exists in the app.**
> This note records the design option so a future phase can pick it
> up without re-doing the research. Nothing in this file is
> implemented, and no code in the repo depends on it.

## What it is

ISO/IEC 24745 ("Biometric information protection",
https://www.iso.org/standard/75302.html) defines how biometric
templates can be protected so that a leaked template can be
**cancelled and re-issued** — like revoking a password — instead of
being compromised forever. The standard's properties:

- **Irreversibility:** the protected template must not reveal the
  original biometric data (or the raw template).
- **Unlinkability:** protected templates from the same person in
  different systems must not be linkable to each other.
- **Renewability / revocability:** if a protected template leaks,
  issue a new one from the same biometric (e.g. with a new key or
  transform) and the old one stops working.

Background survey: "Biometric template protection" overview,
https://www.arxiv.org/pdf/2303.02715

## Why it matters here

Today the app stores raw embedding vectors (512-d face, 192-d
voice) in pgvector. If those leak, the student cannot "change"
their face — a new scan produces a similar vector. That is the
single biggest residual risk in `docs/privacy/dpia.md` (§4).
Cancelable templates are the principled fix; platform encryption
at rest + RLS are mitigations, not a fix.

## Candidate approaches (for a future phase — pick one, then evaluate)

1. **BioHashing / random-projection transforms:** apply a
   user-specific random projection + binarisation to the embedding
   before storage; matching happens in the transformed domain.
   Cheap, but security depends on keeping the projection secret,
   and accuracy loss must be measured (FMR/FNMR per ISO/IEC
   19795-1).
2. **Fuzzy vault / fuzzy commitment:** bind the template to a key
   that can be revoked; needs a helper-data store and careful
   error-correction tuning for embedding noise.
3. **Homomorphic-encryption matching:** match on encrypted vectors
   without decrypting. Strongest privacy, but heavy (latency,
   key management) and overkill for classroom attendance.
4. **Template encryption with a per-student key in a KMS/HSM:**
   not cancelable in the ISO sense (a key leak re-exposes the
   template), but revocable at the key level. Simplest to build;
   say so honestly if chosen.

## What a future implementation must do

- [ ] Choose one approach and record the choice + rationale.
- [ ] Measure the accuracy cost on the labelled classroom set
      (`scripts/evaluate_biometrics.py`): FMR/FNMR/EER before and
      after the transform, split by subgroup/condition.
- [ ] Prove unlinkability + irreversibility for the chosen scheme
      (or state clearly which properties it does NOT provide).
- [ ] Migration plan: re-enrol every student (old raw templates
      must be deleted, not converted — conversion cannot remove
      the already-stored raw vector from backups).
- [ ] Key/transform storage and rotation procedure, with the
      keys/transforms kept out of the database that holds the
      protected templates (separation of duties).
- [ ] Update the privacy notice + DPIA: the notice must say how
      templates are protected, in plain language.

## Non-goals

- This is not a commitment to build any of the above in Phase 3.
- Do not present platform encryption at rest as cancelable
  templates — they are different things.
