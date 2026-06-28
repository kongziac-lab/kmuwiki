-- 보안 강화: 함수의 search_path를 고정(미설정 시 search_path 주입 위험, linter 0011).
-- 함수 본문은 0001/0002와 동일하며 set search_path = public 만 추가.

create or replace function match_chunks(
  query_embedding vector(1024),
  match_count int default 8,
  filter_dept text default null
) returns table (
  document_id uuid,
  chunk_index int,
  content text,
  similarity float
)
language sql stable
set search_path = public
as $$
  select c.document_id, c.chunk_index, c.content,
         1 - (c.embedding <=> query_embedding) as similarity
  from doc_chunks c
  join documents d on d.id = c.document_id
  where d.status = 'processed'
    and (filter_dept is null or d.dept = filter_dept)
  order by c.embedding <=> query_embedding
  limit match_count;
$$;

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
set search_path = public
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
