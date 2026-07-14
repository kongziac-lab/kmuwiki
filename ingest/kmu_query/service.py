"""검색·RAG HTTP 서비스 (FastAPI).

  POST /search  → 하이브리드 검색 결과(출처) JSON
  POST /chat    → SSE 스트림(먼저 citations, 이어서 답변 토큰)

RLS: 요청의 Authorization: Bearer <사용자 JWT> 를 먼저 검증한 뒤 해당 사용자
권한으로 Supabase 클라이언트를 구성한다. 인증이 없거나 검증되지 않으면 요청을 거부한다.
"""

from __future__ import annotations

import json
import time
from urllib.parse import quote

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

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
from .visual_assets import load_visual_inputs
from .audit import log_access
from .http_security import (
    authorize_request,
    bounded_text,
    read_json_object,
    require_api_secret as _require_api_secret,
    validate_query_body,
    validate_runtime_security,
    bearer_token,
)

settings = load_settings()
validate_runtime_security(settings)
_embedder = None
_reranker = None
_reranker_checked = False

app = FastAPI(title="KMU Wiki Search/RAG")
# 운영은 validate_runtime_security 에서 명시적 allow-list를 강제한다.
_allowed_origins = [o.strip() for o in settings.allowed_origins.split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["authorization", "content-type", "x-kmuwiki-api-secret"],
    max_age=600,
)


def _authorized_context(authorization: str | None, api_secret: str | None, action: str):
    client = authorize_request(authorization, api_secret, action, settings)
    return client, Retriever(
        client,
        _get_embedder(),
        search_rpc=settings.search_rpc,
        allow_v1_fallback=settings.allow_v1_search_fallback,
    )


def _get_embedder():
    """외부 SDK와 모델 초기화는 실제 검색 요청이 들어올 때까지 지연한다."""
    global _embedder
    if _embedder is None:
        _embedder = make_embedder(
            settings.embed_provider,
            settings.embed_model,
            settings.embed_version,
            output_dimension=settings.embed_output_dimension,
        )
    return _embedder


def _get_reranker():
    global _reranker, _reranker_checked
    if _reranker_checked:
        return _reranker
    _reranker_checked = True
    if settings.rerank_provider != "cohere" or not settings.cohere_api_key:
        return None
    try:
        _reranker = CohereReranker(
            settings.cohere_api_key,
            settings.rerank_model,
            timeout=settings.provider_timeout_seconds,
        )
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


# hybrid_search SQL 이 match_count 를 60 으로 클램프하므로 후보 상한도 60.
_CANDIDATE_HARD_CAP = 60


def _candidate_count(k: int, current_settings=settings) -> int:
    """리랭크 후보 풀 크기. 사용자 결과 상한(k, KMU_API_MAX_K)과 분리해
    rerank_max_candidates 까지 후보를 가져온다(SQL 클램프 60 이내). 리랭커가 넓은
    후보에서 상위 k를 재정렬하도록 해 정확도를 높인다. 리랭크가 없어도 refine/focus
    단계가 더 넓은 후보에서 고른다."""
    return max(k, min(current_settings.rerank_max_candidates, _CANDIDATE_HARD_CAP))


def _parse_year(value) -> int | None:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 2000 <= year <= 2100 else None


def _target_year(body: dict) -> int | None:
    return _parse_year(body.get("target_year") or body.get("year"))


def _source_year(body: dict) -> int | None:
    """Year used to filter retrieval.

    Hermes-style workflows often need separate years: search the latest source
    documents from one year, then draft a target-year artifact. Existing callers
    that only send target_year keep the old behavior because target_year remains
    the final fallback.
    """
    return _parse_year(
        body.get("source_year")
        or body.get("filter_year")
        or body.get("year")
        or body.get("target_year")
    )


def _apply_rerank(query: str, sources, *, top_n: int) -> RerankResult:
    return rerank_sources(
        query,
        sources,
        reranker=_get_reranker(),
        top_n=top_n,
        max_candidates=settings.rerank_max_candidates,
        provider=settings.rerank_provider,
    )


def _retrieve_ranked(
    retriever: Retriever,
    query: str,
    body: dict,
    *,
    default_k: int = 8,
    refine: bool = False,
    focus: bool = False,
):
    k = _bounded_k(body, default=default_k)
    sources = retriever.retrieve(query, _candidate_count(k), body.get("dept"), _source_year(body))
    if refine:
        sources = refine_sources(query, sources, limit=settings.rerank_max_candidates)
    reranked = _apply_rerank(query, sources, top_n=k)
    sources = focus_sources(query, reranked.sources, limit=k) if focus else reranked.sources
    return sources, reranked


def require_api_secret(header_secret: str | None, current_settings=settings) -> None:
    """Compatibility wrapper retained for focused unit tests."""
    _require_api_secret(header_secret, current_settings)


async def _query_request(req: Request) -> tuple[dict, str]:
    body = await read_json_object(req, max_bytes=settings.api_max_body_bytes)
    return body, validate_query_body(body, settings)


@app.post("/search")
async def search(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    body, query = await _query_request(req)

    def work():
        started = time.perf_counter()
        client, retriever = _authorized_context(authorization, api_secret, "search")
        k = _bounded_k(body)
        sources = retriever.retrieve(query, _candidate_count(k), body.get("dept"), _source_year(body))
        sources = refine_sources(query, sources, limit=settings.rerank_max_candidates)
        reranked = _apply_rerank(query, sources, top_n=k)
        sources = focus_sources(query, reranked.sources, limit=k)
        log_access(
            client, action="search", query=query, sources=sources,
            latency_ms=int((time.perf_counter() - started) * 1000),
            rerank_provider=reranked.provider, rerank_applied=reranked.applied,
        )
        return JSONResponse({"sources": [s.__dict__ for s in sources]})

    return await run_in_threadpool(work)


@app.post("/chat")
async def chat(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    body, query = await _query_request(req)

    def prepare():
        started = time.perf_counter()
        client, retriever = _authorized_context(authorization, api_secret, "chat")
        k = _bounded_k(body)
        sources = retriever.retrieve(query, _candidate_count(k), body.get("dept"), _source_year(body))
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
        visual_inputs = []
        provider, _model = settings.resolve_llm()
        if settings.visual_llm_enabled and provider in {"anthropic", "gemini"}:
            visual_inputs = load_visual_inputs(
                focused_sources,
                supabase_url=settings.supabase_url,
                anon_key=settings.supabase_anon_key,
                user_jwt=bearer_token(authorization),
                bucket=settings.visual_asset_bucket,
                max_images=settings.visual_llm_max_images,
                max_total_bytes=settings.visual_llm_max_total_bytes,
                max_image_bytes=settings.visual_llm_max_image_bytes,
                timeout=min(settings.provider_timeout_seconds, 30.0),
            )
        return answer_sources, visual_inputs

    answer_sources, visual_inputs = await run_in_threadpool(prepare)

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
            visual_inputs=visual_inputs,
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
    body, query = await _query_request(req)

    def work():
        started = time.perf_counter()
        client, retriever = _authorized_context(authorization, api_secret, "insights")
        sources, reranked = _retrieve_ranked(retriever, query, body, default_k=12)
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

    return await run_in_threadpool(work)


@app.post("/studio")
async def build_studio(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    """NotebookLM식 산출물(비-LLM): 마인드맵·슬라이드(Marp)·인포그래픽(SVG)·지표.

    한 번의 검색으로 결정론적 산출물을 모두 반환한다. 요약(LLM)은 /studio/summary 로 분리.
    """
    body, query = await _query_request(req)

    def work():
        started = time.perf_counter()
        client, retriever = _authorized_context(authorization, api_secret, "studio")
        sources, reranked = _retrieve_ranked(retriever, query, body, default_k=12)
        log_access(
            client, action="studio", query=query, sources=sources,
            latency_ms=int((time.perf_counter() - started) * 1000),
            rerank_provider=reranked.provider, rerank_applied=reranked.applied,
        )
        return JSONResponse(_studio_payload(query, sources, body))

    return await run_in_threadpool(work)


def _studio_payload(query: str, sources, body: dict) -> dict:
    # 마인드맵 그룹 라벨만 선택적으로 LLM 의미 그룹핑(노드는 결정론적).
    groups = _semantic_groups(query, sources) if body.get("semantic_mindmap", True) else None
    return {
        "metrics": studio.studio_metrics(query, sources),
        "mindmap_mermaid": studio.build_mindmap_mermaid(query, sources, groups=groups),
        "mindmap_grouping": "semantic" if groups else "rule",
        "slides_marp": studio.build_slides_marp(query, sources),
        "infographic_svg": studio.build_infographic_svg(query, sources),
    }


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
    body, query = await _query_request(req)

    def prepare():
        started = time.perf_counter()
        client, retriever = _authorized_context(authorization, api_secret, "studio_summary")
        answer_sources, reranked = _retrieve_ranked(
            retriever, query, body, default_k=12, refine=True, focus=True)
        log_access(
            client, action="studio_summary", query=query, sources=answer_sources,
            latency_ms=int((time.perf_counter() - started) * 1000),
            rerank_provider=reranked.provider, rerank_applied=reranked.applied,
        )
        return answer_sources

    answer_sources = await run_in_threadpool(prepare)

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


@app.post("/studio/stream")
async def studio_stream(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    """Retrieve once, then stream both Studio artifacts and the LLM summary."""
    body, query = await _query_request(req)

    def prepare():
        started = time.perf_counter()
        client, retriever = _authorized_context(authorization, api_secret, "studio_stream")
        answer_sources, reranked = _retrieve_ranked(
            retriever, query, body, default_k=12, refine=True, focus=True)
        payload = _studio_payload(query, answer_sources, body)
        log_access(
            client, action="studio", query=query, sources=answer_sources,
            latency_ms=int((time.perf_counter() - started) * 1000),
            rerank_provider=reranked.provider, rerank_applied=reranked.applied,
        )
        return answer_sources, payload

    answer_sources, payload = await run_in_threadpool(prepare)
    provider, model = settings.resolve_llm()

    def sse(event: str, data) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def gen():
        yield sse("studio", payload)
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
    body, query = await _query_request(req)

    def work():
        started = time.perf_counter()
        known = set(body.get("known_document_ids") or [])
        target_year = body.get("target_year")
        client, retriever = _authorized_context(authorization, api_secret, "hermes")
        sources, reranked = _retrieve_ranked(retriever, query, body, default_k=12)
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

    return await run_in_threadpool(work)


@app.post("/reports")
async def wiki_report(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    body, query = await _query_request(req)

    def work():
        started = time.perf_counter()
        client, retriever = _authorized_context(authorization, api_secret, "reports")
        sources, reranked = _retrieve_ranked(retriever, query, body, default_k=12)
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

    return await run_in_threadpool(work)


@app.post("/hermes/docx")
async def hermes_docx(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    await run_in_threadpool(
        authorize_request, authorization, api_secret, "export_docx", settings)
    body = await read_json_object(req, max_bytes=settings.api_max_export_body_bytes)

    def work():
        raw_title = bounded_text(
            body.get("docx_filename") or body.get("title") or "draft",
            field="title", max_chars=300)
        content = bounded_text(body.get("body"), field="body", max_chars=500_000)
        source_label = bounded_text(body.get("source_label"), field="source_label", max_chars=2_000)
        plan = body.get("approval_form_plan") or []
        if not isinstance(plan, list) or len(plan) > 100 or any(not isinstance(v, str) for v in plan):
            raise HTTPException(status_code=400, detail="invalid approval_form_plan")
        filename = docx_export.safe_docx_filename(raw_title)
        data = docx_export.build_approval_docx(
            title=filename, body=content, source_label=source_label, approval_form_plan=plan)
        quoted = quote(filename)
        return Response(
            data,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"content-disposition": f"attachment; filename*=UTF-8''{quoted}"},
        )

    return await run_in_threadpool(work)


@app.post("/hermes/hwpx")
async def hermes_hwpx(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    await run_in_threadpool(
        authorize_request, authorization, api_secret, "export_hwpx", settings)
    body = await read_json_object(req, max_bytes=settings.api_max_export_body_bytes)

    def work():
        raw_title = bounded_text(
            body.get("hwpx_filename") or body.get("docx_filename") or body.get("title") or "draft",
            field="title", max_chars=300)
        content = bounded_text(body.get("body"), field="body", max_chars=500_000)
        source_label = bounded_text(body.get("source_label"), field="source_label", max_chars=2_000)
        plan = body.get("approval_form_plan") or []
        if not isinstance(plan, list) or len(plan) > 100 or any(not isinstance(v, str) for v in plan):
            raise HTTPException(status_code=400, detail="invalid approval_form_plan")
        filename = hwpx_export.safe_hwpx_filename(raw_title)
        data = hwpx_export.build_approval_hwpx(
            title=filename, body=content, source_label=source_label, approval_form_plan=plan)
        quoted = quote(filename)
        return Response(
            data,
            media_type=hwpx_export.HWPX_MIME,
            headers={"content-disposition": f"attachment; filename*=UTF-8''{quoted}"},
        )

    return await run_in_threadpool(work)


@app.post("/reports/template-hwpx")
async def report_template_hwpx(
    req: Request,
    authorization: str | None = Header(default=None),
    api_secret: str | None = Header(default=None, alias="x-kmuwiki-api-secret"),
):
    await run_in_threadpool(
        authorize_request, authorization, api_secret, "export_template_hwpx", settings)
    body = await read_json_object(req, max_bytes=settings.api_max_export_body_bytes)

    def work():
        title = bounded_text(body.get("title") or "wiki-report", field="title", max_chars=300)
        content = bounded_text(body.get("body"), field="body", max_chars=500_000)
        template_base64 = bounded_text(
            body.get("template_base64"), field="template_base64", max_chars=16 * 1024 * 1024)
        filename = hwpx_export.safe_hwpx_filename(title)
        try:
            data = hwpx_export.fill_template_hwpx_from_base64(
                template_base64=template_base64, title=filename, body=content)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"invalid hwpx template: {exc}") from exc
        quoted = quote(filename)
        return Response(
            data,
            media_type=hwpx_export.HWPX_MIME,
            headers={"content-disposition": f"attachment; filename*=UTF-8''{quoted}"},
        )

    return await run_in_threadpool(work)
