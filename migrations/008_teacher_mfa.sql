-- Require an AAL2 Supabase session for teacher profile, roster, attendance,
-- and ML access. Requires migrations 001, 003, 004 and 005; it does not
-- depend on the data repair in 006 or student feature migration 007.
begin;

-- Teachers can no longer read or write their profile using an AAL1 token.
drop policy if exists teachers_require_aal2 on public.teachers;
create policy teachers_require_aal2 on public.teachers
  as restrictive for all to authenticated
  using ((select auth.jwt()->>'aal') = 'aal2')
  with check ((select auth.jwt()->>'aal') = 'aal2');

-- Existing teacher RLS policies and SECURITY DEFINER RPCs share these
-- helpers, so requiring AAL2 here protects both direct table access and RPCs
-- that check teacher ownership through the helper.
create or replace function public.teacher_owns_subject(p_subject_id uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select coalesce((select auth.jwt()->>'aal') = 'aal2', false)
     and exists (
       select 1 from subjects s
       join teachers t on t.teacher_id = s.teacher_id
       where s.subject_id = p_subject_id and t.auth_user_id = auth.uid()
     );
$$;

create or replace function public.teacher_teaches_student(p_student_id uuid)
returns boolean language sql stable security definer set search_path = public as $$
  select coalesce((select auth.jwt()->>'aal') = 'aal2', false)
     and exists (
       select 1
       from subject_students ss
       join subjects s on s.subject_id = ss.subject_id
       join teachers t on t.teacher_id = s.teacher_id
       where ss.student_id = p_student_id and t.auth_user_id = auth.uid()
     );
$$;

-- This SECURITY DEFINER transaction bypasses table RLS, so enforce AAL2
-- inside the function as well as validating ownership.
create or replace function public.delete_subject_tx(
  p_subject_id uuid, p_teacher_id uuid)
returns jsonb language plpgsql security definer set search_path = public as $$
declare
  v_owner uuid;
  v_logs int := 0;
  v_sessions int := 0;
  v_enrolments int := 0;
begin
  if coalesce(auth.jwt()->>'aal', '') <> 'aal2' then
    raise exception 'multi-factor authentication required' using errcode = '42501';
  end if;

  select s.teacher_id into v_owner
    from subjects s
    join teachers t on t.teacher_id = s.teacher_id
   where s.subject_id = p_subject_id
     and t.auth_user_id = auth.uid();
  if v_owner is null or v_owner <> p_teacher_id then
    raise exception 'subject does not exist or does not belong to this teacher'
      using errcode = '42501';
  end if;

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
