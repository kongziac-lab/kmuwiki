# KMU Wiki 운영 구조

## 실행 위치

로컬 PC는 원본 문서 처리 전용입니다.

- ZIP/HWP/HWPX/PDF 인제스트
- 텍스트 추출
- 개인정보 마스킹
- 임베딩 생성
- Supabase 저장

Vercel은 사용자-facing 기능 전용입니다.

- KMU Wiki 웹 앱
- 챗봇
- 문서 검색
- 업무 활용
- 보고서 생성
- HWPX 다운로드 API

Supabase는 권한과 검색 데이터의 단일 저장소입니다.

- 문서 DB
- 청크
- 메타데이터
- RLS 권한 관리
- 감사 로그

현재 `vercel.json`은 Vercel Services 구조로 설정되어 있습니다. `web/`은 `/`로, `ingest/main.py` FastAPI 서비스는 `/rag`로 노출됩니다.

## 운영 가드레일

- 문서별 청크 상한: `KMU_MAX_CHUNKS_PER_DOC`, 기본 80개
- 검색 결과 상한: `KMU_API_MAX_K`, 기본 20개
- 검색 기본값: `KMU_API_DEFAULT_K`, 기본 8개
- 요청 본문/질문 상한: `KMU_API_MAX_BODY_KB`, `KMU_API_MAX_QUERY_CHARS`
- 사용자별 분산 요청 제한: `KMU_API_RATE_LIMIT_PER_MINUTE`, 기본 분당 30회
- 외부 제공자 호출 제한시간: `KMU_PROVIDER_TIMEOUT_SECONDS`, 기본 120초
- 감사 로그 보존: DB 마이그레이션의 일일 정리 작업으로 기본 180일
- ZIP 중복 방지: `zip_archives.sha256` unique
- 문서 중복 방지: `documents.sha256` unique
- 부서/연도 검색 필터: `/search`, `/chat`, `/insights`, `/hermes`, `/reports`에서 `dept`, `year` 또는 `target_year` 전달
- pgvector HNSW 인덱스 확인: `admin_storage_health()` RPC의 `indexes.pgvector_hnsw`
- 감사 로그 정리: `cleanup_access_log(retention_days)` RPC
- 감사 쿼리: 이메일·전화번호·주민등록번호 마스킹, 500자/문서 50개 상한
- Supabase 용량 모니터링: `admin_storage_health()` RPC의 `database_bytes`, 테이블별 bytes/counts

## 중요 보안 원칙

Vercel 웹 앱에는 Supabase service role key를 넣지 않습니다. 웹/RAG API는 사용자 JWT를
검증한 뒤 anon key와 사용자 토큰으로 RLS를 적용합니다. 운영 환경은 내부 공유 시크릿과
명시적 CORS 허용 목록이 없으면 시작하지 않습니다.

로컬 인제스트 PC에만 `SUPABASE_SERVICE_ROLE_KEY`를 둡니다. 원본 문서 추출, OCR, 마스킹, 임베딩 생성은 로컬에서 끝낸 뒤 결과만 Supabase에 저장합니다.

## 검증 루프

운영 구조와 가드레일이 빠지지 않았는지 빠르게 점검합니다.

```powershell
python scripts/verify_operational_guardrails.py
```

검색 품질 기준선을 점검합니다.

```powershell
python scripts/verify_search_quality.py
```

주요 단위 테스트를 실행합니다.

```powershell
$env:PYTHONPATH='ingest'
python -m unittest ingest.tests.test_operational_guardrails ingest.tests.test_pipeline ingest.tests.test_rag
```

## 검색 품질 개선 루프

현재 검색 개선 순서는 다음을 기준으로 합니다.

1. Parser/metadata: 제목, 문서번호, 시행일, 부서, 붙임, 문서유형을 추출합니다.
2. Chunking: 제목/문서번호/날짜/붙임 prefix를 각 청크에 붙이고 `section_type`을 기록합니다.
3. Hybrid Search: 부서/연도 필터를 먼저 적용합니다.
4. Cohere Rerank: 후보를 재정렬하고 실패 시 hybrid 결과로 fallback합니다.
5. Monitoring: `access_log`에 latency, result count, rerank 적용 여부를 기록합니다.
6. Quality Report: `evaluation/golden/search_quality_synth.jsonl` 기준 `Recall@5`, `Recall@10`, `MRR`을 추적합니다.

웹 빌드를 실행합니다.

```powershell
cd web
npm run build
```
