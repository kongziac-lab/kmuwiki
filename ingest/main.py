"""Vercel Python 진입점 — 검색·RAG FastAPI 앱을 노출.

Vercel은 루트의 main.py 에 노출된 `app`(ASGI/FastAPI)을 자동 인식해 서빙한다.
env(SUPABASE_URL/SUPABASE_ANON_KEY/COHERE_API_KEY)는 Vercel 프로젝트 설정에서 주입된다.
이 서비스는 마스킹·임베딩이 끝난 Supabase 데이터만 조회한다(원본·service_role 미사용).
"""

from kmu_query.service import app

__all__ = ["app"]
