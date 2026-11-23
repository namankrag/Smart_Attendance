-- ============================================================================
-- Smart Attendance — Phase 0 migration 003: fix RLS infinite recursion
-- Run ONLY after 001 has been applied live. 001's original Step 7
-- policies directly referenced other RLS-enabled tables, so Postgres
-- returned: ERROR 42P17: infinite recursion detected in policy for
-- relation "subjects" (and attendance_logs) on every read.
-- This file drops those recursive policies and replaces them with
-- SECURITY DEFINER helper functions, which run as the table owner and
-- bypass RLS for the inner check. See the same fix in 001 Step 7.
-- Supabase RLS guidance:
-- https://supabase.com/docs/guides/database/postgres/row-level-security
-- ============================================================================
begin;

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

drop policy if exists subjects_teacher_own on subjects;
create policy subjects_teacher_own on subjects
  for all using (public.teacher_owns_subject(subjects.subject_id));
drop policy if exists subjects_student_enrolled on subjects;
create policy subjects_student_enrolled on subjects
  for select using (public.student_enrolled_in_subject(subjects.subject_id));

drop policy if exists enrollments_teacher on subject_students;
create policy enrollments_teacher on subject_students
  for all using (public.teacher_owns_subject(subject_students.subject_id));
drop policy if exists enrollments_student on subject_students;
create policy enrollments_student on subject_students
  for select using (public.student_is_self(subject_students.student_id));

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

commit;

-- Verification (as anon, via PostgREST, after 003):
--   subjects and attendance_logs should no longer return 500 / 42P17.
--   As anon with no auth.uid(), they should return [] (deny by default),
--   not an error. As a signed-in teacher/student, they should return
--   only that user's rows, once auth_user_id is linked.
