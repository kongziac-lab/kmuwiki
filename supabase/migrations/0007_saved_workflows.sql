-- Saved workflow snapshots created from the business insights page.
create table if not exists saved_workflows (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null default auth.uid(),
  title text not null,
  query text,
  target_year int,
  graph jsonb not null,
  source jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_saved_workflows_owner_created
  on saved_workflows(owner_id, created_at desc);

alter table saved_workflows enable row level security;

grant select, insert, update, delete on saved_workflows to authenticated;

drop policy if exists saved_workflows_select_own on saved_workflows;
create policy saved_workflows_select_own on saved_workflows
  for select to authenticated
  using (owner_id = auth.uid());

drop policy if exists saved_workflows_insert_own on saved_workflows;
create policy saved_workflows_insert_own on saved_workflows
  for insert to authenticated
  with check (owner_id = auth.uid());

drop policy if exists saved_workflows_update_own on saved_workflows;
create policy saved_workflows_update_own on saved_workflows
  for update to authenticated
  using (owner_id = auth.uid())
  with check (owner_id = auth.uid());

drop policy if exists saved_workflows_delete_own on saved_workflows;
create policy saved_workflows_delete_own on saved_workflows
  for delete to authenticated
  using (owner_id = auth.uid());
