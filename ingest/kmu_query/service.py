"""검색·RAG HTTP 서비스 (FastAPI).

  POST /search  → 하이브리드 검색 결과(출처) JSON
  POST /chat    → SSE 스트림(먼저 citations, 이어서 답변 토큰)

RLS: 요청의 Authorization: Bearer <사용자 JWT> 로 Supabase 클라이언트를 인증한다.
헤더가 없으면 anon 권한 → 정책상 아무 문서도 안 보인다(deny-by-default).
"""

from __future__ import annotations

import json

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from kmu_ingest.config import load_settings
from kmu_ingest.embedding import make_embedder

from . import rag
from .retriever import Retriever

settings = load_settings()
_embedder = make_embedder(settings.embed_provider, settings.embed_model, settings.embed_version)

app = FastAPI(title="KMU Wiki Search/RAG")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


def _client(authorization: str | None):
    """사용자 JWT로 인증된 Supabase 클라이언트(RLS 적용)."""
    from supabase import create_client

    c = create_client(settings.supabase_url, settings.supabase_anon_key)
    if authorization and authorization.lower().startswith("bearer "):
        c.postgrest.auth(authorization.split(" ", 1)[1])
    return c


def _retriever(authorization: str | None) -> Retriever:
    return Retriever(_client(authorization), _embedder)


@app.post("/search")
async def search(req: Request, authorization: str | None = Header(default=None)):
    body = await req.json()
    sources = _retriever(authorization).retrieve(
        body.get("query", ""), int(body.get("k", 8)), body.get("dept"))
    return JSONResponse({"sources": [s.__dict__ for s in sources]})


@app.post("/chat")
async def chat(req: Request, authorization: str | None = Header(default=None)):
    body = await req.json()
    query = body.get("query", "")
    sources = _retriever(authorization).retrieve(
        query, int(body.get("k", 8)), body.get("dept"))

    def sse(event: str, data) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    provider, model = settings.resolve_llm()

    def gen():
        yield sse("citations", rag.citations(sources))
        for delta in rag.stream_answer(
            query, sources, provider=provider, model=model,
            anthropic_key=settings.anthropic_api_key, cohere_key=settings.cohere_api_key,
        ):
            yield sse("token", delta)
        yield sse("done", {})

    return StreamingResponse(gen(), media_type="text/event-stream")
