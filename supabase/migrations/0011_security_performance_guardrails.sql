-- Security/performance guardrails for public RAG traffic.
-- 1) distributed authenticated-user rate limiting
-- 2) bounded/masked audit events and automatic retention
-- 3) index-friendly year filtering and inline representative citations

create table if not exists api_rate_limits (
  user_id uuid not null,
  action text not null check (char_length(action) between 1 and 64),
  window_started timestamptz not null,
  request_count int not null default 1 check (request_count > 0),
  primary key (user_id, action, window_started)
);

alter table api_rate_limits enable row level security;
-- No direct policies: authenticated callers can only use the bounded RPC below.

create or replace function consume_api_rate_limit(
  action_text text,
  max_requests int default 30,
  window_seconds int default 60
) returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  uid uuid := auth.uid();
  safe_action text := left(regexp_replace(coalesce(action_text, ''), '[^a-zA-Z0-9_:-]', '', 'g'), 64);
  safe_max int := greatest(1, least(coalesce(max_requests, 30), 300));
  safe_window int := greatest(10, least(coalesce(window_seconds, 60), 3600));
  bucket timestamptz;
  accepted int;
begin
  if uid is null then
    raise exception 'authentication required';
  end if;
  if safe_action = '' then
    raise exception 'invalid rate-limit action';
  end if;

  bucket := to_timestamp(
    floor(extract(epoch from clock_timestamp()) / safe_window) * safe_window
  );

  insert into api_rate_limits(user_id, action, window_started, request_count)
  values (uid, safe_action, bucket, 1)
  on conflict (user_id, action, window_started)
  do update set request_count = api_rate_limits.request_count + 1
  where api_rate_limits.request_count < safe_max
  returning request_count into accepted;

  return accepted is not null;
end;
$$;

revoke all on function consume_api_rate_limit(text, int, int) from public;
grant execute on function consume_api_rate_limit(text, int, int) to authenticated;

-- Audit queries can themselves contain personal data. Mask common high-risk
-- patterns, cap payload size, cap document count, and reject ids the caller
-- cannot currently access even though this function is SECURITY DEFINER.
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
  uid uuid := auth.uid();
  doc_id uuid;
  inserted_count int := 0;
  safe_action text;
  safe_query text;
begin
  if uid is null then
    raise exception 'authentication required';
  end if;

  safe_action := case
    when action_text in ('search','chat','insights','studio','studio_summary','hermes','reports')
      then action_text
    else 'other'
  end;
  safe_query := left(coalesce(query_text, ''), 500);
  safe_query := regexp_replace(safe_query, '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', '[이메일]', 'g');
  safe_query := regexp_replace(safe_query, '\m[0-9]{6}-?[1-4][0-9]{6}\M', '[주민등록번호]', 'g');
  safe_query := regexp_replace(safe_query, '\m01[016789]-?[0-9]{3,4}-?[0-9]{4}\M', '[전화번호]', 'g');

  foreach doc_id in array coalesce(document_ids[1:50], '{}'::uuid[])
  loop
    if exists (
      select 1
      from documents d
      where d.id = doc_id
        and d.status = 'processed'
        and d.security_level = '일반'
        and (
          exists (select 1 from access_roles r where r.user_id = uid and r.role = 'admin')
          or exists (select 1 from access_roles r where r.user_id = uid and r.dept = d.dept)
        )
    ) then
      insert into access_log(
        user_id, document_id, action, query, result_count, latency_ms,
        rerank_provider, rerank_applied
      ) values (
        uid, doc_id, safe_action,
        case when inserted_count = 0 then nullif(safe_query, '') else null end,
        greatest(0, least(coalesce(result_count, 0), 50)),
        greatest(0, least(coalesce(latency_ms, 0), 3600000)),
        left(rerank_provider, 40), coalesce(rerank_applied, false)
      );
      inserted_count := inserted_count + 1;
    end if;
  end loop;

  if inserted_count = 0 then
    insert into access_log(
      user_id, action, query, result_count, latency_ms, rerank_provider, rerank_applied
    ) values (
      uid, safe_action, nullif(safe_query, ''), 0,
      greatest(0, least(coalesce(latency_ms, 0), 3600000)),
      left(rerank_provider, 40), coalesce(rerank_applied, false)
    );
  end if;
end;
$$;

revoke all on function log_search_event(text, text, uuid[], int, int, text, boolean) from public;
grant execute on function log_search_event(text, text, uuid[], int, int, text, boolean) to authenticated;

create index if not exists idx_documents_zip_id on documents(zip_id);
-- idx_documents_processed_dept_doc_date (0008) now becomes usable because the
-- year predicate below is a date range rather than extract(year from doc_date).

-- Return citation metadata in the search RPC so the API does not need two
-- additional document lookups after every search.
drop function if exists hybrid_search(vector, text, int, int, int, text, int);

create function hybrid_search(
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
  dept text,
  zip_id uuid,
  citation_filename text,
  citation_doc_no text,
  citation_doc_date date,
  citation_dept text
)
language sql stable
set search_path = public
as $$
  with bounds as (
    select
      greatest(1, least(coalesce(match_count, 8), 60)) as safe_match_count,
      greatest(1, least(coalesce(pool, 50), 80)) as safe_pool,
      case when filter_year between 2000 and 2100 then make_date(filter_year, 1, 1) end as year_start,
      case when filter_year between 2000 and 2100 then make_date(filter_year + 1, 1, 1) end as year_end
  ),
  vec as (
    select c.id, row_number() over (order by c.embedding <=> query_embedding) as rank
    from doc_chunks c
    join documents d on d.id = c.document_id
    cross join bounds b
    where d.status = 'processed'
      and (filter_dept is null or d.dept = filter_dept)
      and (filter_year is null or (d.doc_date >= b.year_start and d.doc_date < b.year_end))
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
      and (filter_year is null or (d.doc_date >= b.year_start and d.doc_date < b.year_end))
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
         d.filename, d.doc_no, d.doc_date, d.dept, d.zip_id,
         coalesce(rep.filename, d.filename),
         coalesce(rep.doc_no, d.doc_no),
         coalesce(rep.doc_date, d.doc_date),
         coalesce(rep.dept, d.dept)
  from fused f
  join doc_chunks c on c.id = f.id
  join documents d on d.id = c.document_id
  left join lateral (
    select rd.filename, rd.doc_no, rd.doc_date, rd.dept
    from documents rd
    where rd.zip_id = d.zip_id
      and rd.status = 'processed'
      and lower(rd.filename) like '%.pdf'
    order by
      case when rd.doc_no is null then 1 else 0 end,
      case when rd.filename ~ '^\s*(\[?\s*붙임|[0-9]+\.\s)' then 1 else 0 end,
      rd.doc_date nulls last,
      rd.filename
    limit 1
  ) rep on true
  order by f.score desc
  limit (select safe_match_count from bounds);
$$;

-- Best-effort automatic cleanup on Supabase/Postgres installations with pg_cron.
do $$
begin
  begin
    create extension if not exists pg_cron with schema pg_catalog;
  exception when insufficient_privilege or feature_not_supported then
    raise notice 'pg_cron unavailable; configure the documented retention job externally';
  end;

  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    perform cron.unschedule(jobid)
    from cron.job
    where jobname = 'kmuwiki-security-retention';

    perform cron.schedule(
      'kmuwiki-security-retention',
      '17 3 * * *',
      $cron$
        delete from public.access_log where at < now() - interval '180 days';
        delete from public.api_rate_limits where window_started < now() - interval '1 day';
      $cron$
    );
  end if;
exception when others then
  raise notice 'automatic retention schedule was not installed: %', sqlerrm;
end;
$$;
