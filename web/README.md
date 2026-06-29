# KMU Wiki — 웹 (Phase 2)

검색·RAG 챗봇 UI. **얇은 클라이언트**다 — 실제 검색/임베딩/LLM은 Python 서비스가 담당한다.

## 아키텍처 결정 (왜 AI SDK가 아니라 프록시인가)
쿼리 임베딩은 **문서 임베딩과 동일한 모델**이어야 한다(불변식 6). 그 임베더는 Python
(`kmu_ingest.embedding`)에 있으므로, 검색·RAG·LLM 스트리밍을 Python 서비스(`kmu_query`)에
두고 Next.js는 그 SSE 스트림을 프록시·렌더링만 한다. 이렇게 하면 모델 일치가 코드로 보장되고
교차언어 임베딩 불일치가 원천 차단된다. (추후 원하면 LLM 호출만 AI SDK로 옮길 수 있음.)

## 구성
- `app/page.tsx` — 채팅 UI(클라이언트). 로그인 세션의 JWT를 실어 `/api/chat` 호출, SSE 렌더.
- `app/search/page.tsx` — 키워드/하이브리드 검색 UI. 권한 범위 내 마스킹 청크와 출처 메타 표시.
- `app/api/chat/route.ts` — Python `/chat` 으로 스트리밍 프록시. 사용자 JWT 전달(RLS 적용), Python URL은 서버 전용.
- `app/api/search/route.ts` — Python `/search` JSON 프록시. `/api/chat`과 같은 RLS/공유 시크릿 경로 사용.
- `app/api/insights/route.ts` — Python `/insights` 프록시. 분류·흐름도·일정·보고서 초안.
- `app/api/hermes/route.ts` — Python `/hermes` 프록시. 반복업무 탐지·안전한 문서 초안·변경 보고.
- `lib/ragProxy.ts` — Vercel Services(`/rag`)와 로컬 FastAPI(`PY_API_URL`) 경로 계산 및 공유 시크릿 헤더 구성.
- `lib/supabase.ts` — 브라우저 Supabase 클라이언트(세션 토큰 획득).

## 권한 (RLS)
- 로그인 사용자의 JWT → Python → Supabase RLS. **권한 밖 문서는 검색·답변에 안 나온다.**
- 로그인 안 하면 토큰 없음 → Python에서 anon → **deny-by-default**(아무것도 안 보임).

## 실행
```bash
# 1) Python 검색·RAG 서비스 (별도 터미널, ingest/)
uvicorn kmu_query.service:app --port 8000
# 2) 웹
cp .env.example .env.local   # 값 채우기
npm install && npm run dev
```

## 구현 상태
- 로그인 UI(Supabase Auth), 챗봇(`/`), 검색(`/search`) 구현.
- 설치된 Next.js 기준 `npm test`와 `npm run build` 검증.
