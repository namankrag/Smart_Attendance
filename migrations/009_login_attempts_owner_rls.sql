-- Let the signed-in app use its own rate-limit rows without exposing
-- other users' login identifiers or allowing cross-user lockout writes.
begin;

alter table public.login_attempts
  add column if not exists actor_auth_user_id uuid default auth.uid();

alter table public.login_attempts enable row level security;

drop policy if exists login_attempts_actor_select on public.login_attempts;
create policy login_attempts_actor_select on public.login_attempts
  for select to authenticated
  using ((select auth.uid()) = actor_auth_user_id);

drop policy if exists login_attempts_actor_insert on public.login_attempts;
create policy login_attempts_actor_insert on public.login_attempts
  for insert to authenticated
  with check ((select auth.uid()) = actor_auth_user_id);

revoke all on table public.login_attempts from public, anon;
grant select, insert on table public.login_attempts to authenticated;

create index if not exists idx_login_attempts_actor_identifier_time
  on public.login_attempts
    (actor_auth_user_id, identifier, kind, success, attempted_at desc);

commit;
