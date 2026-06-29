# KMU Wiki

학교 전자결재 문서(ZIP)를 수집·정제·DB화하여 검색·RAG 챗봇·업무자동화로 활용하는 시스템.

설계 전문: [plans/kmu-wiki-master-plan.md](plans/kmu-wiki-master-plan.md)

## 구조 (모노레포)
| 디렉터리 | 내용 |
|---|---|
| `ingest/` | Python 인제스트 워커 — 잠금탐지·파싱·**마스킹**·임베딩·Supabase 적재 (Phase 1) |
| `ingest/kmu_query/` | 검색·RAG 코어 — 하이브리드 검색·RLS·Claude 답변 (Phase 2) |
| `ingest/evaluation/` | 마스킹 품질 평가 하네스(골든셋·재현율 게이트) |
| `supabase/migrations/` | DB 스키마·pgvector·RLS·하이브리드 검색 RPC |
| `web/` | Next.js 검색·챗봇 UI (Vercel 배포 대상) |

## 핵심 원칙
- **마스킹 경계선**: 주민번호·계좌·카드·이메일은 클라우드 전송 직전 마스킹. 정책(`MaskPolicy`)으로 토글.
- **단계적 처리**: 잠긴 파일은 1차에서 메타만 등록(`pending_password`), 로컬 GPU 서버 구축 후 백필.
- **권한**: Supabase RLS로 부서·보안등급별 강제(deny-by-default).
- **임베딩 모델 핀**: 쿼리·문서 동일 모델(1024차원).

## 빠른 시작
- 인제스트: `cd ingest && python -m kmu_ingest.cli run --dry-run`
- 테스트: `cd ingest && python -m unittest discover -s tests`
- 마스킹 평가: `cd ingest && python -m evaluation.evaluate`
- 검색 API: `cd ingest && uvicorn kmu_query.service:app --port 8000`
- 웹: `cd web && npm install && npm run dev`

## 배포
- **루트** → Vercel Services. `web/`은 Next.js 웹, `ingest/main.py`는 `/rag` FastAPI 검색·RAG 서비스.
- **ingest/** 워커 → 학교 내부/로컬에서 실행. 원본 ZIP 파싱·마스킹·임베딩 적재는 Vercel에서 수행하지 않는다.
