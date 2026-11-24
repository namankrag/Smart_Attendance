# Preflight log — migrations 004 and 005 (Smart Attendance)

Date: 2026-11-22. Author: preflight subagent. Skill followed:
`~/workspace/custom-skills/live_migration_preflight/SKILL.md`.

## Verdict

**004 and 005 PASS on a restored copy — after three fixes to 004.**
The original 004 file FAILED two of its own checks on the copy
(see "Defects found"). The fixed 004 plus 005 were re-run on a
freshly restored copy: 001 → 002 → 003 → 004 → 005 all exit 0 and
COMMIT, all footer verification queries match expectations, and
second runs of 004 and 005 also COMMIT (idempotent).

**Nothing was run live against Supabase. No live migration is
authorised by this preflight alone.**

## Environment (this VM)

- OS: Ubuntu 24.04.5 LTS. No Postgres was installed; installed via apt:
  `postgresql-16` (server 16.15), `postgresql-server-dev-16`,
  `build-essential`, `git`.
- Postgres server used: **16.15** (local cluster, socket
  `/tmp/pgpreflight`, port 54399, data dir `/tmp/pgpreflight/data`,
  database `smartclass_preflight`). Live Supabase is Postgres 17 —
  see "Fidelity gaps".
- pgvector: Ubuntu's `postgresql-16-pgvector` is **0.6.0**, below
  004's 0.8.0 floor, so it was NOT used. pgvector **0.8.0** was built
  from source (`git clone --branch v0.8.0`, `make && make install`)
  and verified: `select extversion …` → `0.8.0`.
  - Note: during the pgvector build step a permission-approval prompt
    timed out unanswered; the build itself completed (BUILD_EXIT 0)
    and `vector.so` / `vector--0.8.0.sql` were verified present
    afterwards. No step was retried on the basis of that approval.
- `pg_restore` 16 refused the backup: `unsupported version (1.16)
  in file header` (the dump was written by pg_dump 17). Installed
  `postgresql-client-17` (17.12) from the PGDG apt repo for
  `pg_restore` only. A PG 17 **server** could not be installed:
  PGDG's `postgresql-17` needs `libllvm19`, which does not exist in
  Ubuntu noble at all. Hence the PG 16 server + pg_restore 17
  combination (fidelity gap, below).

## Backup / restore (skill: fresh backup first — LIMITATION)

- **No fresh backup was taken.** There is no live DB access for
  `pg_dump` from this VM (only anon PostgREST reads), and the only
  backup on file is `~/workspace/user/files/smartclass-backup-2026-11-22.dump`
  (407K, verified PostgreSQL custom dump v1.16-0). **That backup
  predates migrations 001–003 and cannot restore current live state.**
  004's Step 9 drops `*_legacy` columns destructively, so a fresh
  backup is still REQUIRED before any live run of 004.
- What was done instead (per task): the old backup was restored into
  the separate local database, then 001 → 002 → 003 were replayed to
  rebuild the pre-004 live-equivalent schema.
- Restore method: `pg_restore -l` (648 entries) filtered to the 30
  entries for the five `public` tables (tables, sequences, data, PKs,
  FKs, unique constraints). `auth`/`realtime`/`storage` schemas were
  NOT restored (not needed; 001–005 only touch `public` + `auth.uid()`).
- Restore result: **success**. One harmless error only:
  `ERROR: unrecognized configuration parameter "transaction_timeout"`
  (pg_restore 17 emits `SET transaction_timeout = 0;`, a PG 17-only
  GUC; PG 16 ignores it; exit code 1 solely for that line).
- Restored counts — identical to the recorded live counts:
  students 8, teachers 1, subjects 2, subject_students 8,
  attendance_logs 38. All 8 students had `pin_hash` NULL.
- Restored schema matched 001's assumptions exactly: bigint identity
  PKs (`students_pkey`, `teachers_pkey`, `subjects_pkey`,
  `subject_students_pkey`), FKs
  (`attendance_logs_student_id_fkey`, `attendance_logs_subject_id_fkey`,
  `subject_students_student_id_fkey`, `subject_students_subject_id_fkey`,
  `subjects_teacher_id_fkey`), `attendance_logs(id, timestamp,
  subject_id, student_id, is_present)`,
  `students(student_id, name, face_embedding jsonb, voice_embedding
  jsonb, pin_hash)`. `subject_students` also already carried
  `unique_student_subject_enrollment (student_id, subject_id)`.

## Local stand-ins (fidelity gaps — read before trusting the pass)

- `auth` schema does not exist in local Postgres. Created a stub:
  `create schema auth; auth.uid() returns uuid` returning NULL
  (later temporarily redefined to a fixed UUID for the
  `delete_subject_tx` success-path test, then reset to NULL).
  RLS behaviour with a real signed-in user cannot be tested here;
  only the anon (uid NULL) deny path was tested.
- Supabase roles `anon`, `authenticated`, `service_role` were created
  as NOLOGIN roles. Local tables have no grants to `anon` by default
  (unlike Supabase, where PostgREST reads work); `GRANT SELECT` was
  issued in the test DB for the anon RLS checks. Grant state is a
  local artefact, not part of the migrations.
- Live is Postgres 17; this preflight ran on Postgres 16.15.
  Anything PG 17-specific in 004/005 would not be caught here.
  (Both files use only features available in 15+, e.g.
  `security_invoker` views.)
- The copy starts from the pre-001 backup, NOT from current live
  state. If live has drifted since 001–003 (new rows, new columns,
  changed constraints), this preflight does not see it.

## Migration runs (first copy)

| Step | File | Result |
|---|---|---|
| 001 | `001_phase0_core.sql` | exit 0, COMMIT. 8 students, 2 subjects, 38 logs preserved; 7 `attendance_sessions` backfilled from distinct (subject, timestamp) groups; `students.student_id` now uuid, `student_id_legacy` bigint kept. Only NOTICEs (policies not existing yet on first run). |
| 002 | `002_phase0_pin_enforcement.sql` | **Aborted by design** (psql exit 3): `Phase 0 PIN guard: 8 student(s) have no pin_hash…` — no constraint added, transaction rolled back, 8 PINs still NULL. Confirms the guard works. |
| 002 retry | after dummy PINs (see below) | exit 0, COMMIT. `pin_hash` NOT NULL, 0 NULLs. |
| 003 | `003_fix_rls_recursion.sql` | exit 0, COMMIT. 4 helpers + 9 policies present. |
| 004 (original) | `004_phase1_pgvector.sql` | exit 0, COMMIT — **but 2 defects found by verification** (below). `NOTICE: pgvector 0.8.0 OK`. |
| 005 | not run on first copy | deferred until 004 was fixed and a fresh copy restored. |

Dummy PINs (local copy ONLY, clearly labelled, never real hashes):
`update students set pin_hash = 'DUMMY-PREFLIGHT-ONLY-NOT-A-REAL-HASH-' || usn`
— 8 rows. Required because 002 aborts by design on the PIN-less
restored copy. The same dummy update was used on the fresh copy.

## Defects found in 004 (all fixed, regression-tested)

### A. `subjects.teacher_id_legacy` never dropped — Step 9 incomplete
- 001 Step 6 renames `subjects.teacher_id` (bigint) →
  `teacher_id_legacy` before `teacher_uuid` becomes `teacher_id`.
  004 Step 9 dropped the other seven `*_legacy` columns but not this
  one. 004's own verification query
  (`… where column_name like '%_legacy'`) returned **1 row**
  (`subjects.teacher_id_legacy`) instead of 0.
- Fix: added
  `alter table subjects drop column if exists teacher_id_legacy;`
  to Step 9, with a comment citing this preflight.

### B. `match_faces()` global and large-roster paths fail — STABLE + SET LOCAL
- `match_faces` was declared `STABLE`, but its global path
  (`p_subject_id NULL`) and its >500-roster path run
  `SET LOCAL hnsw.iterative_scan = 'relaxed_order'`. Postgres
  rejects that in a non-volatile function. Observed on the copy:
  `ERROR: SET is not allowed in a non-volatile function`
  (PL/pgSQL function `match_faces`, line 14). The small-roster
  (≤500) path worked, which is why the defect hid.
- This would fail live the same way (the restriction is not
  version-specific). The global path is the registration
  duplicate-face check, so this was a live-blocking defect.
- Fix: `match_faces` is now `VOLATILE` (comment explains why; the
  function only reads, but VOLATILE is required for `SET LOCAL`).

### C. pgvector version guard used lexicographic text comparison (latent)
- `if v_version < '0.8.0'` compares text, so a future pgvector
  `0.10.0` would be wrongly rejected (`'1' < '8'`). The file's own
  comment claimed lexicographic compare was safe — it is not for
  two-digit components.
- Fix: `if string_to_array(v_version, '.')::int[] < array[0, 8, 0]`.
  Verified in SQL: `0.10.0` → not rejected, `0.7.4` → rejected,
  `0.8.0` → not rejected.

No defects were found in 005 by static trace or by running it
(policies call SECURITY DEFINER helpers only; `delete_subject_tx`
is VOLATILE by default and uses no `SET LOCAL`).

## RLS trace (004 + 005) — no 42P17
- Every policy in 004/005 calls a SECURITY DEFINER helper
  (`student_is_self`, `teacher_teaches_student`,
  `teacher_owns_subject`, `student_enrolled_in_subject`) and no
  policy `USING` clause directly `EXISTS`-selects from another
  RLS-protected table. Helpers are defined in 001/003 (004) and 004
  (005's `teacher_teaches_student`).
- Tested as `anon` (uid NULL, after `GRANT SELECT`): `face_embeddings`
  0 rows, `voice_embeddings` 0, `inference_jobs` 0, `students` 0,
  `subjects` 0, `attendance_logs` 0, `consent_records` 0,
  `parental_consents` 0 — no error, no 42P17 infinite recursion.
  (Note: before the grant, anon got `permission denied` — a local
  grant artefact, not an RLS result.)

## Fresh-copy re-run (after the fixes, per the skill)

Fresh database restored from the same old backup, full chain replayed:
001 exit 0, 002 exit 0 (dummy PINs), 003 exit 0, **004 (fixed) exit 0**,
**005 exit 0**. Second runs of 004 and 005: exit 0, COMMIT
(idempotent).

Expected verification results on the fresh copy (all observed):

- `select extversion … where extname='vector'` → `0.8.0`
- `face_embeddings` / `voice_embeddings` / `inference_jobs` /
  `consent_records` / `parental_consents` → 0 rows each
- `enrollments` view → 8 rows, same as `subject_students`
- `v_session_counts` → 2 rows (one per subject: 5 and 2 sessions)
- `v_attendance_percentages` → rows present; `date_of_birth` column
  exists on `students` (`date`)
- `… where column_name like '%_legacy'` → **0 rows** (fix A)
- Functions present: `match_faces`, `attendance_percentage`,
  `delete_subject_tx`, `teacher_teaches_student`
- HNSW indexes: `idx_face_embeddings_hnsw`,
  `idx_voice_embeddings_hnsw`

Functional checks on the fresh copy (dummy data, local only):

- `match_faces` global path (fix B): with two orthogonal dummy
  512-d vectors (e1/e2 basis vectors), returns both students,
  similarities 1.0000 / 0.0000 — correct. Roster path: same result
  for the enrolled subject. (First attempt used one `random()` array
  expression shared by both rows, producing two identical vectors
  and two 1.0000 similarities — a test-data artefact, not a
  function bug; re-tested with distinct basis vectors.)
- `attendance_percentage(student, subject)` returns a row (0 total /
  0 present — see the enrolled_at note below).
- `consent_records` + `parental_consents` inserts succeed (1 row
  each, test rows left in the local copy only).
- `delete_subject_tx`: ownership-failure path with `auth.uid()` NULL
  raises `42501 'subject does not exist or does not belong to this
  teacher'`; success path (teacher `auth_user_id` set to a fixed
  UUID in the local copy, `auth.uid()` stubbed to return it) inside
  a rolled-back transaction returned
  `{"attendance_logs_deleted": 4, "attendance_sessions_deleted": 2,
  "enrolments_deleted": 2}` and the rollback restored subjects = 2,
  logs = 38 — all-or-nothing confirmed. Stub and teacher row were
  reset afterwards.

## Historical `enrolled_at` backfill
- Migration 001 initially set `subject_students.enrolled_at` to migration
  time for pre-existing enrollments. This caused sessions recorded before
  migration 001 to be excluded from student totals by the audit-27 rule.
- Migration 006 repairs these rows using each student's first linked
  attendance session. Enrollments without attendance logs keep their
  existing timestamp.

## Tests
- New: `tests/test_migration_004_005_preflight.py` — 7 tests
  (legacy-drop completeness incl. `subjects.teacher_id_legacy`,
  `match_faces` VOLATILE, numeric version guard, no `SET LOCAL` in
  a non-volatile function in 005, RLS helpers-only in 004/005,
  005 tables/RLS/`delete_subject_tx`).
- `pytest tests/test_migration_004_005_preflight.py
  tests/test_migration_phase1.py tests/test_migration_sql.py
  tests/test_phase3_privacy.py -q` → **56 passed**.

## Files changed
- `migrations/004_phase1_pgvector.sql` — three fixes (A, B, C above).
  No other migration file was changed. 005 unchanged.
- `tests/test_migration_004_005_preflight.py` — new, 7 tests.
- This log: `PREFLIGHT_004_005.md`.
- Raw per-run logs (ephemeral, `/tmp/pgpreflight/`): `restore.log`,
  `mig001.log`, `mig002_abort.log`, `mig002.log`, `mig003.log`,
  `mig004.log`, `restore2.log`, `r2_mig001.log`, `r2_mig002.log`,
  `r2_mig003.log`, `r2_mig004.log`, `r2_mig005.log`,
  `r2_mig004_rerun.log`, `r2_mig005_rerun.log`. The local cluster
  was stopped after the run.

## What remains untested / required before any live run
1. **Fresh backup of live is still REQUIRED.** No fresh backup
   exists; the only backup predates 001–003. Take one (Supabase
   Database > Backups or `pg_dump`) and verify it before running 004
   live — 004's legacy-column drops are destructive and irreversible
   without it.
2. Live is Postgres 17; this preflight ran on 16.15. A final live
   run in the Supabase SQL Editor is still the real check.
3. Live state may have drifted since 001–003 (new rows/columns);
   re-check the `*_legacy` columns and UUID PKs live before 004.
4. RLS with a real signed-in teacher/student (non-NULL `auth.uid()`)
   was not tested — only the anon deny path, with a stubbed
   `auth.uid()`. The positive path (teacher reads own embeddings,
   student reads own consent) needs a live or auth-stubbed check
   with real linked `auth_user_id`s.
5. `match_faces` >500-roster HNSW path was not executed (roster is
   8); it shares the fixed `SET LOCAL` code with the global path,
   which was executed and now passes.
6. No model weights / real embeddings were involved; `match_faces`
   was tested with synthetic basis vectors only.
7. **Do NOT run 004/005 live from this preflight alone without
   Naman's explicit approval** (standing rule: stop per phase, no
   live migrations without his say-so).
