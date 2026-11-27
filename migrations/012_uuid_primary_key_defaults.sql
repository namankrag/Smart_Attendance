-- Restore database-generated UUIDs for profiles and subjects.
-- Migration 001 backfills UUID values for existing rows but leaves the
-- renamed primary-key columns without defaults, so new inserts fail when
-- the application omits those IDs.
begin;

alter table public.students
  alter column student_id set default gen_random_uuid();

alter table public.teachers
  alter column teacher_id set default gen_random_uuid();

alter table public.subjects
  alter column subject_id set default gen_random_uuid();

commit;
