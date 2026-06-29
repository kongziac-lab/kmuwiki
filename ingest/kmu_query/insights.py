"""Phase 4 활용 기능 코어.

검색 결과(Source)를 기반으로 업무 분류, 흐름도, 일정 초안, 보고서 초안을 만든다.
외부 캘린더/LLM에 바로 쓰기 전에 사람이 검토할 수 있도록 모든 산출물은 draft 성격이다.
"""

from __future__ import annotations

import re
from datetime import date

from .retriever import Source


_DATE_RE = re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def classify_source(source: Source) -> dict:
    text = f"{source.filename or ''} {source.content}"
    category = "일반 행정"
    if "교환학생" in text or "파견" in text or "면접전형" in text or "서류전형" in text:
        category = "교환학생 선발"
    elif "출장" in text:
        category = "국외 출장"
    elif "대표단" in text or "내방" in text:
        category = "대외 교류"

    document_type = "문서"
    if "면접" in text:
        document_type = "면접"
    elif "서류전형" in text:
        document_type = "서류전형"
    elif "시험" in text:
        document_type = "시험"
    elif "출장" in text:
        document_type = "출장"
    elif source.filename and source.filename.lower().startswith("붙임"):
        document_type = "붙임"

    return {
        "document_id": source.document_id,
        "task_category": category,
        "document_type": document_type,
        "year": _year(source),
        "label": source.label(),
    }


def build_mermaid_timeline(sources: list[Source]) -> str:
    ordered = sorted(sources, key=lambda s: (s.doc_date or "9999-12-31", s.doc_no or "", s.filename or ""))
    lines = ["timeline", "    title KMU Wiki 업무흐름"]
    for source in ordered:
        when = source.doc_date or "날짜 미상"
        title = _compact(source.doc_no or source.filename or source.document_id[:8], 60)
        detail = _compact(source.filename or source.content, 80)
        lines.append(f"    {when} : {title} : {detail}")
    return "\n".join(lines)


def build_calendar_drafts(sources: list[Source]) -> list[dict]:
    drafts: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for source in sources:
        for found in _dates_in_text(source.content):
            key = (found.isoformat(), source.document_id)
            if key in seen:
                continue
            seen.add(key)
            drafts.append({
                "status": "draft",
                "date": found.isoformat(),
                "title": _event_title(source),
                "source_document_id": source.document_id,
                "source_label": source.label(),
            })
    return sorted(drafts, key=lambda row: (row["date"], row["title"]))


def draft_report(query: str, sources: list[Source]) -> str:
    if not sources:
        return f"# {query}\n\n근거 문서를 찾지 못했습니다."

    lines = [f"# {query}", "", "## 요약"]
    for idx, source in enumerate(sources, start=1):
        lines.append(f"- [{idx}] {_compact(source.content, 160)}")
    lines.extend(["", "## 출처"])
    for idx, source in enumerate(sources, start=1):
        lines.append(f"- [{idx}] {source.label()}")
    return "\n".join(lines)


def _dates_in_text(text: str) -> list[date]:
    dates: list[date] = []
    for match in _DATE_RE.finditer(text):
        year, month, day = (int(part) for part in match.groups())
        try:
            dates.append(date(year, month, day))
        except ValueError:
            continue
    return dates


def _event_title(source: Source) -> str:
    filename = source.filename or source.doc_no or "일정"
    if "면접전형" in filename or "면접전형" in source.content:
        return "면접전형"
    if "서류전형" in filename or "서류전형" in source.content:
        return "서류전형"
    return _compact(filename, 40)


def _year(source: Source) -> int | None:
    if source.doc_date and len(source.doc_date) >= 4 and source.doc_date[:4].isdigit():
        return int(source.doc_date[:4])
    match = re.search(r"20\d{2}", f"{source.filename or ''} {source.content}")
    return int(match.group(0)) if match else None


def _compact(text: str, limit: int) -> str:
    single = re.sub(r"\s+", " ", text).strip()
    return single if len(single) <= limit else single[:limit - 3] + "..."
