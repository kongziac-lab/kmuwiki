"""검색·RAG HTTP 서비스 (FastAPI).

  POST /search  → 하이브리드 검색 결과(출처) JSON
  POST /chat    → SSE 스트림(먼저 citations, 이어서 답변 토큰)

RLS: 요청의 Authorization: Bearer <사용자 JWT> 로 Supabase 클라이언트를 인증한다.
헤더가 없으면 anon 권한 → 정책상 아무 문서도 안 보인다(deny-by-default).
"""

from __future__ import annotations

import hmac
import json
import time
from urllib.parse import quote

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from kmu_ingest.config import load_settings
from kmu_ingest.embedding import make_embedder

from . import rag
from . import insights
from . import studio
from . import hermes
from . import reports
from . import docx_export
from . import hwpx_export
from .retriever import Retriever
from .rerank import CohereReranker, RerankResult, rerank_sources
from .source_quality import refine_sources
from .verification import focus_sources, needs_full_zip_context
from .audit import log_access

settings = load_settings()
_embedder = make_embedder(settings.embed_provider, settings.embed_model, settings.embed_version)
_reranker = None
_reranker_checked = False

app = FastAPI(title="KMU Wiki Search/RAG")
# CORS 허용 출처: KMU_ALLOWED_ORIGINS(콤마 구분)로 제한. 미설정 시 "*"(개발) 폴백.
_allowed_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware, allow_origins=_allowed_origins, allow_methods=["*"], allow_headers=["*"],
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


def _get_reranker():
    global _reranker, _reranker_checked
    if _reranker_checked:
        return _reranker
    _reranker_checked = True
    if settings.rerank_provider != "cohere" or not settings.cohere_api_key:
        return None
    try:
        _reranker = CohereReranker(settings.cohere_api_key, settings.rerank_model)
    except Exception:
        _reranker = None
    return _reranker


def _bounded_k(body: dict, *, default: int | None = None) -> int:
    fallback = default or settings.api_default_k
    try:
        requested = int(body.get("k", fallback))
    except (TypeError, ValueError):
        requested = fallback
    return max(1, min(requested, settings.api_max_k))


def _target_year(body: dict) -> int | None:
    value = body.get("target_year") or body.get("year")
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 2000 <= year <= 2100 else None


def _apply_rerank(query: str, sources, *, top_n: int) -> RerankResult:
    return rerank_sources(
        query,
        sources,
        reranker=_get_reranker(),
        top_n=top_n,
        max_candidates=settings.rerank_max_candidates,
        provider=settings.rerank_provider,
    )


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
    started = time.perf_counter()
    require_api_secret(api_secret)
    body = await req.json()
    client, retriever = _client_and_retriever(authorization)
    query = body.get("query", "")
    k = _bounded_k(body)
    sources = retriever.retrieve(query, min(k * 3, settings.api_max_k), body.get("dept"), _target_year(body))
    sources = refine_sources(query, sources, limit=settings.rerank_max_candidates)
    reranked = _apply_rerank(query, sources, top_n=k)
    sources = focus_sources(query, reranked.sources, limit=k)
    log_access(
        client, action="search", query=query, sources=sources,
        latency_ms=int((time.perf_counter() - started) * 1000),
        rerank_provider=reranked.provider, rerank_applied=reranked.applied,
    )
    return JSONResponse({"sources": [s.__dict__ for s in sources]})


@app.post("/chat")
async def chat(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    started = time.perf_counter()
    require_api_secret(api_secret)
    body = await req.json()
    query = body.get("query", "")
    client, retriever = _client_and_retriever(authorization)
    k = _bounded_k(body)
    sources = retriever.retrieve(query, min(k * 3, settings.api_max_k), body.get("dept"), _target_year(body))
    sources = refine_sources(query, sources, limit=settings.rerank_max_candidates)
    reranked = _apply_rerank(query, sources, top_n=k)
    # 검증 민감 질문은 ZIP 전체를 투입해 루프 없이 전수 대조한다(준-검증모드).
    zip_limit = None if needs_full_zip_context(query) else 12
    focused_sources = focus_sources(query, reranked.sources, limit=k)
    answer_sources = retriever.expand_zip_context(focused_sources, limit_per_zip=zip_limit)
    log_access(
        client, action="chat", query=query, sources=focused_sources,
        latency_ms=int((time.perf_counter() - started) * 1000),
        rerank_provider=reranked.provider, rerank_applied=reranked.applied,
    )

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
    started = time.perf_counter()
    require_api_secret(api_secret)
    body = await req.json()
    query = body.get("query", "")
    client, retriever = _client_and_retriever(authorization)
    k = _bounded_k(body, default=12)
    sources = retriever.retrieve(query, k, body.get("dept"), _target_year(body))
    reranked = _apply_rerank(query, sources, top_n=k)
    sources = reranked.sources
    log_access(
        client, action="insights", query=query, sources=sources,
        latency_ms=int((time.perf_counter() - started) * 1000),
        rerank_provider=reranked.provider, rerank_applied=reranked.applied,
    )
    report_draft = insights.draft_report(query, sources)
    return JSONResponse({
        "work_items": insights.group_work_items(sources),
        "classifications": [insights.classify_source(s) for s in sources],
        "workflow_mermaid": insights.build_mermaid_timeline(sources),
        "calendar_drafts": insights.build_calendar_drafts(sources),
        "report_draft": report_draft,
        "report_workflow": insights.build_report_workflow(query, report_draft),
    })


@app.post("/studio")
async def build_studio(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    """NotebookLM식 산출물(비-LLM): 마인드맵·슬라이드(Marp)·인포그래픽(SVG)·지표.

    한 번의 검색으로 결정론적 산출물을 모두 반환한다. 요약(LLM)은 /studio/summary 로 분리.
    """
    started = time.perf_counter()
    require_api_secret(api_secret)
    body = await req.json()
    query = body.get("query", "")
    client, retriever = _client_and_retriever(authorization)
    k = _bounded_k(body, default=12)
    sources = retriever.retrieve(query, k, body.get("dept"), _target_year(body))
    reranked = _apply_rerank(query, sources, top_n=k)
    sources = reranked.sources
    log_access(
        client, action="studio", query=query, sources=sources,
        latency_ms=int((time.perf_counter() - started) * 1000),
        rerank_provider=reranked.provider, rerank_applied=reranked.applied,
    )
    # 마인드맵 그룹 라벨만 선택적으로 LLM 의미 그룹핑(노드는 결정론적). 기본 활성,
    # semantic_mindmap=false 로 끌 수 있고 실패 시 규칙기반으로 자동 폴백한다.
    groups = None
    if body.get("semantic_mindmap", True):
        groups = _semantic_groups(query, sources)
    return JSONResponse({
        "metrics": studio.studio_metrics(query, sources),
        "mindmap_mermaid": studio.build_mindmap_mermaid(query, sources, groups=groups),
        "mindmap_grouping": "semantic" if groups else "rule",
        "slides_marp": studio.build_slides_marp(query, sources),
        "infographic_svg": studio.build_infographic_svg(query, sources),
    })


def _semantic_groups(query: str, sources):
    """마인드맵 의미 그룹핑(work_id → 라벨). 실패·미설정 시 None 반환(규칙기반 폴백)."""
    provider, model = settings.resolve_llm()

    def generate(system: str, prompt: str) -> str:
        return rag.generate_text(
            provider=provider, model=model, system=system, prompt=prompt, max_tokens=512,
            anthropic_key=settings.anthropic_api_key, cohere_key=settings.cohere_api_key,
            nous_key=settings.nous_api_key, nous_base_url=settings.nous_base_url,
            gemini_key=settings.gemini_api_key,
            gemini_use_vertex=settings.gemini_use_vertex,
            gemini_project=settings.gemini_project,
            gemini_location=settings.gemini_location,
        )

    try:
        return studio.cluster_work_items(query, sources, generate)
    except Exception:
        return None


@app.post("/studio/summary")
async def studio_summary(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    """NotebookLM식 소스 묶음 요약(SSE). /chat 과 같은 마스킹·제공자 선택을 재사용한다."""
    started = time.perf_counter()
    require_api_secret(api_secret)
    body = await req.json()
    query = body.get("query", "")
    client, retriever = _client_and_retriever(authorization)
    k = _bounded_k(body, default=12)
    sources = retriever.retrieve(query, min(k * 3, settings.api_max_k), body.get("dept"), _target_year(body))
    sources = refine_sources(query, sources, limit=settings.rerank_max_candidates)
    reranked = _apply_rerank(query, sources, top_n=k)
    answer_sources = focus_sources(query, reranked.sources, limit=k)
    log_access(
        client, action="studio_summary", query=query, sources=answer_sources,
        latency_ms=int((time.perf_counter() - started) * 1000),
        rerank_provider=reranked.provider, rerank_applied=reranked.applied,
    )

    def sse(event: str, data) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    provider, model = settings.resolve_llm()

    def gen():
        yield sse("citations", rag.citations(answer_sources))
        for delta in rag.stream_summary(
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


@app.post("/hermes")
async def hermes_report(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    started = time.perf_counter()
    require_api_secret(api_secret)
    body = await req.json()
    query = body.get("query", "")
    known = set(body.get("known_document_ids") or [])
    target_year = body.get("target_year")
    client, retriever = _client_and_retriever(authorization)
    k = _bounded_k(body, default=12)
    sources = retriever.retrieve(query, k, body.get("dept"), _target_year(body))
    reranked = _apply_rerank(query, sources, top_n=k)
    sources = reranked.sources
    log_access(
        client, action="hermes", query=query, sources=sources,
        latency_ms=int((time.perf_counter() - started) * 1000),
        rerank_provider=reranked.provider, rerank_applied=reranked.applied,
    )
    drafts = []
    if isinstance(target_year, int):
        drafts = hermes.draft_next_year_documents(sources, target_year, limit=3)
    return JSONResponse({
        "update_report": hermes.update_report(query, sources, known_document_ids=known),
        "recurring_work": hermes.detect_recurring_work(sources),
        "drafts": drafts,
    })


@app.post("/reports")
async def wiki_report(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    started = time.perf_counter()
    require_api_secret(api_secret)
    body = await req.json()
    query = body.get("query", "")
    client, retriever = _client_and_retriever(authorization)
    k = _bounded_k(body, default=12)
    sources = retriever.retrieve(
        query,
        k,
        body.get("dept"),
        _target_year(body),
    )
    reranked = _apply_rerank(query, sources, top_n=k)
    sources = reranked.sources
    log_access(
        client, action="reports", query=query, sources=sources,
        latency_ms=int((time.perf_counter() - started) * 1000),
        rerank_provider=reranked.provider, rerank_applied=reranked.applied,
    )
    target_year = body.get("target_year")
    if not isinstance(target_year, int):
        target_year = None
    return JSONResponse(reports.build_wiki_report(
        query,
        sources,
        report_type=body.get("report_type") or "result",
        target_year=target_year,
        recipient=body.get("recipient") or "[수신처]",
        sender=body.get("sender") or "[발신기관명]",
        dept=body.get("dept"),
    ))


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


@app.post("/reports/template-hwpx")
async def report_template_hwpx(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    require_api_secret(api_secret)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing authorization")
    body = await req.json()
    filename = hwpx_export.safe_hwpx_filename(body.get("title") or "wiki-report")
    try:
        data = hwpx_export.fill_template_hwpx_from_base64(
            template_base64=body.get("template_base64") or "",
            title=filename,
            body=body.get("body") or "",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid hwpx template: {exc}") from exc
    quoted = quote(filename)
    return Response(
        data,
        media_type=hwpx_export.HWPX_MIME,
        headers={"content-disposition": f"attachment; filename*=UTF-8''{quoted}"},
    )
