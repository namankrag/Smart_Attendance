-- ============================================================================
-- Smart Attendance / SmartClass — Phase 3 migration
-- 005_phase3_privacy.sql
--
-- HOW TO RUN (Supabase SQL Editor — do NOT run from the app; the REST API
-- cannot run SQL, and this file is LOCAL-ONLY until Naman applies it):
--   1. BACK UP FIRST (pg_dump / Database > Backups).
--   2. Open the Supabase dashboard for project
--      tomhefyrrwjdyaddlidg > SQL Editor > New query.
--   3. Paste this ENTIRE file and click Run. It runs in ONE transaction
--      (`begin; ... commit;`): any error rolls everything back.
--   4. Do NOT run this before migrations 001 + 002 + 003 + 004 have all
--      been applied (it depends on students/teachers/subjects UUID PKs,
--      audit_log, face_embeddings / voice_embeddings, and the 003
--      SECURITY DEFINER RLS helpers).
--
-- What this does (Phase 3, SPEC.md PHASE 3 items 1-3):
--   * consent_records — one row per consent grant/withdrawal, with the
--     privacy-notice version shown (DPDP Act Sec. 6(1) consent;
--     Sec. 6(4) withdrawal; Sec. 6(10) burden of proof on the
--     fiduciary — hence the timestamp + notice version on every row).
--   * parental_consents — verifiable parental / lawful-guardian consent
--     for students under 18 (DPDP Act Sec. 9(1); child = under 18,
--     Sec. 2(3)). `students.date_of_birth` is added so the app can
--     decide under-18 status; it is NULL for existing rows (unknown
--     age FAILS CLOSED in the app — treated as under 18).
--   * delete_subject_tx(p_subject_id, p_teacher_id) — the transactional
--     subject delete (SPEC Phase 3 item 4 / audit 51): the old
--     three-sequential-deletes path in the app could partially fail
--     and leave orphans. This SECURITY DEFINER function verifies
--     ownership (teacher's auth_user_id) and deletes logs, sessions,
--     enrolments and the subject in ONE transaction — all or nothing.
--     The app calls it via supabase.rpc("delete_subject_tx", ...).
--   * RLS on the new tables, reusing the 001/003 SECURITY DEFINER
--     helpers (student_is_self, teacher_teaches_student) — policies
--     call functions, never other RLS tables directly (003, live
--     error 42P17: infinite recursion).
--
-- What this does NOT do (documented honestly, Phase 3 item 3):
--   * Encryption at rest of pgvector templates is a Supabase platform setting
--     (Supabase encrypts Postgres data at rest; see docs/privacy/dpia.md).
--     No app-level column encryption is built here, and none is claimed:
--     the templates remain stored as pgvector vectors, protected by RLS +
--     separation from identity data (face_embeddings / voice_embeddings
--     tables hold only student_id + vector + model metadata — no names,
--     USNs or PINs).
--   * No ISO/IEC 24745 cancelable-template mode is built (see
--     docs/privacy/cancelable-templates.md — future/optional).
--   * No raw photos or audio are stored by this migration or by the
--     app: uploads are processed in memory and deleted after
--     inference (see worker/stores.py, worker/runner.py).
--
-- References (verified 2026-11-22):
--   DPDP Act 2023 official text:
--     https://www.indiacode.nic.in/bitstream/123456789/22037/2/a2023-22.pdf
--   Supabase RLS:
--     https://supabase.com/docs/guides/database/postgres/row-level-security
-- ============================================================================

begin;

-- ---------------------------------------------------------------------------
-- Step 1: students.date_of_birth (needed for the under-18 gate).
-- NULL for existing rows: the app treats unknown age as under 18
-- (fail closed) until a DOB is recorded.
-- ---------------------------------------------------------------------------
alter table students add column if not exists date_of_birth date;

-- ---------------------------------------------------------------------------
-- Step 2: consent_records — DPDP Act Sec. 6.
-- One row per grant/withdrawal (append-only history, like audit_log:
-- never UPDATE/DELETE — a withdrawal is a new row with granted=false,
-- so the full consent history is preserved and the fiduciary can
-- prove what was consented to, when, and under which notice version).
-- ---------------------------------------------------------------------------
create table if not exists consent_records (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students(student_id) on delete cascade,
  purpose text not null check (purpose in ('biometric_attendance', 'voice_attendance')),
  notice_version text not null,
  granted boolean not null,
  granted_at timestamptz not null default now(),
  granted_by text
);
create index if not exists idx_consent_records_student_purpose
  on consent_records (student_id, purpose, granted_at desc);
revoke update, delete on consent_records from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- Step 3: parental_consents — DPDP Act Sec. 9(1).
-- Verifiable parental consent: guardian name + verification method +
-- the teacher who verified it, with a timestamp. Only 'in_person'
-- verification exists today (guardian shows ID to the teacher); the
-- CHECK constraint keeps any future method honest — a new method must
-- be added here deliberately, not smuggled in by the app.
-- ---------------------------------------------------------------------------
create table if not exists parental_consents (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students(student_id) on delete cascade,
  guardian_name text not null,
  guardian_contact text,
  verification_method text not null default 'in_person'
    check (verification_method in ('in_person')),
  verified_by_teacher_id uuid not null references teachers(teacher_id),
  verified_at timestamptz not null default now()
);
create index if not exists idx_parental_consents_student
  on parental_consents (student_id, verified_at desc);

-- ---------------------------------------------------------------------------
-- Step 4: RLS on the new tables.
-- Students manage their own consent rows; teachers may read consent
-- rows of students they teach (needed to check the Sec. 9(1) gate
-- before enrolling a minor). No permissive policy: anon sees nothing.
-- ---------------------------------------------------------------------------
alter table consent_records enable row level security;
alter table parental_consents enable row level security;

drop policy if exists consent_records_self on consent_records;
create policy consent_records_self on consent_records
  for all using (public.student_is_self(consent_records.student_id));
drop policy if exists consent_records_teacher on consent_records;
create policy consent_records_teacher on consent_records
  for select using (public.teacher_teaches_student(consent_records.student_id));

drop policy if exists parental_consents_self on parental_consents;
create policy parental_consents_self on parental_consents
  for select using (public.student_is_self(parental_consents.student_id));
drop policy if exists parental_consents_teacher on parental_consents;
create policy parental_consents_teacher on parental_consents
  for all using (public.teacher_teaches_student(parental_consents.student_id));

-- ---------------------------------------------------------------------------
-- Step 5: delete_subject_tx — transactional subject delete (audit 51).
-- SECURITY DEFINER so the function can delete across the four tables
-- under RLS in one transaction; ownership is checked INSIDE the
-- function against the calling teacher's auth.uid() (via the teachers
-- row), so a caller can never delete another teacher's subject.
-- Returns the counts deleted, so the caller can confirm all-or-nothing.
-- ---------------------------------------------------------------------------
create or replace function public.delete_subject_tx(
  p_subject_id uuid, p_teacher_id uuid)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_owner uuid;
  v_logs int := 0;
  v_sessions int := 0;
  v_enrolments int := 0;
begin
  -- Ownership: the subject must belong to this teacher (checked by
  -- teacher_id AND by the teacher row's auth_user_id, so a forged
  -- teacher_id alone is not enough).
  select s.teacher_id into v_owner
    from subjects s
    join teachers t on t.teacher_id = s.teacher_id
   where s.subject_id = p_subject_id
     and t.auth_user_id = auth.uid();
  if v_owner is null or v_owner <> p_teacher_id then
    raise exception 'subject does not exist or does not belong to this teacher'
      using errcode = '42501';
  end if;

  -- All deletes run in this function's single transaction: any error
  -- rolls back every delete above it (all-or-nothing). Dependency
  -- order: logs -> sessions -> enrolments -> subject.
  delete from attendance_logs where subject_id = p_subject_id;
  get diagnostics v_logs = row_count;
  delete from attendance_sessions where subject_id = p_subject_id;
  get diagnostics v_sessions = row_count;
  delete from subject_students where subject_id = p_subject_id;
  get diagnostics v_enrolments = row_count;
  delete from subjects where subject_id = p_subject_id;
  if not found then
    raise exception 'subject % vanished during delete', p_subject_id;
  end if;

  return jsonb_build_object(
    'subject_id', p_subject_id,
    'attendance_logs_deleted', v_logs,
    'attendance_sessions_deleted', v_sessions,
    'enrolments_deleted', v_enrolments
  );
end;
$$;

commit;

-- ---------------------------------------------------------------------------
-- Verify (run after applying; expected: tables exist, function exists):
--   select count(*) from consent_records;            -- 0 rows, no error
--   select count(*) from parental_consents;          -- 0 rows, no error
--   select column_name from information_schema.columns
--     where table_name = 'students' and column_name = 'date_of_birth';
--   select proname from pg_proc where proname = 'delete_subject_tx';
-- ---------------------------------------------------------------------------
