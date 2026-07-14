-- KMU Wiki multimodal search index v2.
--
-- The existing documents/zip_archives tables remain the authority for identity,
-- lifecycle, department, and security level.  v2 only replaces the derived
-- search index.  doc_chunks is intentionally retained during the cut-over so a
-- deployment can roll back without rebuilding the old index first.

alter table documents
  add column if not exists index_version text not null default 'v1',
  add column if not exists visual_status text not null default 'pending',
  add column if not exists indexed_at timestamptz;

create index if not exists idx_documents_index_version
  on documents(index_version, status);

-- A document asset is a physical or structured part of the source: rendered
-- page, image, table, chart, worksheet, etc.  Only masked text and redacted
-- derivative images may be stored here; raw source bytes remain on the NAS.
create table if not exists document_assets (
  id                 uuid primary key default gen_random_uuid(),
  document_id        uuid not null references documents(id) on delete cascade,
  asset_index        int not null check (asset_index >= 0),
  asset_type         text not null check (asset_type in (
                       'page','image','table','chart','figure','worksheet','slide','attachment'
                     )),
  page_no            int check (page_no is null or page_no >= 1),
  bbox               real[] check (bbox is null or cardinality(bbox) = 4),
  text_content       text not null default '', -- masked OCR/extracted text only
  structured_content text not null default '', -- masked Markdown/JSON only
  caption            text not null default '', -- masked caption only
  storage_path       text unique,               -- private redacted derivative only
  media_type         text,
  media_sha256       text,
  width              int check (width is null or width > 0),
  height             int check (height is null or height > 0),
  status             text not null check (status in (
                       'ready','metadata_only','pending_review','pending_ocr','blocked','failed'
                     )),
  redaction_applied  boolean not null default false,
  extraction_model   text,
  extraction_version text,
  error              text,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique(document_id, asset_index)
);

-- A search unit is the common retrieval representation for a text chunk or a
-- visual/structured asset.  Embed v4 maps all modalities into one 1024d space.
create table if not exists search_units (
  id                 uuid primary key default gen_random_uuid(),
  document_id        uuid not null references documents(id) on delete cascade,
  asset_id           uuid references document_assets(id) on delete cascade,
  unit_index         int not null check (unit_index >= 0),
  modality           text not null check (modality in ('text','image','mixed','table')),
  asset_type         text,
  page_no            int check (page_no is null or page_no >= 1),
  bbox               real[] check (bbox is null or cardinality(bbox) = 4),
  content            text not null, -- masked text/YAML surrogate used by FTS and Rerank
  embedding          vector(1024) not null,
  token_count        int,
  embed_model        text not null,
  embed_version      text not null,
  extraction_version text,
  created_at         timestamptz not null default now(),
  unique(document_id, unit_index)
);

create index if not exists idx_document_assets_document_id
  on document_assets(document_id);
create index if not exists idx_document_assets_page
  on document_assets(document_id, page_no);
create index if not exists idx_document_assets_status
  on document_assets(status);
create index if not exists idx_search_units_document_id
  on search_units(document_id);
create index if not exists idx_search_units_asset_id
  on search_units(asset_id);
create index if not exists idx_search_units_modality
  on search_units(modality, asset_type);
create index if not exists idx_search_units_content_fts
  on search_units using gin (to_tsvector('simple', content));
create index if not exists idx_search_units_embedding
  on search_units using hnsw (embedding vector_cosine_ops);

-- The same deny-by-default document policy protects every derived v2 row.
alter table document_assets enable row level security;
alter table search_units enable row level security;

drop policy if exists document_assets_select on document_assets;
create policy document_assets_select on document_assets
  for select to authenticated
  using (
    exists (
      select 1
      from documents d
      where d.id = document_assets.document_id
        and d.status = 'processed'
        and d.security_level = '일반'
        and (
          exists (select 1 from access_roles r
                  where r.user_id = auth.uid() and r.role = 'admin')
          or exists (select 1 from access_roles r
                     where r.user_id = auth.uid() and r.dept = d.dept)
        )
    )
  );

drop policy if exists search_units_select on search_units;
create policy search_units_select on search_units
  for select to authenticated
  using (
    exists (
      select 1
      from documents d
      where d.id = search_units.document_id
        and d.status = 'processed'
        and d.security_level = '일반'
        and (
          exists (select 1 from access_roles r
                  where r.user_id = auth.uid() and r.role = 'admin')
          or exists (select 1 from access_roles r
                     where r.user_id = auth.uid() and r.dept = d.dept)
        )
    )
  );

-- Redacted visual derivatives live in a private bucket.  There are no client
-- write policies; only the service-role ingest worker can upload or replace.
insert into storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
values (
  'kmuwiki-assets', 'kmuwiki-assets', false, 10485760,
  array['image/png','image/jpeg','image/webp']
)
on conflict (id) do update set
  public = false,
  file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists kmuwiki_assets_select on storage.objects;
create policy kmuwiki_assets_select on storage.objects
  for select to authenticated
  using (
    bucket_id = 'kmuwiki-assets'
    and exists (
      select 1
      from document_assets a
      join documents d on d.id = a.document_id
      where a.storage_path = storage.objects.name
        and d.status = 'processed'
        and d.security_level = '일반'
        and (
          exists (select 1 from access_roles r
                  where r.user_id = auth.uid() and r.role = 'admin')
          or exists (select 1 from access_roles r
                     where r.user_id = auth.uid() and r.dept = d.dept)
        )
    )
  );

-- Atomically replace one document's derived index.  The RPC is deliberately
-- unavailable to authenticated/anon callers; the worker invokes it with the
-- service-role key after all masking, visual redaction, and embedding succeed.
drop function if exists replace_document_index_v2(uuid, jsonb, jsonb, text);
create or replace function replace_document_index_v2(
  target_document_id uuid,
  asset_rows jsonb,
  unit_rows jsonb,
  target_visual_status text default 'ready',
  legacy_rows jsonb default '[]'::jsonb
) returns void
language plpgsql
set search_path = public
as $$
declare
  a jsonb;
  u jsonb;
  l jsonb;
begin
  if target_document_id is null then
    raise exception 'target_document_id is required';
  end if;
  if jsonb_typeof(coalesce(asset_rows, '[]'::jsonb)) <> 'array'
     or jsonb_typeof(coalesce(unit_rows, '[]'::jsonb)) <> 'array'
     or jsonb_typeof(coalesce(legacy_rows, '[]'::jsonb)) <> 'array' then
    raise exception 'asset_rows, unit_rows, and legacy_rows must be arrays';
  end if;

  -- Units without an asset do not cascade, so remove them first.
  delete from search_units where document_id = target_document_id;
  delete from document_assets where document_id = target_document_id;

  for a in select value from jsonb_array_elements(coalesce(asset_rows, '[]'::jsonb))
  loop
    insert into document_assets(
      document_id, asset_index, asset_type, page_no, bbox,
      text_content, structured_content, caption,
      storage_path, media_type, media_sha256, width, height, status,
      redaction_applied, extraction_model, extraction_version, error
    ) values (
      target_document_id,
      (a->>'asset_index')::int,
      a->>'asset_type',
      nullif(a->>'page_no', '')::int,
      case when jsonb_typeof(a->'bbox') = 'array'
           then array(select value::real from jsonb_array_elements_text(a->'bbox'))
           else null end,
      coalesce(a->>'text_content', ''),
      coalesce(a->>'structured_content', ''),
      coalesce(a->>'caption', ''),
      nullif(a->>'storage_path', ''),
      nullif(a->>'media_type', ''),
      nullif(a->>'media_sha256', ''),
      nullif(a->>'width', '')::int,
      nullif(a->>'height', '')::int,
      a->>'status',
      coalesce((a->>'redaction_applied')::boolean, false),
      nullif(a->>'extraction_model', ''),
      nullif(a->>'extraction_version', ''),
      nullif(a->>'error', '')
    );
  end loop;

  -- During cut-over, keep the rollback index on the exact same Embed v4 model.
  -- Empty legacy_rows deliberately preserves the old index when dual-write is disabled.
  if jsonb_array_length(coalesce(legacy_rows, '[]'::jsonb)) > 0 then
    delete from doc_chunks where document_id = target_document_id;
    for l in select value from jsonb_array_elements(legacy_rows)
    loop
      insert into doc_chunks(
        document_id, chunk_index, content, embedding, token_count,
        embed_model, embed_version, section_type
      ) values (
        target_document_id,
        (l->>'chunk_index')::int,
        l->>'content',
        ((l->'embedding')::text)::vector(1024),
        nullif(l->>'token_count', '')::int,
        l->>'embed_model',
        l->>'embed_version',
        nullif(l->>'section_type', '')
      );
    end loop;
  end if;

  for u in select value from jsonb_array_elements(coalesce(unit_rows, '[]'::jsonb))
  loop
    insert into search_units(
      document_id, asset_id, unit_index, modality, asset_type, page_no, bbox,
      content, embedding, token_count, embed_model, embed_version,
      extraction_version
    ) values (
      target_document_id,
      case when u ? 'asset_index' and nullif(u->>'asset_index', '') is not null
           then (select da.id from document_assets da
                 where da.document_id = target_document_id
                   and da.asset_index = (u->>'asset_index')::int)
           else null end,
      (u->>'unit_index')::int,
      u->>'modality',
      nullif(u->>'asset_type', ''),
      nullif(u->>'page_no', '')::int,
      case when jsonb_typeof(u->'bbox') = 'array'
           then array(select value::real from jsonb_array_elements_text(u->'bbox'))
           else null end,
      u->>'content',
      ((u->'embedding')::text)::vector(1024),
      nullif(u->>'token_count', '')::int,
      u->>'embed_model',
      u->>'embed_version',
      nullif(u->>'extraction_version', '')
    );
  end loop;

  update documents
  set status = 'processed',
      index_version = 'v2',
      visual_status = case
        when target_visual_status in ('ready','partial','pending_review','pending_ocr','disabled','blocked')
          then target_visual_status
        else 'blocked'
      end,
      indexed_at = now(),
      processed_at = now(),
      error = null
  where id = target_document_id;

  if not found then
    raise exception 'document not found: %', target_document_id;
  end if;
end;
$$;

revoke all on function replace_document_index_v2(uuid, jsonb, jsonb, text, jsonb) from public;
revoke all on function replace_document_index_v2(uuid, jsonb, jsonb, text, jsonb) from anon;
revoke all on function replace_document_index_v2(uuid, jsonb, jsonb, text, jsonb) from authenticated;
grant execute on function replace_document_index_v2(uuid, jsonb, jsonb, text, jsonb) to service_role;

-- Multimodal hybrid retrieval: one vector ranking across text/image/mixed units,
-- plus keyword ranking over their masked textual surrogate, fused with RRF.
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
      case when filter_year between 2000 and 2100 then make_date(filter_year, 1, 1) end as year_start,
      case when filter_year between 2000 and 2100 then make_date(filter_year + 1, 1, 1) end as year_end
  ),
  vec as (
    select su.id, row_number() over (order by su.embedding <=> query_embedding) as rank
    from search_units su
    join documents d on d.id = su.document_id
    cross join bounds b
    where d.status = 'processed'
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
                              plainto_tsquery('simple', query_text)) desc
           ) as rank
    from search_units su
    join documents d on d.id = su.document_id
    cross join bounds b
    where d.status = 'processed'
      and d.index_version = 'v2'
      and d.security_level = '일반'
      and (filter_dept is null or d.dept = filter_dept)
      and (filter_year is null or (d.doc_date >= b.year_start and d.doc_date < b.year_end))
      and to_tsvector('simple', su.content) @@ plainto_tsquery('simple', query_text)
    order by ts_rank(to_tsvector('simple', su.content),
                     plainto_tsquery('simple', query_text)) desc
    limit (select safe_pool from bounds)
  ),
  fused as (
    select coalesce(vec.id, kw.id) as id,
           coalesce(1.0 / (rrf_k + vec.rank), 0)
         + coalesce(1.0 / (rrf_k + kw.rank), 0) as score
    from vec
    full outer join kw on vec.id = kw.id
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

create or replace function admin_multimodal_status()
returns jsonb
language plpgsql
stable
security definer
set search_path = public
as $$
begin
  if not current_user_is_admin() then
    raise exception 'admin required';
  end if;
  return jsonb_build_object(
    'documents', jsonb_build_object(
      'v1', (select count(*) from documents where index_version = 'v1'),
      'v2', (select count(*) from documents where index_version = 'v2'),
      'visual_ready', (select count(*) from documents where visual_status = 'ready')
    ),
    'assets', jsonb_build_object(
      'total', (select count(*) from document_assets),
      'ready', (select count(*) from document_assets where status = 'ready'),
      'pending', (select count(*) from document_assets where status in ('pending_review','pending_ocr')),
      'blocked', (select count(*) from document_assets where status in ('blocked','failed'))
    ),
    'search_units', jsonb_build_object(
      'total', (select count(*) from search_units),
      'text', (select count(*) from search_units where modality = 'text'),
      'visual', (select count(*) from search_units where modality in ('image','mixed')),
      'table', (select count(*) from search_units where modality = 'table')
    )
  );
end;
$$;

revoke all on function admin_multimodal_status() from public;
grant execute on function admin_multimodal_status() to authenticated;
