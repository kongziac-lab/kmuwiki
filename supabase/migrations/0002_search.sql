-- KMU Wiki — 하이브리드 검색 (Phase 2)
-- 벡터 유사도(pgvector) + 키워드(FTS)를 RRF(Reciprocal Rank Fusion)로 결합.
-- SECURITY INVOKER(기본)로 두어 호출자(authenticated 유저)의 RLS가 그대로 적용된다
-- → 권한 없는 부서/비공개 문서는 검색 결과에 절대 포함되지 않는다(불변식 5·8).

create or replace function hybrid_search(
  query_embedding vector(1024),
  query_text text,
  match_count int default 8,
  rrf_k int default 50,
  pool int default 50,
  filter_dept text default null
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
as $$
  with vec as (
    select c.id,
           row_number() over (order by c.embedding <=> query_embedding) as rank
    from doc_chunks c
    join documents d on d.id = c.document_id
    where d.status = 'processed'
      and (filter_dept is null or d.dept = filter_dept)
    order by c.embedding <=> query_embedding
    limit pool
  ),
  kw as (
    select c.id,
           row_number() over (
             order by ts_rank(to_tsvector('simple', c.content),
                              plainto_tsquery('simple', query_text)) desc
           ) as rank
    from doc_chunks c
    join documents d on d.id = c.document_id
    where d.status = 'processed'
      and (filter_dept is null or d.dept = filter_dept)
      and to_tsvector('simple', c.content) @@ plainto_tsquery('simple', query_text)
    limit pool
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
  limit match_count;
$$;
