-- ============================================================================
-- Smart Attendance — Phase 0 migration 002: PIN enforcement (STAGED)
-- Run ONLY after every active student has set a 4-6 digit PIN (Argon2id
-- hash in students.pin_hash). LIVE CHECK 2026-11-22: all 8 live students
-- have pin_hash NULL, so running this now would (correctly) abort.
-- Steps to prepare: for each active student, run the app's PIN-set /
-- re-enrolment flow, or deactivate the account. Then run this file in
-- the Supabase SQL editor and verify the count query returns 0 first:
--   select count(*) from students where pin_hash is null or pin_hash = '';
-- OWASP Password Storage Cheat Sheet:
-- https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html
-- ============================================================================
begin;
do $$
begin
  if exists (select 1 from students where pin_hash is null or pin_hash = '') then
    raise exception 'Phase 0 PIN guard: % student(s) have no pin_hash. Set a PIN for every active student (or deactivate the account) before applying the NOT NULL constraint.',
      (select count(*) from students where pin_hash is null or pin_hash = '');
  end if;
end $$;
alter table students alter column pin_hash set not null;
commit;
-- Verification: select count(*) from students where pin_hash is null; -- must be 0
