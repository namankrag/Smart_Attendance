-- ============================================================================
-- Smart Attendance / SmartClass — Phase 0 migration
-- 001_phase0_core.sql
--
-- DO NOT APPLY BLINDLY. Run in the Supabase SQL editor against a COPY of
-- the production database first, verify row counts, then apply to live.
-- Live data verified 2026-11-22 via anon PostgREST reads (no writes):
-- 8 students (ids 5-12, all pin_hash NULL, single 128-d face_embedding),
-- 2 subjects (MPW/MINI PROJECT, bm56), 1 teacher (namankrag, bcrypt
-- $2b$12$...), 38 attendance_logs, subject_students has NO id column
-- (only subject_id, student_id). Migration preserves all of it: UUIDs
-- are backfilled, legacy int IDs kept as *_legacy columns for one release.
-- Live migration is NOT applied in this PR (REST cannot run SQL).
--
-- What this does (Phase 0, audit 1-54):
--   * UUID primary keys (replacing guessable integer IDs), USN as a separate
--     unique institutional key, preserving existing rows via a mapping.
--   * Mandatory PIN: students.pin_hash NOT NULL enforcement is applied in
--     has set a PIN, otherwise it fails loudly, by design (fail closed).
--   * Separate join_code on subjects (sections can share subject_code).
--   * attendance_sessions table (called `sessions` in the spec) +
--     UNIQUE (session_id, student_id) on attendance_logs
--     for idempotent upserts.
--   * login_attempts table for DB-backed sliding-window rate limiting +
--     exponential lockout (OWASP Authentication Cheat Sheet:
--     https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html).
--   * audit_log (append-only) for template / attendance access.
--   * Row Level Security (RLS) driven by Supabase Auth: auth.uid()
--     https://supabase.com/docs/guides/database/postgres/row-level-security
--   * All timestamps timestamptz (UTC); render in the user's time zone in UI.
--
-- Python 3.11 / Postgres (Supabase). Requires pgcrypto.
-- ============================================================================

begin;

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- Step 1: UUID columns + USN + auth linkage (additive, safe to run first)
-- ---------------------------------------------------------------------------
alter table students add column if not exists id uuid;
alter table students add column if not exists usn text;
alter table students add column if not exists auth_user_id uuid unique;

alter table teachers add column if not exists id uuid;
alter table teachers add column if not exists auth_user_id uuid unique;

alter table subjects add column if not exists id uuid;
alter table subjects add column if not exists join_code text;
alter table subjects add column if not exists teacher_uuid uuid;

alter table subject_students add column if not exists student_uuid uuid;
alter table subject_students add column if not exists subject_uuid uuid;
alter table subject_students add column if not exists enrolled_at timestamptz not null default now();

alter table attendance_logs add column if not exists student_uuid uuid;
alter table attendance_logs add column if not exists subject_uuid uuid;
alter table attendance_logs add column if not exists session_id uuid;
alter table attendance_logs add column if not exists status text not null default 'present';
alter table attendance_logs add column if not exists method text;
alter table attendance_logs add column if not exists confidence double precision;
alter table attendance_logs add column if not exists marked_by uuid;
alter table attendance_logs add column if not exists updated_at timestamptz not null default now();

-- Backfill UUIDs for existing rows (stable within this transaction).
update students set id = gen_random_uuid() where id is null;
update teachers set id = gen_random_uuid() where id is null;
update subjects set id = gen_random_uuid() where id is null;

-- USN backfill: use the legacy integer student_id as a provisional USN only
-- where no USN exists, so no row is lost. Operators MUST replace provisional
-- USNs (format 'LEGACY-<id>') with real institutional USNs before enrolment.
update students set usn = 'LEGACY-' || student_id::text where usn is null;

-- Join code: separate from subject_code, URL-safe, unguessable.
-- (OWASP: guessable join codes, audit 32.)
update subjects set join_code = encode(gen_random_bytes(9), 'base64')
  where join_code is null;
-- Normalise to URL-safe alphabet.
update subjects set join_code = translate(join_code, '+/=', '---')
  where join_code ~ '[+/=]';

-- Map legacy integer FKs to UUIDs.
update subject_students ss
  set student_uuid = s.id from students s where ss.student_id = s.student_id;
update subject_students ss
  set subject_uuid = sub.id from subjects sub where ss.subject_id = sub.subject_id;
update attendance_logs al
  set student_uuid = s.id from students s where al.student_id = s.student_id;
update attendance_logs al
  set subject_uuid = sub.id from subjects sub where al.subject_id = sub.subject_id;
update subjects sub
  set teacher_uuid = t.id from teachers t where sub.teacher_id = t.teacher_id;

-- ---------------------------------------------------------------------------
-- Step 2: sessions table (Phase 0 item 10)
-- A session is one teacher-started attendance run (face or voice), not a
-- distinct timestamp. Face and voice runs for the same class must share a
-- session_id, otherwise they count twice (audit 28).
-- ---------------------------------------------------------------------------
-- FIX 2026-11-22 (error 42830 on live run): do NOT add inline REFERENCES
-- here. At this point subjects.id / teachers.id are plain UUID columns
-- with no unique constraint yet (their PKs are created in Step 6), so
-- Postgres rejects "references subjects(id)" with 42830: there is no
-- unique constraint matching given keys for referenced table "subjects".
-- The FKs are added in Step 6, after the PKs exist, as
-- fk_session_subject / fk_session_teacher.
create table if not exists attendance_sessions (
  session_id uuid primary key default gen_random_uuid(),
  subject_id uuid not null,
  teacher_id uuid not null,
  method text not null check (method in ('face','voice','manual','pin')),
  started_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);
create index if not exists idx_attendance_sessions_subject_started
  on attendance_sessions (subject_id, started_at desc);

-- Backfill one session per legacy (subject_id, timestamp) group, so existing
-- logs are not lost and are not double-counted.
insert into attendance_sessions (subject_id, teacher_id, method, started_at)
select distinct on (al.subject_uuid, al.timestamp)
  al.subject_uuid, sub.teacher_uuid, 'face', al.timestamp
from attendance_logs al
join subjects sub on sub.id = al.subject_uuid
where al.session_id is null and al.subject_uuid is not null
on conflict do nothing;

update attendance_logs al
  set session_id = s.session_id
  from attendance_sessions s
  where s.subject_id = al.subject_uuid
    and s.started_at = al.timestamp
    and al.session_id is null;

-- ---------------------------------------------------------------------------
-- Step 3: login_attempts — DB-backed rate limiting (Phase 0 item 4)
-- Sliding window + exponential lockout are enforced in Python
-- (src/database/rate_limit.py / db.py) by querying this table; the table
-- itself is the shared state so Streamlit's multiple instances agree.
-- ---------------------------------------------------------------------------
create table if not exists login_attempts (
  id uuid primary key default gen_random_uuid(),
  identifier text not null,          -- student USN/UUID or teacher username
  kind text not null check (kind in ('pin','face','teacher')),
  success boolean not null default false,
  attempted_at timestamptz not null default now()
);
create index if not exists idx_login_attempts_identifier_time
  on login_attempts (identifier, kind, attempted_at desc);

-- ---------------------------------------------------------------------------
-- Step 4: audit_log — append-only (Phase 0 item 8, Phase 3 item 2)
-- ---------------------------------------------------------------------------
create table if not exists audit_log (
  id uuid primary key default gen_random_uuid(),
  actor_id uuid,
  action text not null,
  table_name text,
  record_id uuid,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists idx_audit_log_actor_time
  on audit_log (actor_id, created_at desc);
revoke update, delete on audit_log from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- Step 5: PIN guard — STAGED, see 002_phase0_pin_enforcement.sql
-- LIVE DATA: all 8 students currently have pin_hash NULL, so a NOT NULL
-- constraint here would abort this entire transaction. 001 therefore
-- does NOT enforce pin_hash NOT NULL; 002 does, after PINs are set.
-- The application already fails closed for PIN-less accounts
-- (get_student_for_login + verify_credential return False with no hash).

alter table students add constraint students_usn_unique unique (usn);
alter table subjects add constraint subjects_join_code_unique unique (join_code);

-- Idempotent attendance: one row per (session, student).
alter table attendance_logs
  add constraint attendance_logs_session_student_unique
  unique (session_id, student_id);

-- ---------------------------------------------------------------------------
-- Step 6: Swap integer PKs for UUIDs (preserving data via the mapping above)
-- This is the destructive step. It runs in the same transaction, so a
-- failure rolls everything back. Verify FKs in a copy first.
-- NOTE: legacy integer columns are kept as *_legacy for one release so
-- old clients / exports can still be reconciled, then dropped in Phase 1.
--
-- FIX 2026-11-22 (error 42P16 on live run): "multiple primary keys for
-- table students are not allowed". The live tables already have PKs
-- (from the backup dump: students_pkey on student_id,
-- teachers_pkey on teacher_id, subjects_pkey on subject_id,
-- subject_students_pkey on (subject_id, student_id)).
-- Renaming student_id -> student_id_legacy carries that PK with it, so
-- adding a second PK on the new UUID student_id fails. The same
-- applies to teachers/subjects, and to the FKs that reference those
-- PKs (attendance_logs_student_id_fkey, attendance_logs_subject_id_fkey,
-- subject_students_student_id_fkey, subject_students_subject_id_fkey,
-- subjects_teacher_id_fkey). Drop the old FKs and PKs FIRST.
-- Also, renaming student_uuid -> student_id would fail with
-- "column student_id already exists" unless the original integer
-- student_id is renamed to *_legacy first, in every FK table.
-- Order below is therefore: drop FKs, drop PKs, rename legacy
-- columns to *_legacy, rename UUID columns to canonical names,
-- then add the new PKs and FKs.
alter table attendance_logs drop constraint if exists attendance_logs_student_id_fkey;
alter table attendance_logs drop constraint if exists attendance_logs_subject_id_fkey;
alter table subject_students drop constraint if exists subject_students_student_id_fkey;
alter table subject_students drop constraint if exists subject_students_subject_id_fkey;
alter table subjects drop constraint if exists subjects_teacher_id_fkey;

alter table students drop constraint if exists students_pkey;
alter table teachers drop constraint if exists teachers_pkey;
alter table subjects drop constraint if exists subjects_pkey;
alter table subject_students drop constraint if exists subject_students_pkey;

-- The Step 5 unique on (session_id, student_id) was created on the
-- integer student_id. Drop it now and re-add it after the rename,
-- otherwise it would follow the rename to student_id_legacy.
alter table attendance_logs drop constraint if exists attendance_logs_session_student_unique;

-- Rename legacy integer FK columns first.
alter table subject_students rename column student_id to student_id_legacy;
alter table subject_students rename column subject_id to subject_id_legacy;
alter table attendance_logs rename column student_id to student_id_legacy;
alter table attendance_logs rename column subject_id to subject_id_legacy;
alter table subjects rename column teacher_id to teacher_id_legacy;

alter table students rename column student_id to student_id_legacy;
alter table students rename column id to student_id;
alter table students alter column student_id set not null;
alter table students add primary key (student_id);

alter table teachers rename column teacher_id to teacher_id_legacy;
alter table teachers rename column id to teacher_id;
alter table teachers alter column teacher_id set not null;
alter table teachers add primary key (teacher_id);

alter table subjects rename column subject_id to subject_id_legacy;
alter table subjects rename column id to subject_id;
alter table subjects alter column subject_id set not null;
alter table subjects add primary key (subject_id);

-- Point FK columns at the new UUID PKs (now safe: the legacy names are free).
alter table subject_students rename column student_uuid to student_id;
alter table subject_students rename column subject_uuid to subject_id;
alter table attendance_logs rename column student_uuid to student_id;
alter table attendance_logs rename column subject_uuid to subject_id;
alter table subjects rename column teacher_uuid to teacher_id;

alter table attendance_logs
  add constraint attendance_logs_session_student_unique
  unique (session_id, student_id);

alter table subject_students
  add constraint fk_enroll_student foreign key (student_id) references students(student_id) on delete cascade,
  add constraint fk_enroll_subject foreign key (subject_id) references subjects(subject_id) on delete cascade;
alter table attendance_logs
  add constraint fk_log_student foreign key (student_id) references students(student_id) on delete cascade,
  add constraint fk_log_subject foreign key (subject_id) references subjects(subject_id) on delete cascade,
  add constraint fk_log_session foreign key (session_id) references attendance_sessions(session_id) on delete cascade;
alter table subjects
  add constraint fk_subject_teacher foreign key (teacher_id) references teachers(teacher_id) on delete cascade;
alter table attendance_sessions
  add constraint fk_session_subject foreign key (subject_id) references subjects(subject_id) on delete cascade,
  add constraint fk_session_teacher foreign key (teacher_id) references teachers(teacher_id) on delete cascade;

-- Enrolment uniqueness (prevents duplicate enrolments, audit 7).
alter table subject_students
  add constraint subject_students_student_subject_unique unique (student_id, subject_id);

create index if not exists idx_attendance_logs_session on attendance_logs (session_id);
create index if not exists idx_attendance_logs_student on attendance_logs (student_id, subject_id);
create index if not exists idx_students_usn on students (usn);
create index if not exists idx_subjects_join_code on subjects (join_code);

-- ---------------------------------------------------------------------------
-- Step 7: Row Level Security (Phase 0 item 8)
-- Supabase Auth: auth.uid() is the authenticated user's UUID, linked via
-- teachers.auth_user_id / students.auth_user_id.
-- The service_role key bypasses RLS and must stay server-side in the future
-- ML worker only — never in Streamlit code.
--
-- FIX 2026-11-22 (live error 42P17 infinite recursion): policies must NOT
-- directly reference other RLS-enabled tables in their USING clause.
-- Example: subjects_student_enrolled referenced subject_students, whose
-- enrollments_teacher policy referenced subjects again, so Postgres
-- detected infinite recursion and every read on subjects /
-- attendance_logs failed with 42P17. The fix, per Supabase RLS guidance
-- (https://supabase.com/docs/guides/database/postgres/row-level-security),
-- is SECURITY DEFINER helper functions: they run as the table owner
-- and bypass RLS for the inner check, so the policy itself only calls
-- a function, it does not trigger another policy.
alter table students enable row level security;
alter table teachers enable row level security;
alter table subjects enable row level security;
alter table subject_students enable row level security;
alter table attendance_logs enable row level security;
alter table attendance_sessions enable row level security;
alter table login_attempts enable row level security;
alter table audit_log enable row level security;

-- Helper functions (SECURITY DEFINER, bypass RLS for the inner check).
create or replace function public.teacher_owns_subject(p_subject_id uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from subjects s
    join teachers t on t.teacher_id = s.teacher_id
    where s.subject_id = p_subject_id and t.auth_user_id = auth.uid()
  );
$$;
create or replace function public.student_enrolled_in_subject(p_subject_id uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from subject_students ss
    join students s on s.student_id = ss.student_id
    where ss.subject_id = p_subject_id and s.auth_user_id = auth.uid()
  );
$$;
create or replace function public.student_is_self(p_student_id uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from students s
    where s.student_id = p_student_id and s.auth_user_id = auth.uid()
  );
$$;
create or replace function public.teacher_owns_session(p_session_id uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from attendance_sessions s
    join teachers t on t.teacher_id = s.teacher_id
    where s.session_id = p_session_id and t.auth_user_id = auth.uid()
  );
$$;

-- Students: a student can read/update only their own row.
drop policy if exists students_self on students;
create policy students_self on students
  for all using (auth.uid() = auth_user_id) with check (auth.uid() = auth_user_id);

-- Teachers: a teacher can read/update only their own row.
drop policy if exists teachers_self on teachers;
create policy teachers_self on teachers
  for all using (auth.uid() = auth_user_id) with check (auth.uid() = auth_user_id);

-- Subjects: teachers manage their own subjects; students read subjects
-- they are enrolled in.
drop policy if exists subjects_teacher_own on subjects;
create policy subjects_teacher_own on subjects
  for all using (public.teacher_owns_subject(subjects.subject_id));
drop policy if exists subjects_student_enrolled on subjects;
create policy subjects_student_enrolled on subjects
  for select using (public.student_enrolled_in_subject(subjects.subject_id));

-- Enrolments: teacher of the subject, or the student themselves.
drop policy if exists enrollments_teacher on subject_students;
create policy enrollments_teacher on subject_students
  for all using (public.teacher_owns_subject(subject_students.subject_id));
drop policy if exists enrollments_student on subject_students;
create policy enrollments_student on subject_students
  for select using (public.student_is_self(subject_students.student_id));

-- Attendance logs & sessions: teacher of the subject, or the student the
-- row is about.
drop policy if exists attendance_teacher on attendance_logs;
create policy attendance_teacher on attendance_logs
  for all using (public.teacher_owns_subject(attendance_logs.subject_id));
drop policy if exists attendance_student on attendance_logs;
create policy attendance_student on attendance_logs
  for select using (public.student_is_self(attendance_logs.student_id));

drop policy if exists sessions_teacher on attendance_sessions;
create policy sessions_teacher on attendance_sessions
  for all using (public.teacher_owns_subject(attendance_sessions.subject_id));
drop policy if exists sessions_student on attendance_sessions;
create policy sessions_student on attendance_sessions
  for select using (public.student_enrolled_in_subject(attendance_sessions.subject_id));

-- login_attempts / audit_log: no direct client access; only via server-side
-- functions / service_role in the worker. Deny by default (no permissive
-- policy = deny under RLS).

commit;

-- Verification queries (run after commit, compare row counts to pre-migration):
--   select count(*) from students;  select count(*) from subjects;
--   select count(*) from attendance_sessions;  select count(*) from attendance_logs;
--   select count(*) from students where pin_hash is null;
--   select count(*) from subjects where join_code is null;
