# Runbook — migrations 004 then 005 (live, Supabase SQL Editor)

Project: `tomhefyrrwjdyaddlidg` (Supabase). Files:
`migrations/004_phase1_pgvector.sql` (417 lines) then
`migrations/005_phase3_privacy.sql` (195 lines).
Each file runs in ONE transaction (`begin … commit`); a failure rolls
back cleanly. Both are idempotent on re-run.

**Status: PREFLIGHTED, NOT RUN LIVE.** See `PREFLIGHT_004_005.md` in
the repo root. On 2026-11-22 the chain 001 → 002 → 003 → 004 → 005
was replayed on a restored copy of the pre-001 backup in local
Postgres 16.15 with pgvector 0.8.0: all exit 0 / COMMIT, all footer
verification queries matched, second runs also COMMIT. Three defects
found in 004 on the copy were fixed in the file (see below) and
regression-tested (`tests/test_migration_004_005_preflight.py`).

## Step 0 — fresh backup FIRST (do not skip, do not reuse the old one)

The only backup on file (`smartclass-backup-2026-11-22.dump`, 407K)
predates migrations 001–003 and cannot restore the current database.
004 Step 9 drops the `*_legacy` integer columns — destructive and
irreversible without a current backup. Take a fresh backup
(Supabase Database > Backups, or `pg_dump` as before 001) and confirm
the file exists and verifies before continuing.

Pre-checks (optional but cheap):
- `select count(*) from students where pin_hash is null or pin_hash = '';`
  — must be 0 (002 already applied live; confirm it is still 0).
- Confirm 001, 002 and 003 are all applied — 004 assumes their UUID
  PKs; 005 additionally assumes 004's `face_embeddings` /
  `voice_embeddings`.

## Step 1 — run 004

Paste the ENTIRE `004_phase1_pgvector.sql` into a new SQL Editor
query and Run. Do not run it from the app — the REST API cannot run
SQL. It aborts the whole transaction by design (do not force past
it) if pgvector is < 0.8.0, or if any UUID PK is still NULL before
the legacy-column drops.

Verify 004 (queries also at the bottom of the file):
- `select extversion from pg_extension where extname = 'vector';`
  — expect >= 0.8.0
- `select count(*) from face_embeddings;` — 0 (new table)
- `select count(*) from voice_embeddings;` — 0
- `select count(*) from inference_jobs;` — 0
- `select * from enrollments limit 5;` — same rows as `subject_students`
- `select * from v_session_counts;` — one row per subject with sessions
- `select * from v_attendance_percentages limit 5;`
- `select column_name from information_schema.columns where table_name in
  ('students','teachers','subjects','subject_students','attendance_logs')
  and column_name like '%_legacy';` — **0 rows**

Migration 001 initially stamps pre-existing enrollments with migration
time. Run `migrations/006_backfill_legacy_enrollment_dates.sql` after 005
to move those dates back to each student's first recorded session, so
historical sessions appear in their attendance totals. Enrollments with
no attendance logs keep the original timestamp.

## Step 2 — run 005 (only after 004 verifies)

Paste the ENTIRE `005_phase3_privacy.sql` into a new SQL Editor
query and Run. **Do not run 005 before 004.**

Verify 005 (queries also at the bottom of the file):
- `select count(*) from consent_records;` — 0 rows, no error
- `select count(*) from parental_consents;` — 0 rows, no error
- `select column_name from information_schema.columns
  where table_name = 'students' and column_name = 'date_of_birth';`
  — one row
- `select proname from pg_proc where proname = 'delete_subject_tx';`
  — one row

## What the preflight fixed in 004 (already in the file)

1. `subjects.teacher_id_legacy` was never dropped — Step 9 missed it,
   so 004's own verification query returned 1 row instead of 0.
2. `match_faces()` was declared STABLE but runs
   `SET LOCAL hnsw.iterative_scan` — Postgres rejects SET in a
   non-volatile function, so the global / >500-roster paths failed.
   Changed to VOLATILE. (The global path is the registration
   duplicate-face check, so this was live-blocking.)
3. The version guard used a lexicographic text compare
   (`v_version < '0.8.0'` would wrongly reject a future 0.10.0).
   It now compares `string_to_array(...)::int[]`.

No defects were found in 005.

## Preflight fidelity gaps (read before running live)

- Preflight ran on Postgres **16.15**; live Supabase is Postgres 17.
- `auth.uid()` was a NULL-returning stub on the copy — only the anon
  deny path was tested (0 rows, no 42P17 recursion), not a real
  signed-in teacher/student.
- The copy starts from the pre-001 backup, so live drift since
  001–003 is unseen.
- The >500-roster HNSW path was not executed (roster is 8 students).

If a live run fails: report the Postgres error code and the step
that produced it, stop, and fix the file — do not retry the same
file live.
