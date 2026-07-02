"""Evidence verification layer for high-precision RAG answers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .retriever import Source


DATE_TERMS = ("언제", "일정", "일시", "날짜", "개최일", "방문일", "출장기간", "기간")
COUNT_TERMS = ("몇 명", "몇명", "인원", "명단", "몇 개", "건수")
MONEY_TERMS = ("금액", "예산", "결산", "소요", "달러", "원")
PLACE_TERMS = ("어디", "장소", "위치")
APPROVAL_TERMS = ("승인", "결재", "확정", "완료")

DATE_PATTERN = re.compile(
    r"(20\d{2})[.\-/년]\s*(\d{1,2})(?:[.\-/월]\s*(\d{1,2}))?"
    r"|(\d{1,2})/(\d{1,2})"
)
COUNT_PATTERN = re.compile(r"(?<!\d)(\d{1,4})\s*(?:명|개|건|부|팀)(?!\d)")
MONEY_PATTERN = re.compile(r"(?<!\d)(?:[$＄]\s*)?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:달러|원|천원|만원|억원|USD|KRW)?")
PLACE_PATTERN = re.compile(r"(?:장소|위치|출장 장소|개최 장소)\s*[:：]?\s*([^.\n。]{2,80})")
APPROVAL_PATTERN = re.compile(r"(전결|대결|승인|결재|확정|완료)")
EVENT_ANCHORS = (
    "개최일시", "개최 일시", "개최일", "행사일시", "행사 일시", "일시:",
    "일시", "기간", "방문일", "내방일", "출장기간", "출장 기간", "면접일",
    "시험일", "시행일",
)
RELATED_ANCHORS = ("관련:", "관련 :", "관련문서", "관련 문서")
APPROVAL_MARKERS = ("전결", "대결", "담당자", "팀장", "처장", "원장")


@dataclass(frozen=True)
class VerificationMemo:
    query_type: str
    summary: str
    confirmed: list[str]
    uncertain: list[str]
    evidence: list[str]
    deterministic_answer: str | None = None

    def to_prompt_block(self) -> str:
        lines = [f"검증 유형: {self.query_type}", f"검증 요약: {self.summary}"]
        if self.confirmed:
            lines.append("확정 근거:")
            lines.extend(f"- {item}" for item in self.confirmed)
        if self.uncertain:
            lines.append("주의/불확실:")
            lines.extend(f"- {item}" for item in self.uncertain)
        if self.evidence:
            lines.append("근거 출처:")
            lines.extend(f"- {item}" for item in self.evidence)
        return "\n".join(lines)


def classify_question(query: str) -> str:
    compact = re.sub(r"\s+", "", query)
    if any(term in query or term in compact for term in DATE_TERMS):
        return "date"
    if any(term in query or term in compact for term in COUNT_TERMS):
        return "count_or_list"
    if any(term in query or term in compact for term in MONEY_TERMS):
        return "money"
    if any(term in query or term in compact for term in PLACE_TERMS):
        return "place"
    if any(term in query or term in compact for term in APPROVAL_TERMS):
        return "approval"
    return "general"


def needs_full_zip_context(query: str) -> bool:
    """검증 민감 질문(날짜/인원/금액/장소/결재)이면 ZIP 전체를 대조 자료로 쓴다."""
    return classify_question(query) != "general"


def build_verification_memo(query: str, sources: list[Source]) -> VerificationMemo:
    query_type = classify_question(query)
    if not sources:
        return VerificationMemo(
            query_type=query_type,
            summary="검색된 근거가 없습니다.",
            confirmed=[],
            uncertain=["자료가 없으므로 답변할 수 없습니다."],
            evidence=[],
        )
    if query_type == "date":
        return _verify_date_question(query, sources)
    if query_type == "count_or_list":
        return _verify_pattern_question(
            query, query_type, sources, COUNT_PATTERN,
            "인원/수량 후보", "명단이나 인원 맥락이 없는 숫자는 확정 인원으로 단정하지 않습니다.",
        )
    if query_type == "money":
        return _verify_pattern_question(
            query, query_type, sources, MONEY_PATTERN,
            "금액 후보", "예산/결산/산출 맥락이 없는 숫자는 금액으로 단정하지 않습니다.",
        )
    if query_type == "place":
        return _verify_pattern_question(
            query, query_type, sources, PLACE_PATTERN,
            "장소 후보", "장소 항목으로 명시되지 않은 기관명이나 문서명은 장소로 단정하지 않습니다.",
        )
    if query_type == "approval":
        return _verify_pattern_question(
            query, query_type, sources, APPROVAL_PATTERN,
            "승인/결재 후보", "결재라인의 날짜와 실제 승인 효력일은 구분해야 합니다.",
        )
    return _generic_memo(query_type, sources)


def focus_sources(query: str, sources: list[Source], *, limit: int = 4) -> list[Source]:
    """검증 확장 전에 질문 주제와 맞는 검색 결과만 우선 선택한다."""
    focus_terms = _focus_terms(query)
    if not focus_terms:
        return sources[:limit]
    matched = [
        source for source in sources
        if _matches_focus(
            f"{source.label()} {source.filename or ''} {source.content}",
            focus_terms,
        )
    ]
    return (matched or sources)[:limit]


def _verify_date_question(query: str, sources: list[Source]) -> VerificationMemo:
    grouped = _group_for_citations(sources)
    focus_terms = _focus_terms(query)
    event_hits: list[tuple[int, str, str]] = []
    related_hits: list[tuple[int, str, str]] = []
    approval_hits: list[tuple[int, str, str]] = []
    doc_dates: list[tuple[int, str, str]] = []
    form_hits: list[tuple[int, str]] = []

    for idx, source in enumerate(grouped, 1):
        text = _compact(source.content)
        label = source.label()
        if source.citation_doc_date or source.doc_date:
            doc_dates.append((idx, source.citation_doc_date or source.doc_date or "", label))
        for window in _date_windows(text):
            focus_text = f"{label} {window}"
            if not _matches_focus(focus_text, focus_terms):
                continue
            if _has_any(window, EVENT_ANCHORS):
                event_hits.append((idx, window, label))
            elif _has_any(window, RELATED_ANCHORS):
                related_hits.append((idx, window, label))
            elif _looks_like_approval_line(window):
                approval_hits.append((idx, window, label))
        if "서면결의" in text:
            form_hits.append((idx, label))

    evidence = [f"[{i}] {s.label()}" for i, s in enumerate(grouped, 1)]
    if event_hits:
        confirmed = [
            f"[{idx}] 본문 행사/일시 근거: {_short(sentence)}"
            for idx, sentence, _label in event_hits[:3]
        ]
        answer = _date_answer_from_event_hits(query, event_hits, form_hits)
        return VerificationMemo(
            query_type="date",
            summary="본문에 행사일시로 해석 가능한 날짜 근거가 있습니다.",
            confirmed=confirmed,
            uncertain=_date_uncertain_notes(related_hits, approval_hits, doc_dates),
            evidence=evidence,
            deterministic_answer=answer,
        )

    confirmed = []
    if form_hits:
        confirmed.append(f"[{form_hits[0][0]}] 개최형식은 서면결의로 확인됩니다.")
    if doc_dates:
        idx, date, label = doc_dates[0]
        confirmed.append(f"[{idx}] 대표 문서의 문서일자는 {date}입니다: {label}")

    uncertain = ["본문에서 별도의 개최일시/행사일시는 확인되지 않습니다."]
    uncertain.extend(_date_uncertain_notes(related_hits, approval_hits, doc_dates))
    answer = _date_answer_without_event_hit(query, form_hits, doc_dates)
    return VerificationMemo(
        query_type="date",
        summary="문서일자나 결재라인 날짜는 있으나, 본문 행사일시가 명시되어 있지 않습니다.",
        confirmed=confirmed,
        uncertain=uncertain,
        evidence=evidence,
        deterministic_answer=answer,
    )


def _generic_memo(query_type: str, sources: list[Source]) -> VerificationMemo:
    grouped = _group_for_citations(sources)
    return VerificationMemo(
        query_type=query_type,
        summary="검색 자료를 같은 ZIP의 대표문서와 첨부까지 확장해 검증 자료로 구성했습니다.",
        confirmed=[
            "최종 답변은 아래 자료에 직접 적힌 내용만 사용해야 합니다.",
            "문서일자, 결재일, 관련문서일은 행사일이나 승인일로 단정하지 않습니다.",
        ],
        uncertain=["명시 근거가 없는 값은 '명시되어 있지 않다'고 답해야 합니다."],
        evidence=[f"[{i}] {source.label()}" for i, source in enumerate(grouped, 1)],
    )


def _verify_pattern_question(
    query: str,
    query_type: str,
    sources: list[Source],
    pattern: re.Pattern,
    label: str,
    caution: str,
) -> VerificationMemo:
    grouped = _group_for_citations(sources)
    focus_terms = _focus_terms(query)
    hits: list[str] = []
    for idx, source in enumerate(grouped, 1):
        text = _compact(source.content)
        for match in pattern.finditer(text):
            window = text[max(0, match.start() - 80): min(len(text), match.end() + 120)]
            if not _matches_focus(f"{source.label()} {window}", focus_terms):
                continue
            hits.append(f"[{idx}] {label}: {_short(window)}")
            if len(hits) >= 8:
                break
        if len(hits) >= 8:
            break

    confirmed = hits or []
    uncertain = [caution]
    if not hits:
        uncertain.insert(0, f"자료에서 {label}가 명시된 근거 문장을 찾지 못했습니다.")
    return VerificationMemo(
        query_type=query_type,
        summary=f"{label}를 원문 주변 문맥과 함께 추출했습니다." if hits else f"{label}가 확인되지 않았습니다.",
        confirmed=confirmed,
        uncertain=uncertain,
        evidence=[f"[{i}] {source.label()}" for i, source in enumerate(grouped, 1)],
    )


def _focus_terms(query: str) -> tuple[str, ...]:
    normalized = re.sub(r"[^\w가-힣]+", " ", query)
    raw_terms = [term for term in normalized.split() if len(term) >= 2]
    stop_terms = {
        "언제", "일시", "날짜", "개최", "개최되었나", "개최되었는가",
        "무엇", "어떻게", "있는가", "인가", "대한", "관련", "되나", "되었나",
        "일정", "내용", "정리",
    }
    terms = []
    for term in raw_terms:
        compact = re.sub(r"(은|는|이|가|을|를|의|에|에서|으로|로|와|과|도)$", "", term)
        if compact.startswith("개최"):
            continue
        if compact and compact not in stop_terms and compact not in terms:
            terms.append(compact)
    expanded: list[str] = []
    for term in terms:
        expanded.append(term)
        if "주부산중국총영사관" in term or "총영사관" in term:
            expanded.extend(["주부산중국총영사", "주부산중국부총영사"])
    terms = []
    for term in expanded:
        if term not in terms:
            terms.append(term)
    return tuple(terms[:5])


def _matches_focus(text: str, focus_terms: tuple[str, ...]) -> bool:
    if not focus_terms:
        return True
    compact_text = re.sub(r"\s+", "", text)
    if "이사회" in focus_terms and "이사회" not in compact_text:
        return False
    if any("총영사관" in term for term in focus_terms):
        return "주부산중국총영사" in compact_text or "주부산중국부총영사" in compact_text
    hits = sum(1 for term in focus_terms if re.sub(r"\s+", "", term) in compact_text)
    return hits >= max(1, min(len(focus_terms), 2))


def _date_answer_from_event_hits(
    query: str,
    event_hits: list[tuple[int, str, str]],
    form_hits: list[tuple[int, str]],
) -> str:
    seen: set[tuple[int, str]] = set()
    lines = []
    for idx, sentence, label in event_hits:
        summary = _event_date_summary(sentence)
        key = (idx, _primary_date(summary) or summary)
        if key in seen:
            continue
        seen.add(key)
        source_title = _source_title(label)
        lines.append(f"{source_title}: {summary} [{idx}]")
        if len(lines) >= 5:
            break
    form = " 개최형식은 서면결의입니다." if form_hits else ""
    if len(lines) == 1:
        return f"자료에서 확인되는 일시는 다음 근거입니다: {lines[0]}.{form}"
    return f"자료에서 확인되는 일정은 다음과 같습니다. " + " ".join(
        f"{i + 1}. {line}" for i, line in enumerate(lines)
    ) + form


def _date_answer_without_event_hit(
    query: str,
    form_hits: list[tuple[int, str]],
    doc_dates: list[tuple[int, str, str]],
) -> str:
    bits = []
    if "개최" in query and form_hits:
        bits.append(f"관련 문서에서 개최형식은 서면결의로 확인됩니다 [{form_hits[0][0]}].")
    if doc_dates:
        idx, date, _label = doc_dates[0]
        bits.append(f"대표 문서의 문서일자는 {date}입니다 [{idx}].")
    bits.append("다만 자료 본문에 별도의 개최일시 또는 행사일시는 명시되어 있지 않아, 문서일자를 실제 개최일로 단정할 수 없습니다.")
    return " ".join(bits)


def _date_uncertain_notes(
    related_hits: list[tuple[int, str, str]],
    approval_hits: list[tuple[int, str, str]],
    doc_dates: list[tuple[int, str, str]],
) -> list[str]:
    notes = []
    if related_hits:
        idx, sentence, _label = related_hits[0]
        notes.append(f"[{idx}] 관련 문서 날짜는 행사일이 아닐 수 있습니다: {_short(sentence)}")
    if approval_hits:
        idx, sentence, _label = approval_hits[0]
        notes.append(f"[{idx}] 결재라인 날짜는 행사일이 아닐 수 있습니다: {_short(sentence)}")
    if doc_dates:
        idx, date, _label = doc_dates[0]
        notes.append(f"[{idx}] 문서일자 {date}는 행사일과 구분해야 합니다.")
    return notes


def _event_date_summary(text: str) -> str:
    text = _compact(text)
    patterns = (
        r"(내방일시\s*[:：]?\s*20\d{2}.{0,70})",
        r"(방문일\s*[:：]?\s*20\d{2}.{0,70})",
        r"(개최일시\s*[:：]?\s*20\d{2}.{0,70})",
        r"(행사일시\s*[:：]?\s*20\d{2}.{0,70})",
        r"((?<!관련\s)일시\s*[:：]?\s*20\d{2}.{0,70})",
        r"(기간\s*[:：]?\s*20\d{2}.{0,90})",
        r"(출장기간\s*[:：]?\s*20\d{2}.{0,90})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        summary = re.split(r"\s(?:주요내용|소요예산|장소|대상|비고|[가-하]\.|[0-9]+\.\s+(?!\d))", match.group(1), maxsplit=1)[0]
        return _short(summary, 100)
    return _short(text, 120)


def _primary_date(text: str) -> str | None:
    match = DATE_PATTERN.search(text)
    return match.group(0) if match else None


def _source_title(label: str) -> str:
    return label.split(" · ")[-1] if label else "자료"


def _group_for_citations(sources: list[Source]) -> list[Source]:
    grouped: dict[str, Source] = {}
    for source in sources:
        key = source.label() if (source.citation_filename or source.citation_doc_no) else source.document_id
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = Source(
                document_id=source.document_id,
                chunk_index=source.chunk_index,
                content=source.content.strip(),
                score=source.score,
                filename=source.filename,
                doc_no=source.doc_no,
                doc_date=source.doc_date,
                dept=source.dept,
                citation_filename=source.citation_filename,
                citation_doc_no=source.citation_doc_no,
                citation_doc_date=source.citation_doc_date,
                citation_dept=source.citation_dept,
            )
        elif source.content.strip() and source.content.strip() not in existing.content:
            existing.content = f"{existing.content}\n\n{source.content.strip()}".strip()
    return list(grouped.values())


def _date_windows(text: str) -> list[str]:
    windows = []
    for match in DATE_PATTERN.finditer(text):
        start = max(0, match.start() - 90)
        end = min(len(text), match.end() + 140)
        windows.append(text[start:end].strip())
    return windows


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _looks_like_approval_line(sentence: str) -> bool:
    if not _has_any(sentence, APPROVAL_MARKERS):
        return False
    slash_dates = re.findall(r"\d{2}/\d{2}", sentence)
    return len(slash_dates) >= 2


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _short(text: str, limit: int = 180) -> str:
    text = _compact(text)
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."
