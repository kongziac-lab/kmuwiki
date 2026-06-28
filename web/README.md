# KMU Wiki — 웹 (Phase 2)

검색·RAG 챗봇 UI. **얇은 클라이언트**다 — 실제 검색/임베딩/LLM은 Python 서비스가 담당한다.

## 아키텍처 결정 (왜 AI SDK가 아니라 프록시인가)
쿼리 임베딩은 **문서 임베딩과 동일한 모델**이어야 한다(불변식 6). 그 임베더는 Python
(`kmu_ingest.embedding`)에 있으므로, 검색·RAG·LLM 스트리밍을 Python 서비스(`kmu_query`)에
두고 Next.js는 그 SSE 스트림을 프록시·렌더링만 한다. 이렇게 하면 모델 일치가 코드로 보장되고
교차언어 임베딩 불일치가 원천 차단된다. (추후 원하면 LLM 호출만 AI SDK로 옮길 수 있음.)

## 구성
- `app/page.tsx` — 채팅 UI(클라이언트). 로그인 세션의 JWT를 실어 `/api/chat` 호출, SSE 렌더.
- `app/api/chat/route.ts` — Python `/chat` 으로 스트리밍 프록시. 사용자 JWT 전달(RLS 적용), Python URL은 서버 전용.
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

## 남은 작업 (다음 단계)
- 로그인 UI(Supabase Auth) — 현재는 세션이 있다고 가정.
- 키워드-only 검색 페이지(`/search`), 출처 문서 원문 보기.
- 코드는 App Router 패턴을 따르지만 설치된 Next 버전 기준으로 빌드 검증 필요.
