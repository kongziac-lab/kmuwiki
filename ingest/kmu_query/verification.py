"""Evidence verification layer for high-precision RAG answers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .retriever import Source


DATE_TERMS = ("언제", "일정", "일시", "날짜", "개최일", "방문일", "출장기간", "기간", "며칠", "몇일")
COUNT_TERMS = ("몇 명", "몇명", "인원", "명단", "몇 개", "건수")
# "원"은 직원·지원·병원·원장 등 흔한 단어의 부분 문자열이라 단독으로 두면
# 금액과 무관한 질문까지 money로 오분류된다(→ 전체 ZIP 확장 오작동). 금액 의도가
# 분명한 다자어만 사용한다.
MONEY_TERMS = ("금액", "예산", "결산", "소요", "달러", "비용", "얼마")
PLACE_TERMS = ("어디", "장소", "위치")
APPROVAL_TERMS = ("승인", "결재", "확정", "완료")

DATE_PATTERN = re.compile(
    r"(20\d{2})[.\-/년]\s*(1[0-2]|0?[1-9])(?!\d)(?:[.\-/월]\s*(3[01]|[12]\d|0?[1-9])(?!\d))?"
    r"|(1[0-2]|0?[1-9])/(3[01]|[12]\d|0?[1-9])(?!\d)"
)
COUNT_PATTERN = re.compile(r"(?<!\d)(\d{1,4})\s*(?:명|개|건|부|팀)(?!\d)")
MONEY_PATTERN = re.compile(r"(?<!\d)(?:[$＄]\s*)?\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*(?:달러|원|천원|만원|억원|USD|KRW)?")
PLACE_PATTERN = re.compile(r"(?:장소|위치|출장 장소|개최 장소)\s*[:：]?\s*([^.\n。]{2,80})")
APPROVAL_PATTERN = re.compile(r"(전결|대결|승인|결재|확정|완료)")
RELATED_ANCHORS = ("관련:", "관련 :", "관련문서", "관련 문서")
APPROVAL_MARKERS = ("전결", "대결", "담당자", "팀장", "처장", "원장")
# 언어권 그룹 라벨(예: "중국어권", "중국어 외 언어권", "중국어 및 언어권").
# 일정 항목이 "나) 면접 전형: ..."처럼 라벨 없이 잘리므로, 직전 라벨을 붙여
# 어느 언어권의 일정인지 표에서 구분되게 한다.
LANG_GROUP_PATTERN = re.compile(r"[가-힣]+어(?:\s*(?:외|및)\s*언어)?권")
LANG_BASES = ("중국어", "영어", "일본어", "스페인어", "러시아어", "독일어", "프랑스어")
# 연락처·공개구분 등 결재/안내 보일러플레이트 — 일정 근거로 쓰지 않는다.
PHONE_PATTERN = re.compile(r"0\d{1,2}-\d{3,4}-\d{4}")
BOILERPLATE_MARKERS = ("[이메일]", "부분공개", "문의 사항", "문의사항")
# 일정 판정의 핵심 기준: '이벤트 라벨이 완전한 날짜에 인접'한 문장 구조.
# ("window 안에 면접·날짜가 공존"만으로는 붙임 배정표 같은 평탄화된 표가
#  통과한다 — 표에는 라벨-날짜 인접 구조가 없으므로 이 기준이 구조적으로 거른다.)
EVENT_LABELED_DATE_PATTERN = re.compile(
    r"(?:전형|시험|면접|접수|마감|발표|선정|일시|일자|기간|내방|방문|개최|행사|출장|시행)"
    r"[^가-힣0-9]{0,12}"
    r"(?:20\d{2}[.\-/년]\s*(?:1[0-2]|0?[1-9])[.\-/월]\s*(?:3[01]|[12]\d|0?[1-9])(?!\d)"
    r"|(?:1[0-2]|0?[1-9])/(?:3[01]|[12]\d|0?[1-9])(?!\d))"
)
# 붙임 배정표(개인별 면접 배정) 특유의 열 이름 — 2개 이상이면 표 덤프로 본다.
TABLE_DUMP_TOKENS = ("고사실", "배정", "인원(명)", "언어권 배정", "시작 시간")


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
    required = _required_date_terms(query)
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
            if not _matches_date_focus(focus_text, focus_terms, window, text, required):
                continue
            # 결재라인·연락처 보일러플레이트를 행사일보다 먼저 걸러낸다
            # (window에 '전형' 등이 섞여 있어도 일정 표에 오르지 않게).
            if _looks_like_approval_line(window):
                approval_hits.append((idx, window, label))
                continue
            if _looks_like_boilerplate(window) or _looks_like_table_dump(window):
                continue
            if _has_labeled_event_date(window):
                event_hits.append((idx, window, label))
            elif _has_any(window, RELATED_ANCHORS):
                related_hits.append((idx, window, label))
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
            # 날짜 질문과 같은 노이즈 필터를 유형별로 적용한다.
            # 단, 결재 질문엔 결재라인이 곧 근거이고 인원 질문엔 표가 곧 근거라 제외.
            if query_type != "approval" and _looks_like_approval_line(window):
                continue
            if _looks_like_boilerplate(window):
                continue
            if query_type not in ("count_or_list", "approval") and _looks_like_table_dump(window):
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


def _matches_date_focus(
    text: str,
    focus_terms: tuple[str, ...],
    window: str,
    source_text: str = "",
    required: tuple[str, ...] | None = None,
) -> bool:
    if required is None:
        required = ()
    if required:
        # 질문이 명시한 조건(면접·언어권)은 전부 충족해야 한다 — 하나라도 어긋나면 제외.
        return all(_date_term_matches(term, window, source_text) for term in required)
    if _matches_focus(text, focus_terms):
        return True
    if not focus_terms or not _looks_like_schedule_item(window):
        return False
    compact_text = re.sub(r"\s+", "", text)
    return any(re.sub(r"\s+", "", term) in compact_text for term in focus_terms)


def _required_date_terms(query: str) -> tuple[str, ...]:
    """질문에서 반드시 지켜야 할 조건어를 뽑는다(질문 원문 기준).

    언어권은 부정형("중국어 외 …")과 긍정형("중국어권/중국어")을 구분한다 —
    '중국어'가 '중국어 외 언어권'의 부분 문자열이라 focus 단어 매칭만으로는
    정반대 언어권 일정이 통과해 버리기 때문이다.
    """
    compact = re.sub(r"\s+", "", query)
    required: list[str] = []
    if "면접" in compact:
        required.append("면접")
    for base in LANG_BASES:
        if f"{base}외" in compact:      # 예: "중국어 외 언어권" 일정을 물음
            required.append(f"{base}외")
        elif base in compact:            # 예: "중국어권"/"중국어" 일정을 물음
            required.append(base)
    return tuple(required)


def _date_term_matches(term: str, window: str, source_text: str) -> bool:
    compact_window = re.sub(r"\s+", "", window)
    compact_source = re.sub(r"\s+", "", source_text)
    if term == "면접":
        return "면접" in compact_window
    if term.endswith("외"):              # 부정형 질문: "중국어외" 표기 자체를 요구
        return term in compact_window
    if term in LANG_BASES:
        # window 안에 언어권 표기가 있으면 window 기준으로만 판정한다.
        # (문서 전체로 폴백하면 "중국어 외 언어권" 행이 문서 내 다른 곳의
        #  "중국어권" 덕에 통과해 버린다.)
        if LANG_GROUP_PATTERN.search(compact_window) or term in compact_window:
            return _mentions_lang_positive(term, compact_window)
        return (_mentions_lang_positive(term, compact_source)
                or (term == "중국어" and "중문" in compact_source))
    return re.sub(r"\s+", "", term) in compact_window or re.sub(r"\s+", "", term) in compact_source


def _mentions_lang_positive(term: str, compact: str) -> bool:
    """'중국어…' 언급 중 '중국어외…'(해당 언어권 제외 표기)가 아닌 것이 있는가."""
    return any(
        not compact.startswith("외", m.end())
        for m in re.finditer(re.escape(term), compact)
    )


def _date_answer_from_event_hits(
    query: str,
    event_hits: list[tuple[int, str, str]],
    form_hits: list[tuple[int, str]],
) -> str:
    seen: set[str] = set()
    rows = []
    for idx, sentence, label in event_hits:
        summary = _event_date_summary(sentence)
        # 요약이 항목 마커에서 다시 잘리며 언어권 라벨이 떨어지면 복원한다 —
        # "면접 전형: 4. 2."만으로는 어느 언어권 일정인지 표에서 알 수 없다.
        lang = LANG_GROUP_PATTERN.search(sentence)
        if lang and lang.group(0) not in summary:
            summary = f"{lang.group(0)} · {summary}"
        # 요약 전체를 전역 키로 쓴다. 첫 날짜만 키로 쓰면 같은 날짜로 시작하는
        # 서로 다른 언어권 블록이 탈락하고, 문서(idx)까지 키에 넣으면 같은 ZIP의
        # pdf/mht 쌍둥이가 같은 일정을 중복 행으로 만든다(5행 상한 잠식).
        key = _compact(summary)
        if key in seen:
            continue
        seen.add(key)
        source_title = _source_title(label)
        rows.append((source_title, summary, idx))
        if len(rows) >= 5:
            break

    overview = (
        f"자료에서 확인되는 일시는 1건입니다 [{rows[0][2]}]."
        if len(rows) == 1
        else f"자료에서 확인되는 일정은 {len(rows)}건입니다."
    )
    if form_hits:
        overview += f" 개최형식은 서면결의로 확인됩니다 [{form_hits[0][0]}]."

    table = [
        "| 구분 | 근거 문서 | 확인 내용 | 근거 |",
        "|---|---|---|---|",
    ]
    for number, (source_title, summary, idx) in enumerate(rows, 1):
        table.append(
            "| "
            + " | ".join((
                f"{number}",
                _markdown_table_cell(source_title),
                _markdown_table_cell(summary),
                f"[{idx}]",
            ))
            + " |"
        )

    caution = "- 문서일자·결재일·관련문서일은 실제 행사일시와 다를 수 있으므로 본문에 명시된 일정 근거를 우선했습니다."
    if form_hits:
        caution += "\n- 서면결의 여부는 일정과 별도 속성으로 보아야 합니다."

    return "\n\n".join((
        "## 한눈에 보기\n" + overview,
        "## 확인된 내용\n" + "\n".join(table),
        "## 주의할 점\n" + caution,
    ))


def _date_answer_without_event_hit(
    query: str,
    form_hits: list[tuple[int, str]],
    doc_dates: list[tuple[int, str, str]],
) -> str:
    overview = "자료 본문에서 별도의 개최일시 또는 행사일시는 확인되지 않습니다."
    rows = [
        "| 항목 | 확인 내용 | 근거 |",
        "|---|---|---|",
    ]
    if "개최" in query and form_hits:
        rows.append(f"| 개최형식 | 서면결의 | [{form_hits[0][0]}] |")
    if doc_dates:
        idx, date, _label = doc_dates[0]
        rows.append(f"| 문서일자 | {date} | [{idx}] |")

    caution = (
        "- 문서일자는 행정 문서의 작성·시행 기준일일 수 있어 실제 개최일로 단정할 수 없습니다.\n"
        "- 최종 일정 확인이 필요하면 원문 또는 붙임 자료의 행사일시 항목을 확인해야 합니다."
    )
    return "\n\n".join((
        "## 한눈에 보기\n" + overview,
        "## 확인된 내용\n" + "\n".join(rows),
        "## 주의할 점\n" + caution,
    ))


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
    focused = _schedule_item_around_date(text)
    if focused:
        return _short(focused, 100)
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


def _schedule_item_around_date(text: str) -> str | None:
    match = DATE_PATTERN.search(text)
    if not match:
        return None

    prefix = text[:match.start()]
    start = _schedule_item_start(prefix)
    end = _schedule_item_end(text, match.end())
    item = text[start:end].strip(" \t\n\r.;")
    item = re.sub(r"^(?:[가-하]\.\s*)+", "", item)
    item = re.sub(r"^[가-하]\)\s*", "", item)
    item = re.sub(r"^\d+\)\s+", "", item)
    item = re.sub(r"^\(\d+\)\s*", "", item)
    item = re.sub(r"\s+", " ", item).strip()
    return item or None


def _schedule_item_start(prefix: str) -> int:
    candidates = [0]
    # 항목 마커: "1)" "가)" "가." 에 더해 "(1)" 괄호형도 인식한다 —
    # 전자결재 원문이 "나) 중국어권 (1) 서류 (2) 필기 (3) 면접" 구조라,
    # 괄호 마커를 못 자르면 언어권 블록 전체가 한 window 로 뭉친다.
    for marker in re.finditer(r"(?:^|\s)(\d+\)|\(\d+\)|[가-하][.)])\s*", prefix):
        candidates.append(marker.start(1))
    anchors = (
        "내방일시", "방문일", "개최일시", "행사일시", "출장기간", "출장 기간",
        "면접일", "시험일", "시행일", "일자", "기간", "일시",
    )
    anchor_pattern = r"(" + "|".join(re.escape(anchor) for anchor in anchors) + r")\s*[:：]?"
    for marker in re.finditer(anchor_pattern, prefix):
        candidates.append(marker.start(1))
    return max(candidates)


def _schedule_item_end(text: str, after_date_index: int) -> int:
    tail = text[after_date_index:]
    candidates = [len(text)]
    marker = re.search(r"\s(?:\d+\)|\(\d+\)|[가-하][.)])\s*", tail)
    if marker:
        candidates.append(after_date_index + marker.start())
    label = re.search(
        r"\s(?:주요내용|소요예산|장소|대상|비고|최종\s+선발자|선발\s+일정|붙임|첨부)\s*[:：]?",
        tail,
    )
    if label:
        candidates.append(after_date_index + label.start())
    return min(candidates)


def _primary_date(text: str) -> str | None:
    match = DATE_PATTERN.search(text)
    return match.group(0) if match else None


def _source_title(label: str) -> str:
    return label.split(" · ")[-1] if label else "자료"


def _markdown_table_cell(value: str) -> str:
    return _compact(value).replace("|", "\\|")


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
        start = _schedule_item_start(text[:match.start()])
        end = _schedule_item_end(text, match.end())
        if end <= start:
            start = max(0, match.start() - 90)
            end = min(len(text), match.end() + 140)
        window = text[start:end].strip()
        # "나) 면접 전형: …"처럼 언어권 라벨이 잘려 나간 항목에는 직전 라벨을
        # 붙여 어느 언어권 일정인지 표와 필터에서 구분되게 한다.
        label = _nearest_lang_group_label(text[:start])
        if label and not LANG_GROUP_PATTERN.search(window):
            window = f"{label} · {window}"
        windows.append(window)
    return windows


def _nearest_lang_group_label(prefix: str, lookback: int = 250) -> str | None:
    hits = list(LANG_GROUP_PATTERN.finditer(prefix[-lookback:]))
    return hits[-1].group(0) if hits else None


def _has_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _looks_like_approval_line(sentence: str) -> bool:
    if not _has_any(sentence, APPROVAL_MARKERS):
        return False
    slash_dates = re.findall(r"\d{2}/\d{2}", sentence)
    return len(slash_dates) >= 2


def _looks_like_boilerplate(window: str) -> bool:
    """연락처(전화/이메일)·공개구분·문의 안내 문맥 — 일정 근거에서 제외."""
    return bool(PHONE_PATTERN.search(window)) or _has_any(window, BOILERPLATE_MARKERS)


def _looks_like_table_dump(window: str) -> bool:
    """붙임 배정표류의 평탄화된 표 조각인가(개인별 배정 행·열 이름 나열)."""
    return sum(1 for token in TABLE_DUMP_TOKENS if token in window) >= 2


def _has_labeled_event_date(window: str) -> bool:
    """이벤트 라벨(전형·시험·일시·기간 등)이 완전한 날짜(일 포함)에 인접한가.

    '2026. 3.'처럼 일(日) 없는 조각이나, 라벨 없이 날짜만 흩어진 표·서신은
    일정 근거로 삼지 않는다.
    """
    return bool(EVENT_LABELED_DATE_PATTERN.search(window))


def _looks_like_schedule_item(sentence: str) -> bool:
    if not DATE_PATTERN.search(sentence):
        return False
    compact = sentence.strip()
    return bool(
        re.match(r"\d+\)", compact)
        or any(term in compact for term in ("면접", "전형", "일자", "차(", "차:", "내방", "방문", "서류 접수", "서류접수"))
    )


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _short(text: str, limit: int = 180) -> str:
    text = _compact(text)
    return text if len(text) <= limit else f"{text[:limit].rstrip()}..."
