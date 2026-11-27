-- Smart Attendance — authenticated student enrollment and scoped teacher roster.
-- Run after migrations 001, 003 and 004. Student self-service functions derive
-- student_id from auth.uid(); teacher functions verify subject ownership.

begin;

create or replace function public.enroll_student_by_join_code(p_join_code text)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_student_id uuid;
  v_subject subjects%rowtype;
begin
  if auth.uid() is null then
    raise exception 'authentication required' using errcode = '42501';
  end if;

  select student_id into v_student_id
    from students
   where auth_user_id = auth.uid();
  if v_student_id is null then
    raise exception 'student profile not found' using errcode = '42501';
  end if;

  select * into v_subject
    from subjects
   where join_code = trim(p_join_code);
  if not found then
    raise exception 'join code not found' using errcode = 'P0002';
  end if;

  insert into subject_students (student_id, subject_id)
  values (v_student_id, v_subject.subject_id)
  on conflict (student_id, subject_id) do nothing;

  return jsonb_build_object(
    'subject_id', v_subject.subject_id,
    'subject_code', v_subject.subject_code,
    'name', v_subject.name,
    'section', v_subject.section,
    'teacher_id', v_subject.teacher_id
  );
end;
$$;

create or replace function public.unenroll_student_self(p_subject_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_student_id uuid;
  v_deleted integer;
begin
  if auth.uid() is null then
    raise exception 'authentication required' using errcode = '42501';
  end if;

  select student_id into v_student_id
    from students
   where auth_user_id = auth.uid();
  if v_student_id is null then
    raise exception 'student profile not found' using errcode = '42501';
  end if;

  delete from subject_students
   where student_id = v_student_id and subject_id = p_subject_id;
  get diagnostics v_deleted = row_count;

  return jsonb_build_object('success', true, 'enrollment_deleted', v_deleted);
end;
$$;

-- The face matcher needs one template at a time. Students may read their own
-- profile; a teacher needs AAL2 and an active enrollment in a subject they own.
create or replace function public.get_authorized_student_profile(p_student_id uuid)
returns jsonb
language plpgsql
stable
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_student jsonb;
begin
  if auth.uid() is null
     or not public.student_is_self(p_student_id)
        and (
          coalesce(auth.jwt()->>'aal', '') <> 'aal2'
          or not public.teacher_teaches_student(p_student_id)
        ) then
    raise exception 'not authorized for this student' using errcode = '42501';
  end if;

  select jsonb_build_object(
      'student_id', s.student_id,
      'usn', s.usn,
      'name', s.name,
      'face_embedding', s.face_embedding,
      'voice_embedding', s.voice_embedding
    )
    into v_student
    from public.students s
   where s.student_id = p_student_id;
  return v_student;
end;
$$;

-- Teacher roster is metadata only; biometric templates stay server-side.
create or replace function public.get_teacher_subject_roster(
  p_subject_id uuid, p_limit integer, p_offset integer
)
returns table (
  student_id uuid,
  subject_id uuid,
  enrolled_at timestamptz,
  students jsonb
)
language plpgsql
stable
security definer
set search_path = pg_catalog, public, pg_temp
as $$
begin
  if auth.uid() is null
     or coalesce(auth.jwt()->>'aal', '') <> 'aal2'
     or not public.teacher_owns_subject(p_subject_id) then
    raise exception 'not authorized for this subject' using errcode = '42501';
  end if;
  if p_limit < 1 or p_limit > 1000 or p_offset < 0 then
    raise exception 'invalid pagination' using errcode = '22023';
  end if;

  return query
    select ss.student_id,
           ss.subject_id,
           ss.enrolled_at,
           jsonb_build_object(
             'student_id', s.student_id,
             'usn', s.usn,
             'name', s.name
           )
      from public.subject_students ss
      join public.students s on s.student_id = ss.student_id
     where ss.subject_id = p_subject_id
     order by s.usn, ss.student_id
     limit p_limit offset p_offset;
end;
$$;

create or replace function public.enroll_student_by_usn(
  p_subject_id uuid, p_usn text
)
returns jsonb
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
declare
  v_student_id uuid;
begin
  if auth.uid() is null or not public.teacher_owns_subject(p_subject_id) then
    raise exception 'not authorized for this subject' using errcode = '42501';
  end if;

  select s.student_id into v_student_id
    from public.students s
   where upper(s.usn) = upper(trim(p_usn));
  if v_student_id is null then
    raise exception 'student not found' using errcode = 'P0002';
  end if;

  insert into public.subject_students (student_id, subject_id)
  values (v_student_id, p_subject_id)
  on conflict (student_id, subject_id) do nothing;

  return jsonb_build_object('student_id', v_student_id, 'subject_id', p_subject_id);
end;
$$;

revoke all on function public.enroll_student_by_join_code(text) from public;
revoke all on function public.unenroll_student_self(uuid) from public;
revoke all on function public.get_authorized_student_profile(uuid) from public;
revoke all on function public.get_teacher_subject_roster(uuid, integer, integer) from public;
revoke all on function public.enroll_student_by_usn(uuid, text) from public;
grant execute on function public.enroll_student_by_join_code(text) to authenticated;
grant execute on function public.unenroll_student_self(uuid) to authenticated;
grant execute on function public.get_authorized_student_profile(uuid) to authenticated;
grant execute on function public.get_teacher_subject_roster(uuid, integer, integer)
  to authenticated;
grant execute on function public.enroll_student_by_usn(uuid, text) to authenticated;

-- match_faces is SECURITY DEFINER and returns student IDs. Keep direct RPC
-- access private; the FastAPI internal adapter validates the user and subject
-- before calling it with the worker's service role.
revoke all on function public.match_faces(uuid, vector, integer)
  from public, anon, authenticated;
grant execute on function public.match_faces(uuid, vector, integer) to service_role;

commit;
