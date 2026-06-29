"""Phase 5 Hermes automation core.

여기서는 외부 LLM tool-use 없이도 검증 가능한 반복업무 탐지와 안전한 초안 생성을 제공한다.
생성물은 항상 draft 상태이며, 실제 개인정보는 자리표시자로 치환한다.
"""

from __future__ import annotations

import re

from .insights import classify_source
from .retriever import Source


_YEAR_RE = re.compile(r"20\d{2}")
_TITLE_YEAR_RE = re.compile(r"20\d{2}(년도|학년도)")
_PHONE_RE = re.compile(r"\b0\d{1,2}-\d{3,4}-\d{4}\b")
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_RRN_RE = re.compile(r"\b\d{6}-[1-4]\d{6}\b")


def detect_recurring_work(sources: list[Source]) -> list[dict]:
    grouped: dict[str, list[Source]] = {}
    for source in sources:
        title = _template_title(source.filename or source.label())
        grouped.setdefault(title, []).append(source)

    patterns: list[dict] = []
    for template, items in grouped.items():
        years = sorted({year for item in items if (year := _year(item)) is not None})
        if len(years) < 2:
            continue
        patterns.append({
            "template_title": template,
            "years": years,
            "document_ids": [item.document_id for item in sorted(items, key=lambda s: _year(s) or 0)],
            "task_category": classify_source(items[-1])["task_category"],
        })
    return sorted(patterns, key=lambda p: (p["template_title"], p["years"]))


def draft_next_year_document(source: Source, target_year: int) -> dict:
    current_year = _year(source)
    title = source.filename or source.label()
    body = source.content
    if current_year is not None:
        title = title.replace(str(current_year), str(target_year))
        body = body.replace(str(current_year), str(target_year))
    hwpx_filename = _hwpx_filename(title)
    return {
        "status": "draft",
        "title": _sanitize_pii(hwpx_filename),
        "export_format": "hwpx",
        "hwpx_filename": _sanitize_pii(hwpx_filename),
        "approval_form_plan": [
            "전자결재 PDF의 기본 결재문 영역(제목, 시행부서, 시행일, 본문, 붙임)을 HWPX 섹션으로 재구성",
            "원문 결재선/담당자/전화/이메일은 마스킹 자리표시자를 유지",
            "본문은 원문 줄바꿈과 붙임 목록을 우선 보존하고, 누락 필드는 검토 필요 표시",
        ],
        "body": _sanitize_pii(body),
        "source_document_id": source.document_id,
        "source_label": source.label(),
    }


def draft_next_year_documents(sources: list[Source], target_year: int, limit: int = 3) -> list[dict]:
    drafts: list[dict] = []
    seen_templates: set[str] = set()
    ordered = sorted(
        sources,
        key=lambda source: (_year(source) or 0, source.doc_date or "", source.score),
        reverse=True,
    )
    for source in ordered:
        key = _template_title(source.filename or source.label())
        if key in seen_templates:
            continue
        seen_templates.add(key)
        drafts.append(draft_next_year_document(source, target_year))
        if len(drafts) >= limit:
            break
    return drafts


def update_report(query: str, sources: list[Source], known_document_ids: set[str] | None = None) -> dict:
    known = known_document_ids or set()
    new_ids = [source.document_id for source in sources if source.document_id not in known]
    classifications = [classify_source(source) for source in sources]
    return {
        "summary": f"{query}: 신규 문서 {len(new_ids)}건, 검색 문서 {len(sources)}건",
        "new_documents": new_ids,
        "classifications": classifications,
        "recurring_work": detect_recurring_work(sources),
    }


def _template_title(title: str) -> str:
    title = re.sub(r"\.[^.]+$", "", title)
    title = _TITLE_YEAR_RE.sub(r"{year}\1", title)
    title = _YEAR_RE.sub("{year}", title)
    return re.sub(r"\s+", " ", title).strip()


def _hwpx_filename(title: str) -> str:
    base = re.sub(r"\.[^.]+$", "", title).strip()
    return f"{base}.hwpx"


def _year(source: Source) -> int | None:
    text = f"{source.doc_date or ''} {source.filename or ''} {source.content}"
    match = _YEAR_RE.search(text)
    return int(match.group(0)) if match else None


def _sanitize_pii(text: str) -> str:
    text = _RRN_RE.sub("{주민등록번호}", text)
    text = _PHONE_RE.sub("{전화번호}", text)
    text = _EMAIL_RE.sub("{이메일}", text)
    return text
