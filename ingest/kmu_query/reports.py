"""Wiki report generation core.

This module turns retrieved Wiki documents into Korean public-document style
report drafts. It intentionally keeps the first version deterministic so the
workflow can be tested without an external LLM.
"""

from __future__ import annotations

from datetime import date
import re

from . import insights
from .retriever import Source


REPORT_TYPES = {
    "result": "결과 보고",
    "plan": "계획 보고",
    "cooperation": "협조 요청",
    "briefing": "내부 보고",
}


def build_wiki_report(
    query: str,
    sources: list[Source],
    *,
    report_type: str = "result",
    target_year: int | None = None,
    recipient: str = "[수신처]",
    sender: str = "[발신기관명]",
    dept: str | None = None,
) -> dict:
    """Build a report draft using wiki-report-writer style orchestration."""

    normalized_type = report_type if report_type in REPORT_TYPES else "result"
    report_label = REPORT_TYPES[normalized_type]
    title = _report_title(query, report_label, target_year)
    work_items = insights.group_work_items(sources)
    classifications = [insights.classify_source(source) for source in sources]
    body = _compose_body(
        title=title,
        query=query,
        sources=sources,
        work_items=work_items,
        report_label=report_label,
        recipient=recipient or "[수신처]",
        sender=sender or "[발신기관명]",
        dept=dept,
    )

    return {
        "status": "draft",
        "engine": "wiki-report-writer",
        "skill_chain": ["wiki-report-writer", "korean-gov-doc", "hwpx-autofill-conversion"],
        "report_type": normalized_type,
        "report_label": report_label,
        "title": title,
        "sender": sender or "[발신기관명]",
        "recipient": recipient or "[수신처]",
        "target_year": target_year,
        "query": query,
        "body": body,
        "source_count": len(sources),
        "sources": [_source_row(source, index) for index, source in enumerate(sources, start=1)],
        "work_items": work_items,
        "classifications": classifications,
        "quality_checks": [
            "korean-gov-doc 번호 체계 적용",
            "개조식 문체(~함, ~임, ~됨) 적용",
            "날짜 표기 점검",
            "붙임 및 끝 처리 포함",
            "HWPX 출력 시 hwpx-autofill-conversion 패키징 규칙 사용",
        ],
    }


def _compose_body(
    *,
    title: str,
    query: str,
    sources: list[Source],
    work_items: list[dict],
    report_label: str,
    recipient: str,
    sender: str,
    dept: str | None,
) -> str:
    today = _gov_date(date.today())
    period = _period(sources)
    source_lines = [_source_bullet(source, index) for index, source in enumerate(sources[:8], start=1)]
    work_lines = [_work_bullet(work, index) for index, work in enumerate(work_items[:6], start=1)]
    dept_line = f"  다. 담당 부서: {dept}" if dept else "  다. 담당 부서: [담당 부서]"

    if not sources:
        source_lines = ["  가. 검색된 근거 문서 없음"]
        work_lines = ["  가. Wiki DB에서 관련 문서를 추가 확인할 것"]

    lines = [
        sender,
        "",
        f"수 신:  {recipient}",
        f"제 목:  {title}",
        "",
        f"1. {query}와(과) 관련하여 Wiki DB 근거 문서를 바탕으로 {report_label} 초안을 작성함.",
        "",
        "2. 보고 개요",
        f"  가. 작성 기준일: {today}",
        f"  나. 대상 기간: {period}",
        dept_line,
        "",
        "3. 주요 내용",
        *work_lines,
        "",
        "4. 근거 문서",
        *source_lines,
        "",
        "5. 검토 및 후속 조치",
        "  가. 본 초안은 Wiki DB 검색 결과를 기준으로 작성되었으므로 최종 제출 전 원문 확인이 필요함.",
        "  나. 개인정보, 연락처, 계좌번호 등 민감정보 포함 여부를 검토할 것.",
        "  다. HWPX 양식으로 제출하는 경우 원본 양식 구조를 보존하여 본문 텍스트만 반영할 것.",
        "",
        "붙임  1. Wiki DB 근거 문서 목록 1부.  끝.",
        "",
        f"                              {sender}장",
    ]
    return "\n".join(lines)


def _report_title(query: str, report_label: str, target_year: int | None) -> str:
    compact_query = _compact(query, 42)
    if target_year:
        return f"{target_year}년 {compact_query} {report_label}"
    return f"{compact_query} {report_label}"


def _work_bullet(work: dict, index: int) -> str:
    marker = _korean_marker(index)
    terms = ", ".join(work.get("terms") or []) or "-"
    types = ", ".join(work.get("document_types") or []) or "문서"
    count = int(work.get("document_count") or 0)
    title = work.get("work_title") or "관련 업무"
    period = _range(work.get("start_date"), work.get("end_date"))
    return f"  {marker}. {title}: {terms}, {types} {count}건 확인됨(기간: {period})"


def _source_bullet(source: Source, index: int) -> str:
    marker = _korean_marker(index)
    date_text = _gov_date_from_iso(source.doc_date) if source.doc_date else "날짜 미상"
    filename = source.filename or "파일명 미상"
    doc_no = source.doc_no or "문서번호 미상"
    return f"  {marker}. {date_text} {doc_no} {filename}"


def _source_row(source: Source, index: int) -> dict:
    return {
        "index": index,
        "document_id": source.document_id,
        "label": source.label(),
        "filename": source.filename,
        "doc_no": source.doc_no,
        "doc_date": source.doc_date,
        "dept": source.dept,
        "score": source.score,
    }


def _period(sources: list[Source]) -> str:
    dates = sorted(source.doc_date for source in sources if source.doc_date)
    if not dates:
        return "[보고 기간]"
    if dates[0] == dates[-1]:
        return _gov_date_from_iso(dates[0])
    return f"{_gov_date_from_iso(dates[0])} ~ {_gov_date_from_iso(dates[-1])}"


def _range(start: str | None, end: str | None) -> str:
    if not start and not end:
        return "-"
    if not end or start == end:
        return _gov_date_from_iso(start or end or "")
    return f"{_gov_date_from_iso(start)} ~ {_gov_date_from_iso(end)}"


def _gov_date(value: date) -> str:
    return f"{value.year}. {value.month}. {value.day}."


def _gov_date_from_iso(value: str) -> str:
    parts = value.split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        return f"{int(parts[0])}. {int(parts[1])}. {int(parts[2])}."
    return value


def _korean_marker(index: int) -> str:
    markers = ["가", "나", "다", "라", "마", "바", "사", "아", "자", "차"]
    return markers[index - 1] if 1 <= index <= len(markers) else f"{index})"


def _compact(text: str, limit: int) -> str:
    single = re.sub(r"\s+", " ", text).strip() or "Wiki 보고서"
    return single if len(single) <= limit else single[:limit - 1].rstrip() + "…"
