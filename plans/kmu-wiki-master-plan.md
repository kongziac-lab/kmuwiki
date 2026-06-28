# KMU Wiki — 전체 설계 계획서

> 학교 전자결재 문서(ZIP)를 수집·정제·DB화하여 검색·챗봇·업무자동화로 활용하는 시스템
> 작성일: 2026-06-29

---

## 0. 개요

### 0.1 목표
학교 전자결재 시스템에서 내려받은 ZIP 파일들을 한 폴더에 누적하고, 이를 정제·임베딩하여
Supabase(pgvector)에 적재한 뒤 다음 용도로 활용한다.

1. 키워드 조회 / LLM 챗봇 (RAG)
2. 업무흐름도 자동 생성
3. 업무별 연간일정 자동설계 (Google Calendar 연동)
4. 업무별 구분(분류)
5. 보고서 작성 보조
6. Hermes 에이전트를 통한 업무 체계화·업데이트
7. 매년 반복되는 업무의 문서 자동 생성

### 0.2 확정된 설계 결정 (대화에서 합의)
- **기관**: 사립대학. 외부 API 정책 미수립 → 보수적으로 개인정보 비유출 설계.
- **구성**: 하이브리드.
  - **로컬(현재 Mac / 추후 GPU 서버)**: 파싱 · OCR · 개인정보 탐지 · **마스킹**
  - **클라우드**: 임베딩 · 벡터DB(Supabase) · LLM · 검색
- **핵심 불변식**: **마스킹은 항상 "클라우드 전송 직전"에 수행한다.** 단, '무엇을 가릴지'는 마스킹 정책(MaskPolicy)이 정한다.
- **마스킹 정책(내부결재문 기준, 2026-06 결정)**:
  - 🔒 마스킹 유지: **주민등록번호·계좌·카드·여권/면허·이메일** (유출 위험 큰 식별자) → 외부로 안 나감.
  - 👤 보존(PII 비대상): **성명·전화번호·주소** — 직원이 업무상 등장하는 식별 메타데이터(업무흐름도·담당자 조회 활용). 클라우드로 전송될 수 있음.
  - 정책은 `KMU_MASK_LABELS` 토글. 민원·학생 등 **제3자 정보 문서 카테고리는 성명·주소를 다시 켠다**.
  - ⚠️ 잔여 고려(PIPA): 성명·전화는 법적으로 개인정보일 수 있고 국외 API로 갈 수 있음 → ZDR·서울리전·문서카테고리별 정책으로 관리.
- **단계적 처리(staged ingestion + backfill)**:
  - **1차(로컬 GPU 서버 구축 전)**: 비밀번호 잠긴 파일은 **열지 않고 메타데이터만 등록**, 나머지만 마스킹→임베딩→DB화.
  - **2차(로컬 서버 구축 후)**: `pending_password` 파일만 골라 비번 해제·(필요시 GPU OCR)·마스킹·임베딩으로 **백필**. 전체 재처리 금지.
- **멱등성**: 파일별 SHA-256 콘텐츠 해시를 키로 사용. 동일 ZIP 재적재 시 중복 임베딩 방지.

### 0.3 핵심 불변식 (모든 Phase가 지켜야 함)
1. 클라우드로 나가는 모든 텍스트는 **마스킹 완료 상태**여야 한다.
2. 1차에서는 잠긴 파일을 **열지 않는다**(탐지만).
3. 임베딩 차원(dimension)은 시스템 전체에서 **하나로 고정**한다.
4. 재처리는 **해시 + status 기반**으로만 한다(전체 재임베딩 금지).
5. 권한은 앱 레이어가 아니라 **DB의 RLS**로 강제한다.
6. **임베딩 모델 버전을 핀(pin)한다.** 차원이 같아도 다른 모델 벡터를 같은 공간에 섞지 않는다. 모델 교체는 §7.D의 "전체 재임베딩"이 유일한 허용 예외다.
7. **마스킹은 신뢰하지 않고 게이트로 검증한다.** 클라우드 전송 직전 PII 정규식 재스캔에서 1건이라도 걸리면 전송을 **차단(block)** 하고 격리한다(§7.A). 탐지를 통과한 것만 나간다.
8. **권한은 기본 거부(deny-by-default).** 문서의 열람 허용 집합을 신뢰도 있게 도출하지 못하면 일반 공개가 아니라 관리자 전용으로 격리한다(§7.B).

---

## Phase 0: 기술 스택 검증 (Allowed APIs)

> 구현 전 각 라이브러리의 "실제 존재하는" API만 사용한다. 추측 API 금지.
> 아래는 후보이며, 각 Phase 착수 시 공식 문서로 시그니처를 재확인한다.

### 0.A 수집 · 파싱 (Python, 로컬)
| 용도 | 라이브러리 | 핵심 API / 확인 포인트 |
|---|---|---|
| ZIP 처리·암호화 탐지 | stdlib `zipfile` | `ZipInfo.flag_bits & 0x1` 로 엔트리 암호화 여부 판별(추출 없이) |
| PDF 텍스트 | `pypdf` / `pdfplumber` | `PdfReader.is_encrypted` 로 잠금 판별 |
| HWP/HWPX | `olefile`(탐지), `pyhwp`/`hwp5`(파싱), HWPX=zip 기반 | OLE 스트림·암호화 플래그 확인 |
| MS Office | `python-docx`, `openpyxl`, `msoffcrypto-tool` | 암호화 OOXML = OLE 컨테이너 → `msoffcrypto`로 탐지/복호 |

### 0.B OCR (로컬)
| 후보 | 비고 |
|---|---|
| **PaddleOCR** (`lang="korean"`) | 정확도 우수, NVIDIA GPU 가속. 본 서버 표준 후보 |
| EasyOCR (`["ko","en"]`) | Mac/CPU에서 동작, 1차 적합 |
| Tesseract (`kor`) | 경량, 품질 낮음 |

### 0.C 개인정보 탐지 · 마스킹 (로컬, CPU)
| 용도 | 방법 |
|---|---|
| 정형 PII | **정규식**: 주민등록번호, 전화번호, 이메일, 계좌/카드번호 |
| 비정형 PII | **한국어 NER**: 이름·주소·기관 (KoELECTRA/KLUE 기반 NER 모델) |
| 프레임워크 | **Microsoft Presidio** (Analyzer + Anonymizer, custom recognizer 지원) — 표준 마스킹 파이프라인 |

> 검증 필요: Presidio에 한국어 custom recognizer 등록, Anonymizer 치환 정책(`replace`/`mask`/`hash`).

### 0.D 임베딩 (차원 고정)
| 옵션 | 차원 | 특징 |
|---|---|---|
| **BGE-M3** (로컬/클라우드 양쪽 가능) | 1024 | 다국어·한국어 강함, 로컬·클라우드 전환 자유 → **권장 기본값** |
| OpenAI `text-embedding-3-large` | 3072 | 클라우드, 품질 우수 |
| Voyage `voyage-3` | 1024 | 클라우드, 다국어 |

> **결정**: pgvector 컬럼은 `vector(1024)`로 고정하고, 임베딩 제공자를 추상화 계층 뒤에 둔다(교체 가능).

### 0.E 벡터DB · 권한 (Supabase)
- Postgres + `pgvector` 확장, `vector(1024)` 컬럼, **HNSW 인덱스**.
- 유사도 검색용 **RPC 함수**(`match_documents(query_embedding, ...)`).
- **RLS(Row Level Security)** 로 부서/직급별 접근 제어.
- 리전 **서울(ap-northeast-2)**. 민감도 높으면 self-hosted 옵션 검토.

### 0.F LLM · 프론트엔드
- LLM: **Claude API** (`claude-opus-4-8` / `claude-sonnet-4-6`), ZDR 옵션. RAG 답변·분류·요약.
- 프론트: **Next.js (App Router)** + **AI SDK v6** 스트리밍 채팅.
- (선택) Vercel AI Gateway로 제공자 추상화·ZDR.

### 0.G 활용 기능
- Google Calendar API v3 (`events.insert`), OAuth2.
- 반복문서 생성: 템플릿 + LLM. 한국 공문서 양식은 `korean-gov-doc` / `hwpx` 스킬 활용.

### 0.H 안티패턴 (하지 말 것)
- ❌ 마스킹 전 텍스트를 임베딩/LLM API로 전송
- ❌ 1차에서 잠긴 파일 강제 오픈
- ❌ pgvector 차원 불일치(임베딩 모델 혼용)
- ❌ 해시 무시한 전체 재임베딩
- ❌ RLS 없이 앱 코드로만 권한 처리
- ❌ 존재하지 않는 라이브러리 메서드/파라미터 추측 사용

---

## 1. 아키텍처

### 1.1 데이터 흐름 (마스킹 경계선 명시)

```
[ZIP 누적 폴더] (한 폴더에 계속 적재)
      │
      ▼
┌─────────────────────── 로컬 (현재 Mac → 추후 GPU 서버) ───────────────────────┐
│  Watcher → ZIP 풀기 → 파일별 SHA-256 해시 → 잠금 탐지                          │
│      ├─ 잠김 → 메타데이터만 DB 등록 (status=pending_password)  [본문 안 봄]     │
│      └─ 안 잠김                                                                │
│            ├─ 텍스트형 → Parser로 텍스트 추출                                   │
│            └─ 스캔형  → OCR (1차: EasyOCR/CPU, 2차: PaddleOCR/GPU)              │
│                  │                                                             │
│                  ▼                                                             │
│            개인정보 탐지(정규식 + 한국어 NER)                                   │
│                  │                                                             │
│                  ▼                                                             │
│            ⭐ 마스킹  ← ★여기까지 원본 개인정보. 이 선을 넘으면 마스킹본만★      │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                    │ (마스킹된 텍스트만)
                                    ▼
┌──────────────────────────── 클라우드 ─────────────────────────────────────────┐
│   Embedding(1024d) → Supabase(pgvector + 메타 + RLS)                           │
│                              │                                                 │
│         ┌────────────────────┼─────────────────────┐                          │
│         ▼                    ▼                     ▼                           │
│   키워드/벡터 검색      LLM 챗봇(RAG)         활용기능(흐름도/일정/보고서)        │
│         │                    │                     │                           │
│         └──────── 권한 확인(RLS + 직급/부서) ───────┘                           │
│                              │                                                 │
│                              ▼                                                 │
│                            답변 / 산출물                                        │
└────────────────────────────────────────────────────────────────────────────────┘
```

### 1.2 컴포넌트
- **ingest-worker** (Python, 로컬): 폴더 감시, 파싱, OCR, 마스킹, 임베딩 호출, DB 적재.
- **kmu-wiki-web** (Next.js, Vercel): 검색 UI, 챗봇, 활용기능 화면.
- **Supabase**: Postgres+pgvector, RLS, Auth.
- **Hermes Agent**: 분류·일정·보고서·반복문서 오케스트레이션(AI SDK / Claude tool-use).

---

## 2. 데이터 모델 (Supabase 스키마 초안)

```sql
-- 확장
create extension if not exists vector;

-- 원천 ZIP 추적
create table zip_archives (
  id            uuid primary key default gen_random_uuid(),
  filename      text not null,
  sha256        text not null unique,        -- ZIP 자체 해시(중복 적재 방지)
  imported_at   timestamptz default now(),
  file_count    int
);

-- 문서(파일) 단위
create table documents (
  id            uuid primary key default gen_random_uuid(),
  zip_id        uuid references zip_archives(id),
  path_in_zip   text not null,
  filename      text not null,
  sha256        text not null unique,        -- 멱등성 키
  mime_type     text,
  is_encrypted  boolean default false,
  status        text not null default 'pending',  -- processed|pending_password|pending_ocr|failed
  dept          text,                         -- 권한 분류용(부서)
  doc_date      date,
  task_category text,                         -- 업무별 구분(Phase 4에서 채움)
  created_at    timestamptz default now(),
  processed_at  timestamptz
);

-- 청크 + 임베딩 (마스킹된 본문만 저장)
create table doc_chunks (
  id            uuid primary key default gen_random_uuid(),
  document_id   uuid references documents(id) on delete cascade,
  chunk_index   int not null,
  content       text not null,               -- ⚠️ 반드시 마스킹된 텍스트
  embedding     vector(1024),                -- 차원 고정
  token_count   int
);

create index on doc_chunks using hnsw (embedding vector_cosine_ops);

-- 권한 매핑(직급/부서 → 접근 가능 범위)
create table access_roles (
  user_id   uuid,                            -- Supabase auth.users
  dept      text,
  role      text                             -- admin|manager|staff 등
);
```

**검색 RPC (예시 — Phase 2에서 실제 시그니처 확정):**
```sql
create or replace function match_chunks(
  query_embedding vector(1024),
  match_count int default 8,
  filter_dept text default null
) returns table (document_id uuid, content text, similarity float)
language sql stable as $$
  select c.document_id, c.content, 1 - (c.embedding <=> query_embedding) as similarity
  from doc_chunks c
  join documents d on d.id = c.document_id
  where d.status = 'processed'
    and (filter_dept is null or d.dept = filter_dept)
  order by c.embedding <=> query_embedding
  limit match_count;
$$;
```

> RLS는 `documents`/`doc_chunks`에 dept·role 기반 정책으로 별도 정의(Phase 2).

---

## Phase 1 — 수집 파이프라인 MVP (로컬 서버 전, 현재 Mac)

### 무엇을 구현하나
ZIP 누적 폴더 → 잠금 탐지 → (안 잠긴 것만) 파싱 → 마스킹 → 임베딩 → Supabase 적재.
잠긴 파일은 **메타데이터만** 등록(`status=pending_password`).

### 작업 항목
1. **폴더 감시·해시**: 지정 폴더의 새 ZIP 감지, ZIP·파일별 SHA-256 계산, 중복 스킵.
2. **잠금 탐지**(본문 미오픈): `zipfile` 플래그, PDF `is_encrypted`, Office/HWP OLE 플래그.
   - 잠김 → `documents`에 메타만 insert(`is_encrypted=true`, `status=pending_password`).
3. **파싱**: 텍스트형 문서 추출(pdfplumber/python-docx/openpyxl/hwp).
   - 스캔형이면서 CPU OCR로 감당되면 EasyOCR 처리, 무거우면 `status=pending_ocr`로 지연.
4. **메타데이터 추출**: 전자결재 ZIP의 구조(폴더명·index 파일·문서 헤더)에서 `dept`·`doc_date`·작성자·문서번호를 파싱해 `documents`에 채운다. **`dept`는 Phase 2 RLS의 전제이므로 1차에서 반드시 채운다**(못 채우면 `dept=null` → 관리자 전용으로 격리, 불변식 8).
5. **개인정보 탐지·마스킹(로컬, CPU)**: 정규식(주민번호 등) + 한국어 NER. Presidio Anonymizer로 치환. **OCR 본문은 고위험 등급**으로 더 공격적 마스킹 정책 적용(§7.A).
6. **이그레스 게이트(egress gate)**: 임베딩 호출 직전, 마스킹 결과를 PII 정규식으로 재스캔. 1건이라도 검출되면 전송 차단 + `status=quarantine` 격리(불변식 7).
7. **청킹·임베딩**: 마스킹 본문을 청크 분할(§7.C 전략) → 임베딩(1024d, 모델 핀) → `doc_chunks` 적재, `documents.status=processed`.
8. **운영·관측성**: 처리 로그, 실패 시 `status=failed` + 재시도 큐, 단계별 성공/실패율 메트릭(§7.F).

### 문서 참조
- §0.A 파싱, §0.C 마스킹(Presidio), §0.D 임베딩, §2 스키마.

### 검증 체크리스트
- [ ] 잠긴 파일이 단 한 번도 열리지 않음(로그로 확인) → `pending_password`로만 기록
- [ ] 클라우드로 나가는 페이로드를 캡처해 **원본 PII 미포함** 확인(주민번호 정규식 grep = 0)
- [ ] 같은 ZIP 재적재 시 중복 임베딩 0건(해시 멱등성)
- [ ] `doc_chunks.embedding` 차원이 전부 1024
- [ ] 샘플 문서 임베딩→유사도 검색이 의미 있는 결과 반환

### 안티패턴 가드
- 마스킹 전에 임베딩 API 호출하는 코드 경로가 없어야 함(코드 리뷰/그렙).
- 잠금 탐지 실패 시 "일단 열어보기" 폴백 금지 → 보수적으로 `pending_password`.

---

## Phase 2 — 검색 + LLM 챗봇 + 권한(RLS)

> 구현 현황(2a 완료): 하이브리드 검색 SQL + Python 검색·RAG 코어 + FastAPI + Next.js 얇은 클라이언트.
> 핵심 결정: 쿼리 임베딩을 문서와 동일 모델로 보장하기 위해 검색·RAG·LLM을 Python(`kmu_query`)에
> 두고, Next.js는 SSE 프록시·UI만 담당(불변식 6). 검증: 검색/RAG 코어 단위테스트 6종 통과(총 38).
> 남은 작업(2b): 로그인 UI(Supabase Auth), 키워드 검색 페이지, 실 Supabase·Claude 연결 통합 테스트.

### 무엇을 구현하나
Next.js 웹에서 키워드/벡터 하이브리드 검색과 RAG 챗봇 제공. RLS로 부서·직급별 접근 제어.

### 작업 항목
1. **RLS 정책**: `documents`/`doc_chunks`에 dept·role 기반 SELECT 정책. JWT 클레임 매핑.
2. **검색 API**: 키워드(Postgres FTS) + 벡터(`match_chunks`) 하이브리드, dept 필터.
3. **RAG 챗봇**: 질의 임베딩 → 관련 청크 검색(권한 필터 적용) → Claude로 답변 생성(출처 표시).
4. **웹 UI**: AI SDK v6 스트리밍 채팅, 검색 결과·출처 문서 링크.

### 문서 참조
- §0.E RLS·RPC, §0.F LLM·AI SDK, §2 `match_chunks`.

### 검증 체크리스트
- [ ] 권한 없는 부서 문서가 검색·답변에 절대 노출되지 않음(다른 dept 계정으로 테스트)
- [ ] 챗봇 답변에 출처 문서가 정확히 인용됨
- [ ] RLS를 우회하는 쿼리 경로 없음(service_role 키가 클라이언트에 노출 안 됨)

### 안티패턴 가드
- ❌ service_role 키를 프론트엔드 번들에 포함. ❌ 앱 코드 if문만으로 권한 처리(RLS 필수).

---

## Phase 3 — 로컬 GPU 서버 + 백필 (비번 해제 / OCR)

### 무엇을 구현하나
로컬 GPU 서버 구축 후, `pending_password`·`pending_ocr` 파일만 골라 처리하는 백필 워커.

### 작업 항목
1. **서버 구축**: Linux + NVIDIA GPU(중규모 기준 RTX 4060Ti 16GB/4070, RAM 64GB, NVMe 2TB+백업).
   - 인터넷 망 분리, 마스킹 이후 트래픽만 아웃바운드 허용(방화벽).
2. **비밀번호 처리**: 기관 공통 패턴 사전(교번·생년월일·문서번호 등)으로 자동 해제 시도(설정파일 기반).
   - 실패분은 수동 입력 큐로 분리.
3. **GPU OCR**: PaddleOCR(korean)로 `pending_ocr`·해제된 스캔본 처리.
4. **백필 실행**: `status in (pending_password, pending_ocr)`만 조회 → 해제/OCR → 마스킹 → 임베딩 → `status=processed` 갱신. **이미 processed는 건드리지 않음.**

### 문서 참조
- §0.B OCR, §0.A `msoffcrypto`/PDF 복호, §1 흐름도 2차 경로.

### 검증 체크리스트
- [ ] 백필이 `processed` 문서를 재처리하지 않음(카운트 0)
- [ ] 해제된 파일도 마스킹 경계 통과(원본 PII 미유출)
- [ ] 비번 자동 해제 실패분이 수동 큐로 안전하게 격리됨

### 안티패턴 가드
- ❌ 백필 시 전체 재임베딩. ❌ 비번 시도 무제한 brute-force(설정 사전 범위로 제한).

---

## Phase 4 — 활용 기능 (분류 · 흐름도 · 연간일정 · 보고서)

### 무엇을 구현하나
DB를 기반으로 업무별 구분, 업무흐름도, 연간일정(구글 연동), 보고서 작성 보조.

### 작업 항목
1. **업무별 구분(분류)**: LLM 분류로 `documents.task_category` 채움(부서·문서유형·연도).
2. **업무흐름도**: 같은 업무군 문서들의 결재 순서·단계를 시계열·결재라인으로 재구성 → 다이어그램(Mermaid) 생성.
3. **연간일정 자동설계 + 구글 연동**: 반복 패턴(연례 행사·정기 보고)을 추출해 연간 캘린더 초안 생성 → Google Calendar API `events.insert`.
4. **보고서 작성 보조**: 주제 질의 → 관련 문서 검색 → 초안 생성(출처 포함).
5. **키워드 조회**: Phase 2 검색 UI 확장(필터·패싯).

### 문서 참조
- §0.G Google Calendar, §0.F LLM, Phase 2 검색.

### 검증 체크리스트
- [ ] 분류 정확도 샘플 검수(부서·연도 라벨)
- [ ] 흐름도가 실제 결재 순서와 일치
- [ ] 캘린더 이벤트가 의도한 날짜·반복규칙으로 생성됨

---

## Phase 5 — Hermes Agent + 반복업무 문서 자동생성

### 무엇을 구현하나
업무를 체계화·업데이트하는 에이전트와, 매년 반복되는 업무 문서의 자동 생성.

### 작업 항목
1. **Hermes Agent**: 도구(검색·분류·일정·문서생성)를 가진 오케스트레이터(Claude tool-use/AI SDK).
   - 신규 ZIP 적재 시 분류·일정·흐름도를 갱신하고 변경점을 요약 보고.
2. **반복업무 탐지**: 연도만 다르고 구조가 동일한 문서군 식별(제목·결재라인·시기 패턴).
3. **문서 자동생성**: 전년도 문서를 템플릿화 → 올해 값으로 채워 초안 생성.
   - 한국 공문서 양식은 `korean-gov-doc`/`hwpx` 스킬로 출력. **생성물에 PII 자동 삽입 금지**(빈칸/플레이스홀더).

### 검증 체크리스트
- [ ] 반복업무 탐지의 오탐/누락 검수
- [ ] 자동생성 초안에 실제 개인정보가 들어가지 않음(플레이스홀더 처리)
- [ ] Hermes 갱신 보고가 실제 DB 변경과 일치

---

## Phase 6 — 최종 검증

1. **보안 회귀**: 클라우드 아웃바운드 트래픽 샘플에서 PII grep = 0 (전 Phase 통합).
2. **권한 회귀**: 부서별 계정으로 교차 접근 테스트, RLS 우회 없음.
3. **멱등성 회귀**: 동일 ZIP 재적재·백필 후 중복 0건, 차원 일관성.
4. **안티패턴 그렙**: 마스킹 전 임베딩 호출, service_role 노출, 차원 혼용, 무제한 brute-force 부재 확인.
5. **기능 스모크**: 검색·챗봇·분류·흐름도·캘린더·반복문서 각 1건 end-to-end.

---

## 7. 설계 리뷰 및 보강 (Hardening)

> 초안을 보안·정확성·운영 관점에서 재검토하여 발견한 갭과 보강안. 각 항목은 위 Phase에 흡수된다.

### 7.A 마스킹은 "단일 단계"가 아니라 "다층 방어 + 게이트"여야 한다 ★최우선
**문제**: 마스킹을 한 번의 탐지 단계로 두면, 탐지 실패(false negative) 1건이 곧 원본 PII의 외부 유출이다. 특히 한국어 NER은 **OCR로 깨진 텍스트**에서 이름·주소를 자주 놓친다. "마스킹 완료"를 신뢰하는 설계는 위험하다.
**보강(다층 방어)**:
1. **L1 정규식**: 주민번호·전화·이메일·계좌·카드 (높은 재현율).
2. **L2 한국어 NER**: 이름·주소·기관.
3. **L3 이그레스 게이트(하드 차단)**: 전송 직전 PII 정규식 **재스캔**. 1건이라도 걸리면 전송 차단 → `status=quarantine`. (불변식 7)
4. **OCR 고위험 등급**: OCR 본문은 정규식 패턴을 느슨하게(공백·오인식 허용) 적용하고, 신뢰도 낮으면 격리.
5. **골든 평가셋**: PII가 라벨링된 표본 문서 50~100건으로 **재현율(recall)을 정기 측정**. 목표 예: 정형 PII recall ≥ 0.99.
   - ✅ 구현됨: `ingest/evaluation/`(하네스 + 합성 골든 10건 + CI 게이트, exit 1 on fail).
   - 측정 결과: 정형 PII recall 1.0·과다마스킹 0. **성명 recall은 NER 컨텍스트 의존성으로 변동**(게이트가 차단). 운영 전 (a)골든셋 확대 50~100건, (b)성씨 가제티어+역할어 컨텍스트 보강, (c)NER 모델 검토 필요.
6. **샘플 인간 검수**: 처리분 일부를 무작위 추출해 마스킹 누락 점검.
**연결**: Phase 1 작업 5·6, Phase 6 보안 회귀.

### 7.B 권한 도출 모델을 명확히 (기본 거부) ★최우선
**문제**: "부서·직급별 접근"은 모호하다. 전자결재 문서의 실제 열람권은 작성자·결재라인·열람지정자·보안등급으로 결정되는데, **그 ACL이 ZIP에 들어 있지 않으면** 우리가 권한을 "재도출"해야 하고, 잘못하면 과다 노출된다.
**보강**:
1. ZIP/메타에 열람권 정보가 있으면 그대로 매핑. 없으면 **부서 단위로 보수적 제한**.
2. **deny-by-default**(불변식 8): `dept` 미상 또는 보안등급 미상 문서는 일반 검색에서 제외, 관리자 전용.
3. RLS 정책을 "허용 목록" 방식으로 작성(명시 허용만 노출).
4. 보안등급 필드(`security_level`) 추가 검토: 대외비/일반 구분.
**미결정(부록 B로)**: 전자결재 ZIP에 열람권/보안등급 메타가 포함되는가? → 샘플 ZIP 1건 구조 분석 필요.

### 7.C 청킹 전략을 명시한다
**문제**: 청크 크기·중첩·문서 구조 매핑이 미정이면 검색 품질이 들쭉날쭉해진다. 결재 문서는 제목·본문·결재라인·표·첨부가 섞여 있다.
**보강**:
- 구조 인식 청킹: 제목·기안문 본문·표를 분리. 표는 행 단위 보존.
- 크기 예시: 300~500 토큰, 중첩 50~80 토큰(착수 시 튜닝).
- 각 청크에 문서 메타(부서·날짜·문서번호)를 프리픽스로 부착 → 검색 정확도↑.
- 한국어 토크나이저 기준으로 길이 산정.

### 7.D 임베딩 모델 버전 핀 + "재임베딩" 예외 규칙
**문제**: "전체 재임베딩 금지"와 모델 교체가 충돌한다. 차원이 같아도 1차(예: cloud)와 2차(예: 로컬 BGE-M3)가 **다른 모델**이면 벡터 공간이 어긋나 검색이 망가진다.
**보강**:
- `doc_chunks`에 `embed_model`·`embed_version` 컬럼 추가, 모든 청크에 기록.
- 시스템 전체에서 **단일 모델·버전 고정**. 1차·2차 백필 모두 동일 모델 사용.
- 모델 교체는 **유일하게 허용되는 전체 재임베딩**으로만 수행(계획된 마이그레이션). (불변식 6)

### 7.E 문서 갱신·회수·버전 처리
**문제**: ZIP은 누적되지만 같은 업무 문서가 재기안·수정·회수될 수 있다. 해시 멱등성은 "추가"만 다루고 "대체/폐기"를 다루지 않는다.
**보강**:
- `documents`에 `doc_no`(문서번호)·`version`·`superseded_by` 추가.
- 같은 `doc_no`의 신규 버전 적재 시 구버전을 `status=superseded`로 내려 검색에서 기본 제외(이력은 보존).
- 회수 문서는 `status=revoked`.

### 7.F 운영·관측성·감사·백업
**문제**: 개인정보 인접 시스템인데 감사·모니터링·백업이 계획에 없다.
**보강**:
- **감사 로그**: 누가 어떤 문서를 검색·열람했는지 기록(개인정보보호법 대응). `access_log` 테이블.
- **모니터링**: 단계별 처리량·실패율·격리(quarantine) 건수 대시보드.
- **백업**: 원본 ZIP 폴더 별도 백업(부록 A), Supabase PITR/백업 정책.
- **비용 추정**: 임베딩·LLM 토큰 비용을 누적 문서 수 기준으로 사전 산정(부록 B).

### 7.G Hermes 자동생성물의 거버넌스
**문제**: 자동 생성된 공문서가 검토 없이 사용되면 위험(오류·부적절 PII 삽입).
**보강**:
- 모든 자동생성 문서는 **초안(draft) 상태**로만 산출, 사람 승인 게이트 필수.
- 생성물에 PII 직접 삽입 금지 → 플레이스홀더(예: `{성명}`)로 비움. (Phase 5 검증)

### 7.H 리스크 레지스터
| 리스크 | 영향 | 가능성 | 완화 |
|---|---|---|---|
| 마스킹 누락으로 PII 유출 | 치명 | 중 | §7.A 다층+게이트+평가셋 |
| 권한 재도출 과다 노출 | 치명 | 중 | §7.B deny-by-default + 샘플 검수 |
| HWP 파싱 실패(구형 포맷) | 중 | 높음 | HWPX 우선, 실패분 `pending_ocr`/수동, 변환 스킬 활용 |
| OCR 품질 저하 → 검색·마스킹 악화 | 중 | 중 | 2차 GPU PaddleOCR, 고위험 등급 처리 |
| 임베딩 모델 혼용 | 높음 | 낮음 | §7.D 모델 핀 |
| 외부 API 정책 변경/금지 | 높음 | 중 | 임베딩·LLM 추상화로 로컬 전환 가능하게 |
| 클라우드 비용 폭증 | 중 | 중 | 사전 산정·청크 수 상한·배치 |

### 7.I 보강으로 추가되는 스키마 변경 요약
```sql
alter table documents add column doc_no text;
alter table documents add column version int default 1;
alter table documents add column superseded_by uuid;
alter table documents add column security_level text;   -- 일반|대외비 등(7.B)
-- status에 quarantine|superseded|revoked 값 추가(7.A/7.E)
alter table doc_chunks add column embed_model text;      -- 7.D
alter table doc_chunks add column embed_version text;
create table access_log (                                 -- 7.F
  id uuid primary key default gen_random_uuid(),
  user_id uuid, document_id uuid, action text,
  at timestamptz default now()
);
```

---

## 부록 A — 서버 사양 요약 (참고)

| | 소규모(CPU) | 중규모(권장) | 대규모 |
|---|---|---|---|
| CPU | 8코어 | 12~16코어 | 16코어+ |
| RAM | 32GB | 64GB | 128GB |
| GPU | 없음 | RTX 4060Ti 16GB/4070 | RTX 4090 24GB/A6000 48GB |
| 스토리지 | 1TB SSD | 2TB NVMe | 4TB NVMe+백업 |
| 원본 보관 | — | +백업 2TB 권장 | — |

> 1차는 현재 Mac(CPU 마스킹·EasyOCR)로 시작 가능. GPU 서버는 Phase 3에서.

## 부록 B — 미확정/확인 필요 항목
- [x] **샘플 ZIP 구조 분석 완료** (2026-06): ZIP=결재 1건, 최상위 폴더(제목) 안에 본문 기안문 PDF(폴더명과 동일) + 붙임(hwp/xls/pdf/html/mht). 파일명은 CP949.
  - **열람권/보안등급 메타파일 없음** → §7.B 확정: dept는 본문 기안문의 `시행 <부서>-<번호>`에서만 추출, 없으면 deny-by-default. 보안등급은 항상 미상 → 관리자 전용.
  - 본문 기안문 PDF는 **텍스트 기반**(pdfplumber 추출 가능). `제 목`/`시행 부서-번호`/시행일자 추출 구현·검증됨.
  - HWP: 비암호는 PrvText 스트림으로 추출, 암호 HWP는 FileHeader 0x02 비트로 탐지→pending_password(실데이터에서 '태권도 명단.hwp' 정확히 격리).
  - 실데이터 13파일 → 12 processed / 1 pending_password, 마스킹·이그레스 게이트 클린.
- [ ] 전자결재 아카이브 총 문서 수 / 연간 증가량 → 서버 티어 확정
- [ ] 학교 외부 API 정책 수립(클라우드 LLM·임베딩 허용 범위, ZDR 계약)
- [ ] 임베딩 제공자 최종 선택(BGE-M3 로컬 vs 클라우드) — 차원 1024 고정·모델 핀 전제(§7.D)
- [ ] 비밀번호 공통 패턴 사전 범위(교번/생년월일/문서번호 등)
- [ ] Supabase: managed(서울 리전) vs self-hosted(온프레미스)
- [ ] Google Workspace 연동 방식(OAuth vs 서비스계정)
- [ ] 클라우드 비용 사전 산정(임베딩·LLM 토큰 × 누적 문서 수) (§7.F)
- [ ] PII 골든 평가셋 50~100건 라벨링(§7.A 재현율 측정용)
