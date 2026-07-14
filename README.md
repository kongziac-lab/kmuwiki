# KMU Wiki

학교 전자결재 문서(ZIP)를 수집·정제·DB화하여 검색·RAG 챗봇·업무자동화로 활용하는 시스템.

설계 전문: [plans/kmu-wiki-master-plan.md](plans/kmu-wiki-master-plan.md)

## 구조 (모노레포)
| 디렉터리 | 내용 |
|---|---|
| `ingest/` | Python 인제스트 워커 — 잠금탐지·파싱·**마스킹**·임베딩·Supabase 적재 (Phase 1) |
| `ingest/kmu_query/` | 검색·RAG 코어 — 하이브리드 검색·RLS·Claude 답변 (Phase 2) |
| `ingest/kmu_query/insights.py` | 분류·흐름도·일정·보고서 초안 코어 (Phase 4) |
| `ingest/kmu_query/hermes.py` | 반복업무 탐지·안전한 문서 초안·변경 보고 코어 (Phase 5) |
| `ingest/kmu_query/studio.py` | NotebookLM식 산출물 — 마인드맵·슬라이드(Marp)·인포그래픽(SVG)·요약 (Phase 7). 문서: [docs/studio-notebooklm-quality.md](docs/studio-notebooklm-quality.md) |
| `ingest/evaluation/` | 마스킹 품질 평가 하네스(골든셋·재현율 게이트) |
| `supabase/migrations/` | DB 스키마·pgvector·RLS·하이브리드 검색 RPC |
| `web/` | Next.js 검색·챗봇 UI (Vercel 배포 대상) |

## 핵심 원칙
- **마스킹 경계선**: 주민번호·계좌·카드·이메일은 클라우드 전송 직전 마스킹. 정책(`MaskPolicy`)으로 토글.
- **단계적 처리**: 잠긴 파일은 1차에서 메타만 등록(`pending_password`), 로컬 GPU 서버 구축 후 백필.
- **원본/지식베이스 분리**: 원본 ZIP은 한 폴더에 계속 넣고, 지식베이스 정리는 임베딩·업무분류 메타(`task_category`)·검토 플래그로 수행.
- **권한**: Supabase RLS로 부서·보안등급별 강제(deny-by-default).
- **임베딩 모델 핀**: 쿼리·문서 동일 모델(1024차원).
- **멀티모달 v2**: PP-StructureV3/한국어 PP-OCRv5 → Cohere Embed v4 → Rerank v4.
  원본 이미지는 로컬에만 두고 RLS가 적용된 마스킹 파생본만 사용한다.

구체적인 모델, 보안 경계, NAS 연결 PC의 재구축·롤백 절차는
[멀티모달 v2 운영 문서](docs/multimodal-v2.md)를 참고한다.

## 빠른 시작
- 인제스트: `cd ingest && python -m kmu_ingest.cli run --path ./zips --dry-run`
- 백필: `cd ingest && python -m kmu_ingest.cli backfill --dry-run`
- v2 현황: `cd ingest && python -m kmu_ingest.cli v2-status`
- v2 재구축: `cd ingest && python -m kmu_ingest.cli reindex-v2 --path <NAS-01_raw>`
- 테스트: `cd ingest && python -m unittest discover -s tests`
- Phase 6 정적 검증: `cd ingest && python -m kmu_verify.phase6 --out ../phase6-report.json`
- 마스킹 평가: `cd ingest && python -m evaluation.evaluate`
- 요약 품질 평가: `cd ingest && python -m evaluation.summary_quality` (CI 게이트: `python scripts/verify_summary_quality.py`)
- 검색 API: `cd ingest && uvicorn kmu_query.service:app --port 8000`
  - 스튜디오: `POST /studio`(마인드맵·슬라이드·인포그래픽·지표), `POST /studio/summary`(요약 SSE)
- 웹: `cd web && npm install && npm run dev` — 스튜디오 화면은 `/studio`

## 관리자 모드
- `/admin`은 Supabase 로그인 후 `access_roles.role='admin'`인 사용자만 접근한다.
- 운영 Vercel에서는 현황 조회와 검토 큐 관리만 가능하다.
- 로컬 폴더 인제스트 실행은 `localhost` 관리자 모드에서만 가능하다.
- ZIP 폴더는 `KMU_ZIP_DIR`로 지정한다. macOS 경로, Windows 드라이브, NAS UNC 경로 모두 환경변수로 교체 가능하다.
  - macOS: `/Users/kdh/Documents/KMU-Wiki-Zips`
  - Windows: `Z:\KMU-Wiki-Zips`
  - NAS: `\\NAS\KMU-Wiki-Zips`

## 배포
- **루트** → Vercel Services. `web/`은 Next.js 웹, `ingest/main.py`는 `/rag` FastAPI 검색·RAG 서비스.
- **ingest/** 워커 → 학교 내부/로컬에서 실행. 원본 ZIP 파싱·마스킹·임베딩 적재는 Vercel에서 수행하지 않는다.
  - NAS(Synology DS920+) 상시 가동 허브로 컨테이너화하는 구성: [docs/nas-hub-architecture.md](docs/nas-hub-architecture.md) (`ingest/Dockerfile`·`docker-compose.yml`).
- 원본 ZIP 파일명/하위폴더는 `zip_archives.source_path`로 추적한다. 파일 보관 구조가 바뀌어도 검색 기준은 DB 메타데이터다.
- 암호가 있는 파일 내부 복호는 보안된 내부 로컬 서버 구축 전까지 의도적으로 유예한다. 그 전까지 `pending_password`는 수동 큐/격리 상태로 유지한다.
