-- Operational guardrails for local ingest + Vercel web/API operation.
-- Adds bounded search filters, audit retention cleanup, and storage/index health.

create index if not exists idx_documents_processed_dept_doc_date
  on documents(dept, doc_date)
  where status = 'processed';

create index if not exists idx_doc_chunks_document_id
  on doc_chunks(document_id);

create index if not exists idx_access_log_user_at
  on access_log(user_id, at desc);

create or replace function hybrid_search(
  query_embedding vector(1024),
  query_text text,
  match_count int default 8,
  rrf_k int default 50,
  pool int default 50,
  filter_dept text default null,
  filter_year int default null
) returns table (
  document_id uuid,
  chunk_index int,
  content text,
  score float,
  filename text,
  doc_no text,
  doc_date date,
  dept text
)
language sql stable
set search_path = public
as $$
  with bounds as (
    select
      greatest(1, least(coalesce(match_count, 8), 20)) as safe_match_count,
      greatest(1, least(coalesce(pool, 50), 80)) as safe_pool
  ),
  vec as (
    select c.id,
           row_number() over (order by c.embedding <=> query_embedding) as rank
    from doc_chunks c
    join documents d on d.id = c.document_id
    cross join bounds b
    where d.status = 'processed'
      and (filter_dept is null or d.dept = filter_dept)
      and (filter_year is null or extract(year from d.doc_date)::int = filter_year)
    order by c.embedding <=> query_embedding
    limit (select safe_pool from bounds)
  ),
  kw as (
    select c.id,
           row_number() over (
             order by ts_rank(to_tsvector('simple', c.content),
                              plainto_tsquery('simple', query_text)) desc
           ) as rank
    from doc_chunks c
    join documents d on d.id = c.document_id
    cross join bounds b
    where d.status = 'processed'
      and (filter_dept is null or d.dept = filter_dept)
      and (filter_year is null or extract(year from d.doc_date)::int = filter_year)
      and to_tsvector('simple', c.content) @@ plainto_tsquery('simple', query_text)
    limit (select safe_pool from bounds)
  ),
  fused as (
    select coalesce(vec.id, kw.id) as id,
           coalesce(1.0 / (rrf_k + vec.rank), 0)
         + coalesce(1.0 / (rrf_k + kw.rank), 0) as score
    from vec
    full outer join kw on vec.id = kw.id
  )
  select c.document_id, c.chunk_index, c.content, f.score,
         d.filename, d.doc_no, d.doc_date, d.dept
  from fused f
  join doc_chunks c on c.id = f.id
  join documents d on d.id = c.document_id
  order by f.score desc
  limit (select safe_match_count from bounds);
$$;

create or replace function cleanup_access_log(retention_days int default 180)
returns int
language plpgsql
security definer
set search_path = public
as $$
declare
  deleted_count int;
begin
  perform require_current_user_admin();

  delete from access_log
  where at < now() - make_interval(days => greatest(30, coalesce(retention_days, 180)));

  get diagnostics deleted_count = row_count;
  return deleted_count;
end;
$$;

create or replace function admin_storage_health()
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
      'database_bytes', pg_database_size(current_database()),
      'tables', jsonb_build_object(
        'zip_archives_bytes', pg_total_relation_size('zip_archives'),
        'documents_bytes', pg_total_relation_size('documents'),
        'doc_chunks_bytes', pg_total_relation_size('doc_chunks'),
        'access_log_bytes', pg_total_relation_size('access_log')
      ),
      'counts', jsonb_build_object(
        'zip_archives', (select count(*) from zip_archives),
        'documents', (select count(*) from documents),
        'doc_chunks', (select count(*) from doc_chunks),
        'access_log', (select count(*) from access_log)
      ),
      'indexes', jsonb_build_object(
        'pgvector_hnsw', to_regclass('public.idx_doc_chunks_embedding') is not null,
        'content_fts', to_regclass('public.idx_doc_chunks_content_fts') is not null,
        'processed_dept_doc_date', to_regclass('public.idx_documents_processed_dept_doc_date') is not null
      ),
      'latest_imported_at', (select max(imported_at) from zip_archives),
      'latest_processed_at', (select max(processed_at) from documents),
      'generated_at', now()
    )
  end;
$$;

revoke all on function cleanup_access_log(int) from public;
revoke all on function admin_storage_health() from public;

grant execute on function cleanup_access_log(int) to authenticated;
grant execute on function admin_storage_health() to authenticated;
