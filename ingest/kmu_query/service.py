"""검색·RAG HTTP 서비스 (FastAPI).

  POST /search  → 하이브리드 검색 결과(출처) JSON
  POST /chat    → SSE 스트림(먼저 citations, 이어서 답변 토큰)

RLS: 요청의 Authorization: Bearer <사용자 JWT> 로 Supabase 클라이언트를 인증한다.
헤더가 없으면 anon 권한 → 정책상 아무 문서도 안 보인다(deny-by-default).
"""

from __future__ import annotations

import hmac
import json
from urllib.parse import quote

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from kmu_ingest.config import load_settings
from kmu_ingest.embedding import make_embedder

from . import rag
from . import insights
from . import hermes
from . import docx_export
from . import hwpx_export
from .retriever import Retriever
from .source_quality import refine_sources
from .verification import focus_sources
from .audit import log_access

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


def _client_and_retriever(authorization: str | None):
    client = _client(authorization)
    return client, Retriever(client, _embedder)


def require_api_secret(header_secret: str | None, current_settings=settings) -> None:
    """공개 API 직접 호출 차단. 로컬 개발 편의를 위해 미설정이면 비활성."""
    expected = current_settings.api_shared_secret
    if not expected:
        return
    if not header_secret or not hmac.compare_digest(header_secret, expected):
        raise HTTPException(status_code=401, detail="invalid api secret")


@app.post("/search")
async def search(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    require_api_secret(api_secret)
    body = await req.json()
    client, retriever = _client_and_retriever(authorization)
    query = body.get("query", "")
    k = int(body.get("k", 8))
    sources = retriever.retrieve(query, max(k * 3, k), body.get("dept"))
    sources = refine_sources(query, sources, limit=k)
    log_access(client, action="search", query=query, sources=sources)
    return JSONResponse({"sources": [s.__dict__ for s in sources]})


@app.post("/chat")
async def chat(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    require_api_secret(api_secret)
    body = await req.json()
    query = body.get("query", "")
    client, retriever = _client_and_retriever(authorization)
    k = int(body.get("k", 8))
    sources = retriever.retrieve(query, max(k * 3, k), body.get("dept"))
    sources = refine_sources(query, sources, limit=k)
    answer_sources = retriever.expand_zip_context(focus_sources(query, sources))
    log_access(client, action="chat", query=query, sources=sources)

    def sse(event: str, data) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    provider, model = settings.resolve_llm()

    def gen():
        yield sse("citations", rag.citations(answer_sources))
        for delta in rag.stream_answer(
            query, answer_sources, provider=provider, model=model,
            anthropic_key=settings.anthropic_api_key, cohere_key=settings.cohere_api_key,
            nous_key=settings.nous_api_key, nous_base_url=settings.nous_base_url,
            gemini_key=settings.gemini_api_key,
            gemini_use_vertex=settings.gemini_use_vertex,
            gemini_project=settings.gemini_project,
            gemini_location=settings.gemini_location,
        ):
            yield sse("token", delta)
        yield sse("done", {})

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/insights")
async def build_insights(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    require_api_secret(api_secret)
    body = await req.json()
    query = body.get("query", "")
    client, retriever = _client_and_retriever(authorization)
    sources = retriever.retrieve(
        query, int(body.get("k", 12)), body.get("dept"))
    log_access(client, action="insights", query=query, sources=sources)
    report_draft = insights.draft_report(query, sources)
    return JSONResponse({
        "work_items": insights.group_work_items(sources),
        "classifications": [insights.classify_source(s) for s in sources],
        "workflow_mermaid": insights.build_mermaid_timeline(sources),
        "calendar_drafts": insights.build_calendar_drafts(sources),
        "report_draft": report_draft,
        "report_workflow": insights.build_report_workflow(query, report_draft),
    })


@app.post("/hermes")
async def hermes_report(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    require_api_secret(api_secret)
    body = await req.json()
    query = body.get("query", "")
    known = set(body.get("known_document_ids") or [])
    target_year = body.get("target_year")
    client, retriever = _client_and_retriever(authorization)
    sources = retriever.retrieve(
        query, int(body.get("k", 12)), body.get("dept"))
    log_access(client, action="hermes", query=query, sources=sources)
    drafts = []
    if isinstance(target_year, int):
        drafts = hermes.draft_next_year_documents(sources, target_year, limit=3)
    return JSONResponse({
        "update_report": hermes.update_report(query, sources, known_document_ids=known),
        "recurring_work": hermes.detect_recurring_work(sources),
        "drafts": drafts,
    })


@app.post("/hermes/docx")
async def hermes_docx(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    require_api_secret(api_secret)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing authorization")
    body = await req.json()
    filename = docx_export.safe_docx_filename(body.get("docx_filename") or body.get("title") or "draft")
    data = docx_export.build_approval_docx(
        title=filename,
        body=body.get("body") or "",
        source_label=body.get("source_label") or "",
        approval_form_plan=body.get("approval_form_plan") or [],
    )
    quoted = quote(filename)
    return Response(
        data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"content-disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )


@app.post("/hermes/hwpx")
async def hermes_hwpx(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    require_api_secret(api_secret)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing authorization")
    body = await req.json()
    filename = hwpx_export.safe_hwpx_filename(
        body.get("hwpx_filename") or body.get("docx_filename") or body.get("title") or "draft"
    )
    data = hwpx_export.build_approval_hwpx(
        title=filename,
        body=body.get("body") or "",
        source_label=body.get("source_label") or "",
        approval_form_plan=body.get("approval_form_plan") or [],
    )
    quoted = quote(filename)
    return Response(
        data,
        media_type=hwpx_export.HWPX_MIME,
        headers={"content-disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )
