-- Repair enrollment dates for rows that existed before 001.
-- 001 added enrolled_at with DEFAULT now(), so legacy enrollments were
-- stamped at migration time and their already-recorded sessions were
-- hidden from student attendance totals. A student's first attendance
-- log proves they were enrolled by that session. Enrollments with no
-- logged session keep their existing date.
begin;

with first_recorded_session as (
  select
    al.student_id,
    al.subject_id,
    min(s.started_at) as first_session_at
  from attendance_logs al
  join attendance_sessions s on s.session_id = al.session_id
  group by al.student_id, al.subject_id
)
update subject_students ss
set enrolled_at = history.first_session_at
from first_recorded_session history
where ss.student_id = history.student_id
  and ss.subject_id = history.subject_id
  and history.first_session_at < ss.enrolled_at;

commit;
