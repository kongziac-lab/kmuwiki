-- 리랭크 후보 풀 확대 (검색 정확도 P1-b)
-- hybrid_search 의 match_count 클램프를 20 → 60 으로 올린다. 리랭커가 넓은 후보에서
-- 상위 k를 재정렬할 수 있게 하려는 목적이다. 사용자-facing 결과 수(k)는 여전히
-- 서비스단 _bounded_k(KMU_API_MAX_K, 기본 20)로 제한되므로 남용 위험은 그대로 막힌다.
-- pool 클램프(80)와 나머지(RRF·filter_year·RLS INVOKER)는 0008 과 동일하다.

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
      greatest(1, least(coalesce(match_count, 8), 60)) as safe_match_count,
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

-- 0002 시절의 6-인자 오버로드는 사용되지 않는다(리트리버는 filter_year 포함 7-인자 호출).
-- 함께 남아 있으면 함수명 모호성을 유발하므로 정리한다.
drop function if exists hybrid_search(vector, text, int, int, int, text);
