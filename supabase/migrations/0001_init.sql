-- KMU Wiki — 초기 스키마 (확정본)
-- 마스터 플랜 §2 기본 스키마 + §7.I 보강(버전/격리/모델핀/감사로그)을 통합.
-- 임베딩 차원은 1024로 고정(불변식 3·6). 모델 교체는 전체 재임베딩 마이그레이션으로만.

create extension if not exists vector;
create extension if not exists pgcrypto;   -- gen_random_uuid

-- ─────────────────────────────────────────────────────────────
-- 상태 enum (불변식 2·4·7·8 반영)
--   pending           : 신규, 미처리
--   processing        : 처리 중
--   processed         : 파싱·마스킹·임베딩 완료 → 검색 노출
--   pending_password  : 비밀번호 잠김 (1차에서 본문 미오픈, 2차 백필 대상)
--   pending_ocr       : 스캔본, GPU OCR 대기 (2차 백필 대상)
--   quarantine        : 이그레스 게이트 차단(PII 잔존 의심) → 전송 안 함(§7.A)
--   failed            : 파싱/처리 오류 → 재시도 큐
--   superseded        : 신버전으로 대체됨 → 검색 기본 제외(§7.E)
--   revoked           : 회수된 문서(§7.E)
-- ─────────────────────────────────────────────────────────────
do $$ begin
  create type doc_status as enum (
    'pending','processing','processed','pending_password','pending_ocr',
    'quarantine','failed','superseded','revoked'
  );
exception when duplicate_object then null; end $$;

-- 원천 ZIP 추적
create table if not exists zip_archives (
  id            uuid primary key default gen_random_uuid(),
  filename      text not null,
  sha256        text not null unique,          -- ZIP 자체 해시(중복 적재 방지)
  imported_at   timestamptz not null default now(),
  file_count    int
);

-- 문서(파일) 단위
create table if not exists documents (
  id            uuid primary key default gen_random_uuid(),
  zip_id        uuid references zip_archives(id) on delete set null,
  path_in_zip   text not null,
  filename      text not null,
  sha256        text not null unique,           -- 멱등성 키(불변식 4)
  mime_type     text,
  is_encrypted  boolean not null default false,
  status        doc_status not null default 'pending',
  -- 권한·분류 메타 (§7.B deny-by-default: 미상이면 일반 검색 제외)
  dept            text,
  security_level  text,                          -- 일반|대외비 등(§7.B). null이면 관리자 전용 취급
  task_category   text,                          -- 업무별 구분(Phase 4에서 채움)
  -- 버전·회수 (§7.E)
  doc_no          text,                          -- 전자결재 문서번호
  version         int not null default 1,
  superseded_by   uuid references documents(id) on delete set null,
  doc_date        date,
  author          text,
  -- 운영
  error           text,                          -- failed 사유
  created_at    timestamptz not null default now(),
  processed_at  timestamptz
);

create index if not exists idx_documents_status   on documents(status);
create index if not exists idx_documents_dept      on documents(dept);
create index if not exists idx_documents_doc_no    on documents(doc_no);
create index if not exists idx_documents_doc_date  on documents(doc_date);

-- 청크 + 임베딩 (마스킹된 본문만 저장; 불변식 1·7)
create table if not exists doc_chunks (
  id            uuid primary key default gen_random_uuid(),
  document_id   uuid not null references documents(id) on delete cascade,
  chunk_index   int not null,
  content       text not null,                   -- ⚠️ 반드시 마스킹된 텍스트
  embedding     vector(1024),                    -- 차원 고정(불변식 3)
  token_count   int,
  -- 모델 핀(불변식 6 / §7.D): 같은 차원이라도 다른 모델 섞지 않도록 추적
  embed_model   text,
  embed_version text,
  created_at    timestamptz not null default now(),
  unique (document_id, chunk_index)
);

-- 코사인 유사도 HNSW 인덱스
create index if not exists idx_doc_chunks_embedding
  on doc_chunks using hnsw (embedding vector_cosine_ops);

-- 전문검색(키워드) — 하이브리드 검색용(Phase 2)
create index if not exists idx_doc_chunks_content_fts
  on doc_chunks using gin (to_tsvector('simple', content));

-- 권한 매핑(직급/부서 → 접근 범위) (§7.B)
create table if not exists access_roles (
  user_id   uuid not null,                       -- Supabase auth.users
  dept      text,
  role      text not null default 'staff',       -- admin|manager|staff
  primary key (user_id, dept)
);

-- 감사 로그(개인정보보호법 대응) (§7.F)
create table if not exists access_log (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid,
  document_id uuid references documents(id) on delete set null,
  action      text not null,                     -- search|view|export 등
  query       text,
  at          timestamptz not null default now()
);
create index if not exists idx_access_log_at on access_log(at);

-- ─────────────────────────────────────────────────────────────
-- 벡터 유사도 검색 RPC (Phase 2). 권한 필터는 RLS + filter_dept 병행.
-- 검색 대상은 'processed'만; superseded/revoked/quarantine 등은 제외(불변식 8).
-- ─────────────────────────────────────────────────────────────
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

-- ─────────────────────────────────────────────────────────────
-- RLS (불변식 5 / §7.B). 인제스트 워커는 service_role로 우회.
-- 클라이언트(anon/authenticated)는 아래 정책으로만 접근.
-- 정책: 본인 부서 문서 + 일반(security_level='일반')만 노출. 미상(null)은 비노출.
-- 관리자(role=admin)는 전체 접근.
-- ─────────────────────────────────────────────────────────────
alter table documents  enable row level security;
alter table doc_chunks enable row level security;

drop policy if exists documents_select on documents;
create policy documents_select on documents
  for select to authenticated
  using (
    status = 'processed'
    and security_level = '일반'
    and (
      exists (select 1 from access_roles r
              where r.user_id = auth.uid() and r.role = 'admin')
      or exists (select 1 from access_roles r
                 where r.user_id = auth.uid() and r.dept = documents.dept)
    )
  );

drop policy if exists doc_chunks_select on doc_chunks;
create policy doc_chunks_select on doc_chunks
  for select to authenticated
  using (
    exists (
      select 1 from documents d
      where d.id = doc_chunks.document_id
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

-- 나머지 public 테이블도 RLS 활성(미설정 시 PostgREST로 anon 노출됨).
-- service_role(인제스트/서비스)은 RLS를 우회하므로 적재·로깅에는 영향 없음.
alter table zip_archives enable row level security;
alter table access_roles enable row level security;
alter table access_log   enable row level security;

-- zip_archives: 클라이언트 정책 없음 → 접근 불가(service_role 전용)

-- 사용자는 본인 역할만 조회 가능
drop policy if exists access_roles_self on access_roles;
create policy access_roles_self on access_roles
  for select to authenticated using (user_id = auth.uid());

-- 감사 로그는 관리자만 조회(쓰기는 service_role)
drop policy if exists access_log_admin on access_log;
create policy access_log_admin on access_log
  for select to authenticated using (
    exists (select 1 from access_roles r
            where r.user_id = auth.uid() and r.role = 'admin')
  );
