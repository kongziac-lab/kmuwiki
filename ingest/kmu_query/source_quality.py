"""Query-aware source validation for RAG.

The retriever is intentionally broad: it finds plausible candidates. This
module decides which candidates are actually suitable evidence for the user's
question before they are shown to the LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from .retriever import Source


@dataclass(frozen=True)
class QueryIntent:
    kind: str
    include_terms: tuple[str, ...] = ()
    exclude_terms: tuple[str, ...] = ()
    require_any_terms: tuple[str, ...] = ()


VISIT_INCLUDE = (
    "내방", "방문", "초청", "내방자", "내방 인원", "내방인원", "대표단",
    "총영사", "방문교수", "초청명단", "초청 대상",
)
VISIT_EXCLUDE = (
    "출장", "국외 출장", "국외출장", "출장자", "출장 계획", "출장기간",
    "출장 장소", "출장 목적", "유학생 수", "일본인 학생 수", "예산상세산출",
    "예산요약", "출장비", "국내외 교통료",
)
VISIT_STRONG_EXCLUDE = (
    "국외 출장", "국외출장", "출장 계획", "출장자 명단", "출장자 및 출장 기간",
    "출장 기간:", "출장 장소:", "출장 목적", "일본인 학생 수", "유학생 수",
)

TRAVEL_TERMS = ("출장", "국외 출장", "국외출장", "출장자", "출장 계획")
TRAVEL_EXCLUDE = (
    "내방자 명단", "내방 인원", "내방인원", "우리 대학교를 내방",
    "대표단 내방", "총영사 내방", "예산상세산출", "예산요약",
)
TRAVEL_STRONG_EXCLUDE = (
    "내방자 명단", "내방 인원", "내방인원", "우리 대학교를 내방",
    "총영사 일행", "대표단이 양교 간 교류 협력 사업 논의를 위하여 우리 대학교를 내방",
)

BUDGET_TERMS = ("예산", "산출", "금액", "예산상세산출", "수지계산서", "계정과목", "소요예산")
BUDGET_EXCLUDE = ("내방자 명단", "출장자 명단", "초청명단", "유학생 수")

VISA_TERMS = ("비자", "사증", "초청장", "초청 대상", "초청명단", "방문교수")
VISA_EXCLUDE = ("출장 계획", "출장자 명단", "예산상세산출", "예산요약", "유학생 수")

COUNT_TERMS = ("인원", "명", "몇 명", "몇명", "수")
VISIT_TERMS = ("내방", "방문", "초청", "대표단", "방문교수", "총영사")


def classify_query(query: str) -> QueryIntent:
    normalized = _normalize(query)
    wants_count = any(term in normalized for term in COUNT_TERMS)
    wants_visit = any(term in normalized for term in VISIT_TERMS)
    wants_travel = any(term in normalized for term in TRAVEL_TERMS)
    wants_budget = any(term in normalized for term in BUDGET_TERMS)
    wants_visa = any(term in normalized for term in VISA_TERMS)

    if wants_visit and wants_count and not wants_travel:
        return QueryIntent(
            kind="visit_count",
            include_terms=VISIT_INCLUDE,
            exclude_terms=VISIT_EXCLUDE,
            require_any_terms=("내방", "방문", "초청", "대표단", "방문교수", "총영사"),
        )
    if wants_visa and not wants_travel:
        return QueryIntent(
            kind="visa",
            include_terms=VISA_TERMS,
            exclude_terms=VISA_EXCLUDE,
            require_any_terms=("비자", "사증", "초청장", "초청장 발급"),
        )
    if wants_budget:
        return QueryIntent(
            kind="budget",
            include_terms=BUDGET_TERMS,
            exclude_terms=BUDGET_EXCLUDE,
            require_any_terms=("예산", "산출", "금액", "예산상세산출", "수지계산서", "계정과목", "소요예산"),
        )
    if wants_travel:
        return QueryIntent(
            kind="travel",
            include_terms=TRAVEL_TERMS,
            exclude_terms=TRAVEL_EXCLUDE,
            require_any_terms=("출장", "국외 출장", "국외출장", "출장자", "출장 계획"),
        )
    if wants_visit:
        return QueryIntent(
            kind="visit",
            include_terms=VISIT_INCLUDE,
            exclude_terms=VISIT_EXCLUDE,
            require_any_terms=("내방", "방문", "초청", "대표단", "방문교수", "총영사"),
        )
    return QueryIntent(kind="general")


def refine_sources(query: str, sources: list[Source], *, limit: int | None = None) -> list[Source]:
    intent = classify_query(query)
    if intent.kind == "general":
        return sources[:limit] if limit else sources

    validated = [_score_source(intent, source) for source in sources]
    accepted = [item for item in validated if item.accept]

    if not accepted:
        return []

    accepted.sort(key=lambda item: item.score, reverse=True)
    refined = _dedupe_sources(intent, accepted)
    return refined[:limit] if limit else refined


@dataclass
class _Validation:
    source: Source
    accept: bool
    score: float
    reason: str


def _score_source(intent: QueryIntent, source: Source) -> _Validation:
    haystack = _source_text(source)
    include_hits = _hits(intent.include_terms, haystack)
    exclude_hits = _hits(intent.exclude_terms, haystack)
    required_hits = _hits(intent.require_any_terms, haystack)

    score = source.score
    score += 0.015 * len(include_hits)
    score -= 0.03 * len(exclude_hits)

    if intent.kind.startswith("visit"):
        if _hits(VISIT_STRONG_EXCLUDE, haystack) and not _has_visit_anchor(haystack):
            return _Validation(source, False, score, "strong travel/non-visit evidence")
        if not required_hits:
            return _Validation(source, False, score, "missing visit evidence")
        if _is_budget_only(source, haystack):
            return _Validation(source, False, score, "budget-only evidence")
        if _looks_like_travel(haystack) and not _has_visit_anchor(haystack):
            return _Validation(source, False, score, "travel evidence without visit anchor")
    elif intent.kind == "travel":
        if not required_hits:
            return _Validation(source, False, score, "missing travel evidence")
        if _hits(TRAVEL_STRONG_EXCLUDE, haystack) and not _has_travel_anchor(haystack):
            return _Validation(source, False, score, "visit evidence without travel anchor")
        if _is_budget_only(source, haystack):
            return _Validation(source, False, score, "budget-only evidence")
    elif intent.kind == "visa":
        if not required_hits:
            return _Validation(source, False, score, "missing visa evidence")
        if _is_budget_only(source, haystack):
            return _Validation(source, False, score, "budget-only evidence")
        if _looks_like_travel(haystack) and not _has_visa_anchor(haystack):
            return _Validation(source, False, score, "travel evidence without visa anchor")
    elif intent.kind == "budget":
        if not required_hits:
            return _Validation(source, False, score, "missing budget evidence")

    return _Validation(source, True, score, "accepted")


def _dedupe_sources(intent: QueryIntent, items: list[_Validation]) -> list[Source]:
    if not intent.kind.startswith("visit"):
        return [item.source for item in items]

    grouped: dict[str, _Validation] = {}
    for item in items:
        source = item.source
        key = _visit_key(source)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = item
            continue
        if item.score > existing.score:
            grouped[key] = item
        elif source.content.strip() and source.content.strip() not in existing.source.content:
            existing.source.content = f"{existing.source.content.strip()}\n\n{source.content.strip()}".strip()
    return [item.source for item in grouped.values()]


def _visit_key(source: Source) -> str:
    text = _source_text(source)
    compact = _normalize(text)
    patterns = (
        ("nankai-tan-mingran", ("남개", "탄밍란")),
        ("changchun-delegation", ("장춘대학교", "대표단")),
        ("changchun-delegation", ("장춘대학", "대표단")),
        ("busan-china-consul", ("주부산중국총영사",)),
        ("busan-china-vice-consul", ("주부산중국부총영사",)),
    )
    for key, terms in patterns:
        if all(term in compact for term in terms):
            return key
    title = source.filename or source.label()
    title = re.sub(r"\.(pdf|hwp|hwpx|docx?|xlsx?|html?|mht)$", "", title, flags=re.I)
    title = re.sub(r"[\[\(]?붙임\s*\d+[\]\)]?\.?\s*", "", title)
    return _normalize(title)[:80] or source.document_id


def _source_text(source: Source) -> str:
    return "\n".join(part for part in (
        source.filename or "",
        source.dept or "",
        source.doc_no or "",
        source.doc_date or "",
        source.content or "",
    ) if part)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _hits(terms: Iterable[str], text: str) -> list[str]:
    normalized = _normalize(text)
    return [term for term in terms if _normalize(term) in normalized]


def _has_visit_anchor(text: str) -> bool:
    normalized = _normalize(text)
    return any(_normalize(term) in normalized for term in (
        "내방", "우리대학교를내방", "본교방문", "본교방문교수", "초청명단",
        "초청대상", "내방자명단", "내방인원", "대표단내방",
    ))


def _looks_like_travel(text: str) -> bool:
    return bool(_hits(TRAVEL_TERMS, text))


def _has_travel_anchor(text: str) -> bool:
    normalized = _normalize(text)
    return any(_normalize(term) in normalized for term in (
        "출장", "국외출장", "국외출장계획", "출장자", "출장기간", "출장장소",
        "출장목적", "출장계획",
    ))


def _has_visa_anchor(text: str) -> bool:
    normalized = _normalize(text)
    return any(_normalize(term) in normalized for term in (
        "비자", "사증", "초청장", "초청대상", "초청명단", "방문교수",
    ))


def _is_budget_only(source: Source, text: str) -> bool:
    filename = source.filename or ""
    if any(term in filename for term in ("예산상세산출", "예산서", "수지계산서", "결산서")):
        return True
    normalized = _normalize(text)
    has_budget = any(_normalize(term) in normalized for term in ("예산요약", "계정과목", "출장비", "교통료"))
    return has_budget and not _has_visit_anchor(text)
