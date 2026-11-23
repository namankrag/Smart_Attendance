-- ============================================================================
-- Smart Attendance / SmartClass — Phase 1 migration
-- 004_phase1_pgvector.sql
--
-- HOW TO RUN (Supabase SQL Editor — do NOT run from the app; the REST API
-- cannot run SQL, and this file is LOCAL-ONLY until Naman applies it):
--   1. BACK UP FIRST. In Supabase: Database > Backups, or from a shell
--      `pg_dump` against the project. The Step 6 legacy-column drops are
--      destructive and cannot be undone without a backup.
--   2. Open the Supabase dashboard for project
--      tomhefyrrwjdyaddlidg > SQL Editor > New query.
--   3. Paste this ENTIRE file and click Run. It runs in ONE transaction
--      (`begin; ... commit;`): any error rolls everything back, so a
--      failed run leaves the database exactly as it was. Re-running the
--      file after a failure is safe (every statement is IF NOT EXISTS /
--      CREATE OR REPLACE / guarded).
--   4. Verify with the queries at the bottom of this file. Expected:
--      pgvector >= 0.8.0, face_embeddings / voice_embeddings /
--      inference_jobs exist, `enrollments` view exists, match_faces()
--      exists, and the *_legacy columns are gone.
--   5. Do NOT run this before migration 001 + 002 + 003 have all been
--      applied (001 creates the UUID PKs, 002 enforces PINs, 003 fixes
--      the RLS recursion). This file assumes those tables/columns exist.
--
-- What this does (Phase 1, SPEC.md PHASE 1 item 1-2):
--   * pgvector >= 0.8.0 (extension + version guard that aborts if older).
--   * face_embeddings(student_id, embedding vector(512), norm_quality,
--     model_version, created_at) and voice_embeddings(student_id,
--     embedding vector(192), model_version, created_at), each with an
--     HNSW cosine index (vector_cosine_ops).
--     - pgvector docs: https://supabase.com/docs/guides/database/extensions/pgvector
--     - HNSW indexes: https://supabase.com/docs/guides/ai/vector-indexes/hnsw-indexes
--     - HNSW paper: https://arxiv.org/abs/1603.09320
--   * match_faces(p_subject_id, p_query, p_k) RPC (SECURITY DEFINER):
--     roster <= 500 -> exact cosine search over the filtered roster
--     (full recall); global duplicate check (p_subject_id NULL) or
--     roster > 500 -> HNSW with
--     `SET LOCAL hnsw.iterative_scan = relaxed_order` so the enrolment
--     filter does not under-retrieve.
--   * subject_students.enrolled_at (added in 001; IF NOT EXISTS here),
--     plus an `enrollments` VIEW over subject_students. The live table
--     is NOT renamed: Phase 0 code reads subject_students, and the view
--     is the spec's `enrollments` name without breaking anything.
--   * inference_jobs(id, type, status, progress, result_json, error,
--     created_at, expires_at) for the Phase 2 worker queue.
--   * audit_log ensured append-only (created if missing; UPDATE/DELETE
--     revoked, as in 001).
--   * SQL views v_session_counts and v_attendance_percentages, plus an
--     attendance_percentage() RPC, so session counts and attendance
--     percentages are computed in SQL, not in Python. Absences count
--     only sessions with started_at >= enrollments.enrolled_at.
--   * RLS on the new tables, reusing the 001/003 SECURITY DEFINER
--     helpers (teacher_owns_subject, student_enrolled_in_subject,
--     student_is_self) plus a new teacher_teaches_student helper.
--     Supabase RLS: https://supabase.com/docs/guides/database/postgres/row-level-security
--   * DROP the legacy integer columns *_legacy (Phase 0 decision: drop
--     integers in Phase 1). Guarded: a DO block aborts the transaction
--     if any UUID primary key is still NULL, and every drop is
--     IF EXISTS, so re-running is safe.
--   * All timestamps timestamptz (UTC); the UI renders them in the
--     user's time zone and parses them with one shared helper
--     (src/database/timeutil.py), which never crashes on bad ISO input.
--
-- Python 3.11 / Postgres (Supabase). Requires pgcrypto (001) + pgvector.
-- ============================================================================

begin;

-- ---------------------------------------------------------------------------
-- Step 1: pgvector extension (>= 0.8.0), with a version guard.
-- pgvector HNSW indexes need >= 0.5.0; 0.8.0 is the Phase 1 floor because
-- `hnsw.iterative_scan = relaxed_order` (used by match_faces below) is
-- only honoured on recent versions. The guard aborts the whole
-- transaction on an older version instead of silently creating a
-- degraded index.
-- https://github.com/pgvector/pgvector
-- ---------------------------------------------------------------------------
create extension if not exists vector;

do $$
declare
  v_version text;
begin
  select extversion into v_version from pg_extension where extname = 'vector';
  if v_version is null then
    raise exception 'pgvector extension is not installed; enable it in Database > Extensions first';
  end if;
  -- Numeric compare: a lexicographic text compare would wrongly
  -- reject pgvector 0.10.0 ('1' < '8'), so compare dotted-numeric
  -- components as integers instead.
  if string_to_array(v_version, '.')::int[] < array[0, 8, 0] then
    raise exception 'pgvector % is too old; Phase 1 requires >= 0.8.0 (found %)', v_version, v_version;
  end if;
  raise notice 'pgvector % OK', v_version;
end $$;

-- ---------------------------------------------------------------------------
-- Step 2: embedding tables (new in Phase 1).
-- Embeddings are stored NORMALISED (unit L2 norm) by the writer, so
-- cosine distance `<=>` is a true angular distance and
-- similarity = 1 - distance. 512-d face vectors are the Phase 2
-- ArcFace/AdaFace dimensionality (ArcFace https://arxiv.org/abs/1801.07698,
-- AdaFace https://arxiv.org/abs/2204.00964); the legacy 128-d dlib
-- vectors stay in students.face_embedding until Phase 2 migrates them
-- and MUST NOT be inserted here (the vector(512) type rejects them).
-- 192-d voice vectors are the Phase 2 ECAPA-TDNN dimensionality
-- (ECAPA-TDNN https://arxiv.org/abs/2005.07143).
-- norm_quality is the feature-norm quality gate (AdaFace/MagFace style,
-- MagFace https://arxiv.org/abs/2103.06627): low-norm enrolments are
-- rejected / flagged by the writer; NULL means "not measured" (legacy).
-- ---------------------------------------------------------------------------
create table if not exists face_embeddings (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students(student_id) on delete cascade,
  embedding vector(512) not null,
  norm_quality double precision
    check (norm_quality is null or (norm_quality >= 0 and norm_quality <= 1)),
  model_version text not null default 'unspecified',
  created_at timestamptz not null default now()
);
create index if not exists idx_face_embeddings_student
  on face_embeddings (student_id, created_at desc);
-- HNSW cosine index for approximate nearest-neighbour search.
-- vector_cosine_ops + hnsw: https://supabase.com/docs/guides/ai/vector-indexes/hnsw-indexes
create index if not exists idx_face_embeddings_hnsw
  on face_embeddings using hnsw (embedding vector_cosine_ops);

create table if not exists voice_embeddings (
  id uuid primary key default gen_random_uuid(),
  student_id uuid not null references students(student_id) on delete cascade,
  embedding vector(192) not null,
  model_version text not null default 'unspecified',
  created_at timestamptz not null default now()
);
create index if not exists idx_voice_embeddings_student
  on voice_embeddings (student_id, created_at desc);
create index if not exists idx_voice_embeddings_hnsw
  on voice_embeddings using hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- Step 3: enrolments — subject_students IS the enrolments table.
-- enrolled_at was added in 001; IF NOT EXISTS keeps this re-runnable.
-- The spec's `enrollments(enrolled_at)` is exposed as a VIEW over
-- subject_students so Phase 0 code (which reads subject_students)
-- keeps working and new code can use the spec name. security_invoker
-- makes the view respect the caller's RLS instead of the owner's.
-- ---------------------------------------------------------------------------
alter table subject_students
  add column if not exists enrolled_at timestamptz not null default now();

create or replace view public.enrollments
  with (security_invoker = true) as
  select student_id, subject_id, enrolled_at from subject_students;

-- ---------------------------------------------------------------------------
-- Step 4: inference_jobs — async job queue for the Phase 2 ML worker.
-- The worker claims jobs (FOR UPDATE SKIP LOCKED, Phase 2); Streamlit
-- only inserts a row and polls status. expires_at lets a sweeper
-- delete stale results; NULL means "keep until the worker cleans up".
-- ---------------------------------------------------------------------------
create table if not exists inference_jobs (
  id uuid primary key default gen_random_uuid(),
  type text not null check (type in ('face', 'voice')),
  status text not null default 'queued'
    check (status in ('queued', 'running', 'done', 'failed')),
  progress integer not null default 0 check (progress >= 0 and progress <= 100),
  result_json jsonb not null default '{}'::jsonb,
  error text,
  created_by uuid,
  created_at timestamptz not null default now(),
  expires_at timestamptz
);
create index if not exists idx_inference_jobs_status_created
  on inference_jobs (status, created_at desc);

-- ---------------------------------------------------------------------------
-- Step 5: audit_log — append-only (ensure it exists; 001 created it).
-- No UPDATE/DELETE for anyone, including the table owner via the API:
-- revoke keeps the log tamper-evident. Phase 3 logs every template
-- access here.
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
-- Step 6: SQL views / RPC for session counts and attendance percentages.
-- Computed in SQL (SPEC Phase 1 item 3), never by loading rows into
-- Python. Absences count ONLY sessions that started on/after the
-- student's enrolled_at, so a late joiner is not marked absent for
-- classes held before they enrolled (audit 27).
-- ---------------------------------------------------------------------------
create or replace view public.v_session_counts
  with (security_invoker = true) as
  select
    subject_id,
    count(*)::bigint as total_classes,
    min(started_at) as first_session_at,
    max(started_at) as last_session_at
  from attendance_sessions
  group by subject_id;

create or replace view public.v_attendance_percentages
  with (security_invoker = true) as
  select
    ss.student_id,
    ss.subject_id,
    count(distinct s.session_id)::bigint as total_classes,
    count(al.id) filter (where coalesce(al.is_present, false))::bigint as present_classes,
    case
      when count(distinct s.session_id) = 0 then null
      else round(
        100.0 * count(al.id) filter (where coalesce(al.is_present, false))
        / count(distinct s.session_id), 2)
    end as attendance_pct
  from subject_students ss
  left join attendance_sessions s
    on s.subject_id = ss.subject_id
    and s.started_at >= ss.enrolled_at
  left join attendance_logs al
    on al.session_id = s.session_id
    and al.student_id = ss.student_id
  group by ss.student_id, ss.subject_id;

create or replace function public.attendance_percentage(
  p_student_id uuid, p_subject_id uuid
)
returns table(
  student_id uuid,
  subject_id uuid,
  total_classes bigint,
  present_classes bigint,
  attendance_pct numeric
)
language sql stable security definer set search_path = public as $$
  select student_id, subject_id, total_classes, present_classes, attendance_pct
  from public.v_attendance_percentages
  where student_id = p_student_id and subject_id = p_subject_id;
$$;

-- ---------------------------------------------------------------------------
-- Step 7: match_faces RPC — roster-scoped cosine search over pgvector.
--   match_faces(p_subject_id, p_query, p_k)
--   - p_subject_id NULL: GLOBAL duplicate-face check (registration):
--     HNSW approximate search over all stored templates.
--   - roster <= 500: EXACT cosine search over the enrolled roster
--     (full recall — no approximation, no missed matches).
--   - roster > 500: HNSW with `SET LOCAL hnsw.iterative_scan =
--     relaxed_order`, so the enrolment filter does not under-retrieve:
--     without it, HNSW can return fewer than p_k rows when the filter
--     discards most of the approximate candidates.
--     https://supabase.com/docs/guides/ai/vector-indexes/hnsw-indexes
-- Returns cosine SIMILARITY (1 - cosine distance), highest first.
-- SECURITY DEFINER so the function can read face_embeddings under RLS
-- while callers only see the top-k matches for a roster they may see;
-- the function itself never returns a raw embedding.
-- ---------------------------------------------------------------------------
create or replace function public.match_faces(
  p_subject_id uuid,
  p_query vector(512),
  p_k integer default 5
)
returns table(student_id uuid, cosine_similarity double precision)
-- VOLATILE (not STABLE): the global and large-roster paths run
-- `SET LOCAL hnsw.iterative_scan`, and Postgres rejects SET inside a
-- non-volatile function ("SET is not allowed in a non-volatile
-- function"). The function only reads, but VOLATILE is required for
-- the SET LOCAL to run. Preflight 2026-11-22: the STABLE version
-- failed the global path (p_subject_id NULL) with exactly that error.
language plpgsql volatile security definer set search_path = public as $$
declare
  v_roster integer;
begin
  if p_k is null or p_k < 1 then
    p_k := 5;
  end if;
  if p_k > 50 then
    p_k := 50;
  end if;

  if p_subject_id is null then
    -- Global duplicate-face check: HNSW approximate search.
    set local hnsw.iterative_scan = 'relaxed_order';
    return query
      select fe.student_id,
             (1 - (fe.embedding <=> p_query))::double precision
      from face_embeddings fe
      order by fe.embedding <=> p_query
      limit p_k;
  end if;

  select count(*) into v_roster
  from subject_students ss
  where ss.subject_id = p_subject_id;

  if v_roster <= 500 then
    -- Small roster: exact cosine search, full recall.
    return query
      select fe.student_id,
             (1 - (fe.embedding <=> p_query))::double precision
      from face_embeddings fe
      join subject_students ss on ss.student_id = fe.student_id
      where ss.subject_id = p_subject_id
      order by fe.embedding <=> p_query
      limit p_k;
  else
    -- Large roster: HNSW, relaxed iterative scan so the enrolment
    -- filter does not under-retrieve.
    set local hnsw.iterative_scan = 'relaxed_order';
    return query
      select fe.student_id,
             (1 - (fe.embedding <=> p_query))::double precision
      from face_embeddings fe
      join subject_students ss on ss.student_id = fe.student_id
      where ss.subject_id = p_subject_id
      order by fe.embedding <=> p_query
      limit p_k;
  end if;
end;
$$;

-- ---------------------------------------------------------------------------
-- Step 8: RLS on the new tables.
-- Reuses the 001/003 SECURITY DEFINER helpers (same anti-recursion
-- pattern: policies call functions, never other RLS tables directly —
-- see 003_fix_rls_recursion.sql, live error 42P17).
-- New helper: a teacher may read embeddings of students enrolled in
-- any subject they own (needed for classroom attendance matching).
-- ---------------------------------------------------------------------------
create or replace function public.teacher_teaches_student(p_student_id uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1
    from subject_students ss
    join subjects s on s.subject_id = ss.subject_id
    join teachers t on t.teacher_id = s.teacher_id
    where ss.student_id = p_student_id and t.auth_user_id = auth.uid()
  );
$$;

alter table face_embeddings enable row level security;
alter table voice_embeddings enable row level security;
alter table inference_jobs enable row level security;

drop policy if exists face_embeddings_self on face_embeddings;
create policy face_embeddings_self on face_embeddings
  for all using (public.student_is_self(face_embeddings.student_id));
drop policy if exists face_embeddings_teacher on face_embeddings;
create policy face_embeddings_teacher on face_embeddings
  for select using (public.teacher_teaches_student(face_embeddings.student_id));

drop policy if exists voice_embeddings_self on voice_embeddings;
create policy voice_embeddings_self on voice_embeddings
  for all using (public.student_is_self(voice_embeddings.student_id));
drop policy if exists voice_embeddings_teacher on voice_embeddings;
create policy voice_embeddings_teacher on voice_embeddings
  for select using (public.teacher_teaches_student(voice_embeddings.student_id));

-- inference_jobs: only the user who created the job (the worker uses
-- service_role server-side and bypasses RLS). No permissive policy for
-- other users' jobs.
drop policy if exists inference_jobs_owner on inference_jobs;
create policy inference_jobs_owner on inference_jobs
  for all using (created_by = auth.uid()) with check (created_by = auth.uid());

-- ---------------------------------------------------------------------------
-- Step 9: DROP the legacy integer columns (Phase 0 decision).
-- !!! BACK UP FIRST (see header). This is destructive and irreversible
-- without a backup. Guarded two ways:
--   (a) the DO block below aborts the transaction if any UUID primary
--       key is still NULL (i.e. 001's backfill did not complete);
--   (b) every drop is IF EXISTS, so re-running this file is safe.
-- After this step, `student_id` / `teacher_id` / `subject_id` are UUIDs
-- everywhere and the old integer IDs are gone for good.
-- ---------------------------------------------------------------------------
do $$
begin
  if exists (select 1 from students where student_id is null) then
    raise exception 'students.student_id has NULLs; 001 backfill incomplete, aborting legacy drop';
  end if;
  if exists (select 1 from teachers where teacher_id is null) then
    raise exception 'teachers.teacher_id has NULLs; 001 backfill incomplete, aborting legacy drop';
  end if;
  if exists (select 1 from subjects where subject_id is null) then
    raise exception 'subjects.subject_id has NULLs; 001 backfill incomplete, aborting legacy drop';
  end if;
  if exists (select 1 from subject_students where student_id is null or subject_id is null) then
    raise exception 'subject_students has NULL UUID FKs; 001 backfill incomplete, aborting legacy drop';
  end if;
  if exists (select 1 from attendance_logs where student_id is null or subject_id is null) then
    raise exception 'attendance_logs has NULL UUID FKs; 001 backfill incomplete, aborting legacy drop';
  end if;
end $$;

alter table students drop column if exists student_id_legacy;
alter table teachers drop column if exists teacher_id_legacy;
alter table subjects drop column if exists subject_id_legacy;
-- FIX 2026-11-22 (preflight): subjects.teacher_id_legacy was missed.
-- 001 Step 6 renamed subjects.teacher_id (bigint) to teacher_id_legacy
-- before teacher_uuid became teacher_id, so without this drop the
-- file's own verification query (columns like '%_legacy') returns 1 row.
alter table subjects drop column if exists teacher_id_legacy;
alter table subject_students drop column if exists student_id_legacy;
alter table subject_students drop column if exists subject_id_legacy;
alter table attendance_logs drop column if exists student_id_legacy;
alter table attendance_logs drop column if exists subject_id_legacy;

commit;

-- Verification queries (run after commit):
--   select extversion from pg_extension where extname = 'vector';  -- >= 0.8.0
--   select count(*) from face_embeddings;   -- 0 (new table)
--   select count(*) from voice_embeddings;  -- 0 (new table)
--   select count(*) from inference_jobs;    -- 0 (new table)
--   select * from enrollments limit 5;      -- same rows as subject_students
--   select * from v_session_counts;         -- one row per subject with sessions
--   select * from v_attendance_percentages limit 5;
--   select * from match_faces(null, (select embedding from face_embeddings limit 1), 5);
--   select column_name from information_schema.columns
--     where table_name in ('students','teachers','subjects','subject_students','attendance_logs')
--       and column_name like '%_legacy';    -- 0 rows
