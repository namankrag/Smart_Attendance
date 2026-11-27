-- Remove legacy/default anon grants left on the SECURITY DEFINER enrollment
-- and teacher roster functions. Authenticated users still pass the function's
-- auth.uid() and ownership checks; service_role remains available to the server.

begin;

revoke all on function public.enroll_student_by_join_code(text) from anon;
revoke all on function public.unenroll_student_self(uuid) from anon;
revoke all on function public.get_teacher_subject_roster(uuid, integer, integer)
  from anon;
revoke all on function public.enroll_student_by_usn(uuid, text) from anon;

grant execute on function public.enroll_student_by_join_code(text) to authenticated;
grant execute on function public.unenroll_student_self(uuid) to authenticated;
grant execute on function public.get_teacher_subject_roster(uuid, integer, integer)
  to authenticated;
grant execute on function public.enroll_student_by_usn(uuid, text) to authenticated;

commit;
