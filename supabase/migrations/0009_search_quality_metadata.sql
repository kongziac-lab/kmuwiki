-- Parser, chunking, rerank, and search-quality monitoring fields.

alter table documents
  add column if not exists title text,
  add column if not exists attachment_names text[] not null default '{}',
  add column if not exists document_kind text;

alter table doc_chunks
  add column if not exists section_type text;

alter table access_log
  add column if not exists result_count int,
  add column if not exists latency_ms int,
  add column if not exists rerank_provider text,
  add column if not exists rerank_applied boolean not null default false;

create index if not exists idx_documents_title
  on documents using gin (to_tsvector('simple', coalesce(title, '')));

create index if not exists idx_documents_document_kind
  on documents(document_kind);

create index if not exists idx_doc_chunks_section_type
  on doc_chunks(section_type);

create table if not exists search_quality_reports (
  id uuid primary key default gen_random_uuid(),
  run_label text not null,
  case_count int not null,
  recall_at_5 numeric not null,
  recall_at_10 numeric not null,
  mrr numeric not null,
  passed boolean not null,
  report jsonb not null,
  created_at timestamptz not null default now()
);

alter table search_quality_reports enable row level security;

drop policy if exists search_quality_reports_admin on search_quality_reports;
create policy search_quality_reports_admin on search_quality_reports
  for select to authenticated using (current_user_is_admin());

create or replace function admin_search_monitoring_summary()
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
  select case
    when not current_user_is_admin() then
      raise_admin_required()
    else jsonb_build_object(
      'last_24h', jsonb_build_object(
        'search_count', (select count(*) from access_log where at > now() - interval '24 hours' and action in ('search','chat','reports','insights','hermes')),
        'rerank_count', (select count(*) from access_log where at > now() - interval '24 hours' and rerank_applied),
        'avg_latency_ms', (select coalesce(round(avg(latency_ms)), 0) from access_log where at > now() - interval '24 hours' and latency_ms is not null)
      ),
      'latest_quality_report', (
        select jsonb_build_object(
          'run_label', run_label,
          'case_count', case_count,
          'recall_at_5', recall_at_5,
          'recall_at_10', recall_at_10,
          'mrr', mrr,
          'passed', passed,
          'created_at', created_at
        )
        from search_quality_reports
        order by created_at desc
        limit 1
      )
    )
  end;
$$;

revoke all on function admin_search_monitoring_summary() from public;
grant execute on function admin_search_monitoring_summary() to authenticated;

create or replace function log_search_event(
  action_text text,
  query_text text,
  document_ids uuid[],
  result_count int default null,
  latency_ms int default null,
  rerank_provider text default null,
  rerank_applied boolean default false
) returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  doc_id uuid;
begin
  foreach doc_id in array coalesce(document_ids, '{}')
  loop
    insert into access_log(
      user_id, document_id, action, query, result_count, latency_ms,
      rerank_provider, rerank_applied
    )
    values (
      auth.uid(), doc_id, action_text, query_text, result_count, latency_ms,
      rerank_provider, coalesce(rerank_applied, false)
    );
  end loop;

  if coalesce(array_length(document_ids, 1), 0) = 0 then
    insert into access_log(
      user_id, action, query, result_count, latency_ms, rerank_provider, rerank_applied
    )
    values (
      auth.uid(), action_text, query_text, result_count, latency_ms,
      rerank_provider, coalesce(rerank_applied, false)
    );
  end if;
end;
$$;

revoke all on function log_search_event(text, text, uuid[], int, int, text, boolean) from public;
grant execute on function log_search_event(text, text, uuid[], int, int, text, boolean) to authenticated;
