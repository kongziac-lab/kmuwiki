-- Bound every caller-controlled hybrid-search parameter. The API already has
-- tighter limits, but authenticated users can invoke PostgREST RPC directly.

create or replace function hybrid_search_v2(
  query_embedding vector(1024),
  query_text text,
  match_count int default 8,
  rrf_k int default 50,
  pool int default 80,
  filter_dept text default null,
  filter_year int default null
) returns table (
  document_id uuid,
  search_unit_id uuid,
  asset_id uuid,
  unit_index int,
  chunk_index int,
  modality text,
  asset_type text,
  page_no int,
  bbox real[],
  content text,
  score float,
  filename text,
  doc_no text,
  doc_date date,
  dept text,
  zip_id uuid,
  storage_path text,
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
      greatest(1, least(coalesce(pool, 80), 200)) as safe_pool,
      greatest(1, least(coalesce(rrf_k, 50), 1000)) as safe_rrf_k,
      left(coalesce(query_text, ''), 2000) as safe_query_text,
      case when filter_year between 2000 and 2100 then make_date(filter_year, 1, 1) end as year_start,
      case when filter_year between 2000 and 2100 then make_date(filter_year + 1, 1, 1) end as year_end
  ),
  vec as (
    select su.id, row_number() over (order by su.embedding <=> query_embedding) as rank
    from search_units su
    join documents d on d.id = su.document_id
    cross join bounds b
    where query_embedding is not null
      and d.status = 'processed'
      and d.index_version = 'v2'
      and d.security_level = '일반'
      and (filter_dept is null or d.dept = filter_dept)
      and (filter_year is null or (d.doc_date >= b.year_start and d.doc_date < b.year_end))
    order by su.embedding <=> query_embedding
    limit (select safe_pool from bounds)
  ),
  kw as (
    select su.id,
           row_number() over (
             order by ts_rank(to_tsvector('simple', su.content),
                              plainto_tsquery('simple', b.safe_query_text)) desc
           ) as rank
    from search_units su
    join documents d on d.id = su.document_id
    cross join bounds b
    where d.status = 'processed'
      and d.index_version = 'v2'
      and d.security_level = '일반'
      and (filter_dept is null or d.dept = filter_dept)
      and (filter_year is null or (d.doc_date >= b.year_start and d.doc_date < b.year_end))
      and to_tsvector('simple', su.content)
          @@ plainto_tsquery('simple', b.safe_query_text)
    order by ts_rank(to_tsvector('simple', su.content),
                     plainto_tsquery('simple', b.safe_query_text)) desc
    limit (select safe_pool from bounds)
  ),
  fused as (
    select coalesce(vec.id, kw.id) as id,
           coalesce(1.0 / (b.safe_rrf_k + vec.rank), 0)
         + coalesce(1.0 / (b.safe_rrf_k + kw.rank), 0) as score
    from vec
    full outer join kw on vec.id = kw.id
    cross join bounds b
  )
  select su.document_id, su.id, su.asset_id, su.unit_index,
         su.unit_index as chunk_index, su.modality, su.asset_type, su.page_no,
         su.bbox, su.content, f.score,
         d.filename, d.doc_no, d.doc_date, d.dept, d.zip_id,
         da.storage_path,
         coalesce(rep.filename, d.filename),
         coalesce(rep.doc_no, d.doc_no),
         coalesce(rep.doc_date, d.doc_date),
         coalesce(rep.dept, d.dept)
  from fused f
  join search_units su on su.id = f.id
  join documents d on d.id = su.document_id
  left join document_assets da on da.id = su.asset_id
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

revoke all on function hybrid_search_v2(vector, text, int, int, int, text, int) from public;
grant execute on function hybrid_search_v2(vector, text, int, int, int, text, int) to authenticated;
