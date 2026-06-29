"""Phase 4 활용 기능 코어.

검색 결과(Source)를 기반으로 업무 분류, 흐름도, 일정 초안, 보고서 초안을 만든다.
외부 캘린더/LLM에 바로 쓰기 전에 사람이 검토할 수 있도록 모든 산출물은 draft 성격이다.
"""

from __future__ import annotations

import re
from datetime import date

from .retriever import Source


_DATE_RE = re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
_EXT_RE = re.compile(r"\.(pdf|mht|mhtml|hwp|hwpx|doc|docx|xls|xlsx|txt)$", re.IGNORECASE)
_ATTACH_PREFIX_RE = re.compile(r"^(붙임|첨부)\s*\d+\s*[.)]?\s*")
_SPACE_RE = re.compile(r"\s+")


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
        "work_id": _work_id(source),
        "work_title": _work_title(source),
        "label": source.label(),
    }


def group_work_items(sources: list[Source]) -> list[dict]:
    grouped: dict[str, dict] = {}
    seen_documents: dict[str, set[str]] = {}
    for source in sources:
        classification = classify_source(source)
        work_id = classification["work_id"]
        row = grouped.setdefault(work_id, {
            "work_id": work_id,
            "work_title": classification["work_title"],
            "task_category": classification["task_category"],
            "year": classification["year"],
            "start_date": source.doc_date,
            "end_date": source.doc_date,
            "document_count": 0,
            "document_types": [],
            "documents": [],
        })
        seen = seen_documents.setdefault(work_id, set())
        if source.document_id in seen:
            continue
        seen.add(source.document_id)
        row["document_count"] += 1
        if classification["document_type"] not in row["document_types"]:
            row["document_types"].append(classification["document_type"])
        if source.doc_date and (row["start_date"] is None or source.doc_date < row["start_date"]):
            row["start_date"] = source.doc_date
        if source.doc_date and (row["end_date"] is None or source.doc_date > row["end_date"]):
            row["end_date"] = source.doc_date
        row["documents"].append({
            "document_id": source.document_id,
            "document_type": classification["document_type"],
            "label": source.label(),
            "doc_no": source.doc_no,
            "doc_date": source.doc_date,
            "filename": source.filename,
        })

    for row in grouped.values():
        row["document_types"] = sorted(row["document_types"], key=_document_type_sort_key)
        row["documents"] = sorted(row["documents"], key=lambda d: (d["doc_date"] or "9999-12-31", d["doc_no"] or "", d["filename"] or ""))
    return sorted(grouped.values(), key=lambda r: (r["start_date"] or "9999-12-31", r["work_title"]))


def build_mermaid_timeline(sources: list[Source]) -> str:
    ordered = _timeline_events(sources)
    lines = ["timeline", "    title KMU Wiki 업무흐름"]
    for event in ordered:
        when = event["date"] or "날짜 미상"
        title = _compact(event["doc_no"] or event["work_title"], 60)
        count = event["document_count"]
        count_suffix = f" ({count}개 문서)" if count > 1 else ""
        detail = _compact(f"{event['work_title']} - {event['event_title']}{count_suffix}", 90)
        lines.append(f"    {when} : {title} : {detail}")
    return "\n".join(lines)


def build_calendar_drafts(sources: list[Source]) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for source in sources:
        found_dates = _dates_in_text(source.content)
        if not found_dates and source.doc_date and _can_use_doc_date_as_event(source):
            try:
                found_dates = [date.fromisoformat(source.doc_date)]
            except ValueError:
                found_dates = []
        for found in found_dates:
            title = _event_title(source)
            key = (found.isoformat(), _event_key(title))
            draft = grouped.setdefault(key, {
                "status": "draft",
                "date": found.isoformat(),
                "title": title,
                "source_document_id": source.document_id,
                "source_label": source.label(),
                "source_document_ids": [],
                "source_labels": [],
            })
            if source.document_id not in draft["source_document_ids"]:
                draft["source_document_ids"].append(source.document_id)
                draft["source_labels"].append(source.label())
    return sorted(grouped.values(), key=lambda row: (row["date"], row["title"]))


def draft_report(query: str, sources: list[Source]) -> str:
    if not sources:
        return f"# {query}\n\n근거 문서를 찾지 못했습니다."

    lines = [f"# {query}", "", "## 요약"]
    for idx, work in enumerate(group_work_items(sources), start=1):
        types = ", ".join(work["document_types"])
        lines.append(f"- [{idx}] {work['work_title']} ({types}, {work['document_count']}개 문서)")
    lines.extend(["", "## 출처"])
    for idx, source in enumerate(sources, start=1):
        lines.append(f"- [{idx}] {source.label()}")
    return "\n".join(lines)


def build_report_workflow(query: str, report_draft: str) -> dict:
    return {
        "source_format": "markdown",
        "source_title": query,
        "steps": [
            "MD 초안을 근거 문서와 출처가 포함된 재료 파일로 고정",
            "양식 선택: 기안보고, 결과보고, 일정계획, 회의자료, 홈페이지 공고문",
            "선택한 보고서 스킬/양식에 맞춰 목차와 문체를 재구성",
            "개인정보 자리표시자와 출처 목록을 보존한 채 DOCX로 내보내기",
            "사람 검토 후 전자결재 또는 공유 문서에 붙여넣기",
        ],
        "templates": [
            {"name": "기안보고", "best_for": "결재 상신, 계획 수립, 변경 시행"},
            {"name": "결과보고", "best_for": "서류전형/면접/선발 결과 정리"},
            {"name": "일정계획", "best_for": "연간 일정, 모집 일정, 준비 체크리스트"},
            {"name": "회의자료", "best_for": "내부 검토 회의, 쟁점 비교"},
            {"name": "홈페이지 공고문", "best_for": "학생 안내문, 공지사항 초안"},
        ],
        "markdown_preview": _compact(report_draft, 500),
    }


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
    filename = _strip_file_noise(source.filename or source.doc_no or "일정")
    if "면접전형" in filename or "면접전형" in source.content:
        return "면접전형"
    if "서류전형" in filename or "서류전형" in source.content:
        return "서류전형"
    if "추가 모집" in filename or "추가모집" in filename:
        return "추가 모집"
    if "지원 기준 변경" in filename:
        return "지원 기준 변경"
    if "시험" in filename:
        return "선발 시험"
    return _compact(filename, 40)


def _can_use_doc_date_as_event(source: Source) -> bool:
    text = f"{source.filename or ''} {source.content}"
    return any(keyword in text for keyword in ("계획", "안내", "일정", "실시", "모집", "시험"))


def _year(source: Source) -> int | None:
    if source.doc_date and len(source.doc_date) >= 4 and source.doc_date[:4].isdigit():
        return int(source.doc_date[:4])
    match = re.search(r"20\d{2}", f"{source.filename or ''} {source.content}")
    return int(match.group(0)) if match else None


def _compact(text: str, limit: int) -> str:
    single = re.sub(r"\s+", " ", text).strip()
    return single if len(single) <= limit else single[:limit - 3] + "..."


def _timeline_events(sources: list[Source]) -> list[dict]:
    grouped: dict[tuple[str, str], dict] = {}
    for source in sources:
        event_title = _event_title(source)
        key = (source.doc_date or "날짜 미상", _event_key(f"{_work_title(source)} {event_title} {source.doc_no or ''}"))
        event = grouped.setdefault(key, {
            "date": source.doc_date,
            "doc_no": source.doc_no,
            "work_title": _work_title(source),
            "event_title": event_title,
            "document_ids": [],
            "document_count": 0,
        })
        if source.document_id not in event["document_ids"]:
            event["document_ids"].append(source.document_id)
            event["document_count"] += 1
    return sorted(grouped.values(), key=lambda e: (e["date"] or "9999-12-31", e["doc_no"] or "", e["event_title"]))


def _work_title(source: Source) -> str:
    text = f"{source.filename or ''} {source.content}"
    year = _year(source)
    semester = _semester(text)
    prefix = f"{year}학년도 " if year else ""
    if semester:
        prefix += f"{semester}학기 "
    if "교환학생" in text and ("파견" in text or "해외" in text):
        return f"{prefix}해외 파견 교환학생 후보 선발".strip()
    if "초청" in text and "교환학생" in text:
        return f"{prefix}초청 교환학생 운영".strip()
    if "출장" in text:
        return f"{prefix}국외 출장".strip()
    if "대표단" in text or "내방" in text:
        return f"{prefix}대외 교류".strip()
    return _compact(_strip_file_noise(source.filename or source.doc_no or source.document_id[:8]), 80)


def _work_id(source: Source) -> str:
    return _event_key(_work_title(source))


def _semester(text: str) -> int | None:
    match = re.search(r"(\d)\s*학기", text)
    if not match:
        return None
    value = int(match.group(1))
    return value if 1 <= value <= 4 else None


def _strip_file_noise(text: str) -> str:
    text = _EXT_RE.sub("", text.strip())
    text = _ATTACH_PREFIX_RE.sub("", text)
    return _SPACE_RE.sub(" ", text).strip()


def _event_key(text: str) -> str:
    text = _strip_file_noise(text)
    text = re.sub(r"20\d{2}(년도|학년도)?", "{year}", text)
    text = re.sub(r"\b\d{2,5}\b", "{number}", text)
    return re.sub(r"[^0-9A-Za-z가-힣{}]+", "", text).lower()


def _document_type_sort_key(document_type: str) -> tuple[int, str]:
    order = {"시험": 0, "서류전형": 1, "면접": 2, "출장": 3, "붙임": 4, "문서": 5}
    return (order.get(document_type, 99), document_type)
