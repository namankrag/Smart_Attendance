-- Allow teachers to see attendance names and USNs without granting direct
-- SELECT access to the students table, which also contains biometric fields.
begin;

create or replace function public.get_teacher_session_details(
  p_subject_id uuid,
  p_timestamp timestamptz
)
returns table (
  id bigint,
  session_id uuid,
  student_id uuid,
  subject_id uuid,
  "timestamp" timestamptz,
  is_present boolean,
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

  return query
    select a.id,
           a.session_id,
           a.student_id,
           a.subject_id,
           a.timestamp,
           a.is_present,
           jsonb_build_object(
             'student_id', s.student_id,
             'usn', s.usn,
             'name', s.name
           )
      from public.attendance_logs a
      join public.students s on s.student_id = a.student_id
     where a.subject_id = p_subject_id
       and a.timestamp = p_timestamp
     order by s.usn, a.student_id;
end;
$$;

revoke all on function public.get_teacher_session_details(uuid, timestamptz)
  from public, anon;
grant execute on function public.get_teacher_session_details(uuid, timestamptz)
  to authenticated;

commit;
