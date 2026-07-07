"""Phase 7 스튜디오 — NotebookLM식 산출물(마인드맵·슬라이드·인포그래픽).

검색된 출처(Source)만 근거로 산출물을 만든다. 뼈대는 결정론적(규칙기반)이라
LLM 없이도 테스트 가능하고 환각이 없다. 문구 보강이 필요한 요약(summary)은
LLM 경유이므로 rag.stream_summary 를 쓴다(이 모듈은 비-LLM 산출물만 담당).

모든 입력은 이미 마스킹된 본문(Source.content)이므로 마스킹 경계선은 유지된다.
분류·집계는 insights 모듈을 재사용해 검색·인사이트와 같은 기준을 공유한다.
"""

from __future__ import annotations

import json
import re

from . import insights
from .retriever import Source

# ── 공통 텍스트 정제 ─────────────────────────────────────────────
_MERMAID_UNSAFE = re.compile(r"[()\[\]{}\"'`#;|<>]+")
_WS = re.compile(r"\s+")


def _clean(text: str, limit: int = 60) -> str:
    single = _WS.sub(" ", (text or "").strip())
    return single if len(single) <= limit else single[: limit - 1] + "…"


def _mermaid_node(text: str, limit: int = 48) -> str:
    """Mermaid mindmap 노드 텍스트: 셰이프/구문 문자를 제거해 파싱 오류를 막는다."""
    safe = _MERMAID_UNSAFE.sub(" ", text or "")
    safe = _WS.sub(" ", safe).strip()
    if not safe:
        safe = "문서"
    return _clean(safe, limit)


def _svg_escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ── 지표 집계 ────────────────────────────────────────────────────
def studio_metrics(query: str, sources: list[Source]) -> dict:
    """마인드맵·슬라이드·인포그래픽이 공유하는 수치 요약.

    문서 수는 중복 제거(document_id 기준), 카테고리/문서유형 분포와 기간을 낸다.
    """
    work_items = insights.group_work_items(sources)

    seen: set[str] = set()
    category_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    dept_counts: dict[str, int] = {}
    for source in sources:
        if source.document_id in seen:
            continue
        seen.add(source.document_id)
        c = insights.classify_source(source)
        category_counts[c["task_category"]] = category_counts.get(c["task_category"], 0) + 1
        type_counts[c["document_type"]] = type_counts.get(c["document_type"], 0) + 1
        dept = source.citation_dept or source.dept or "부서 미상"
        dept_counts[dept] = dept_counts.get(dept, 0) + 1

    dates = sorted(
        d for d in (w.get("start_date") for w in work_items) if d
    ) + sorted(d for d in (w.get("end_date") for w in work_items) if d)
    start = dates[0] if dates else None
    end = dates[-1] if dates else None

    return {
        "query": query,
        "document_count": len(seen),
        "work_item_count": len(work_items),
        "category_count": len(category_counts),
        "categories": _sorted_pairs(category_counts),
        "document_types": _sorted_pairs(type_counts),
        "departments": _sorted_pairs(dept_counts),
        "period_start": start,
        "period_end": end,
    }


def _sorted_pairs(counts: dict[str, int]) -> list[dict]:
    return [
        {"label": label, "count": count}
        for label, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


# ── 1. 마인드맵 (Mermaid mindmap) ────────────────────────────────
def build_mindmap_mermaid(query: str, sources: list[Source], *,
                          groups: dict[str, str] | None = None) -> str:
    """검색 결과를 주제 → 그룹 → 업무 → 문서유형 계층의 Mermaid mindmap 으로.

    Mermaid mindmap 은 들여쓰기로 계층을 표현한다. 노드 텍스트는 셰이프 문자를
    제거해 파싱 안정성을 확보한다. 근거 없는 노드는 만들지 않는다(환각 억제).

    groups: work_id → 그룹 라벨. 주어지면 의미 기반 그룹으로 묶고, 없으면 규칙기반
    task_category 로 묶는다. 노드(업무·문서)는 항상 결정론적으로 유지되어 환각 표면적을
    라벨로만 국한한다.
    """
    root = _mermaid_node(query or "KMU Wiki", 40) or "KMU Wiki"
    lines = ["mindmap", f"  root(({root}))"]

    work_items = insights.group_work_items(sources)
    if not work_items:
        lines.append("    근거 문서 없음")
        return "\n".join(lines)

    # 그룹 라벨로 업무를 묶는다(의미 그룹 우선, 없으면 task_category 폴백).
    by_category: dict[str, list[dict]] = {}
    for work in work_items:
        if groups:
            label = groups.get(work["work_id"]) or work["task_category"]
        else:
            label = work["task_category"]
        by_category.setdefault(label, []).append(work)

    for category, works in sorted(by_category.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        lines.append(f"    {_mermaid_node(category, 30)}")
        for work in works:
            term = (work.get("terms") or [None])[0]
            title = work["work_title"]
            if term:
                title = f"{title} · {term}"
            lines.append(f"      {_mermaid_node(title, 44)}")
            types = work.get("document_types") or []
            count = work.get("document_count") or 0
            leaf = ", ".join(types) if types else "문서"
            lines.append(f"        {_mermaid_node(f'{leaf} {count}건', 40)}")
    return "\n".join(lines)


# ── 3. 슬라이드 (Marp 마크다운) ──────────────────────────────────
def build_slides_marp(query: str, sources: list[Source], *, title: str | None = None) -> str:
    """검색 결과를 Marp(마크다운→슬라이드) 문서로. 보고서 아웃라인을 재활용한다.

    반환값은 그대로 .md 로 저장해 Marp CLI / VS Code Marp 로 PDF·PPTX·HTML 변환 가능.
    """
    metrics = studio_metrics(query, sources)
    work_items = insights.group_work_items(sources)
    deck_title = title or _clean(query or "KMU Wiki 브리핑", 60)

    out: list[str] = []
    out.append("---")
    out.append("marp: true")
    out.append("theme: default")
    out.append("paginate: true")
    out.append(f'title: "{deck_title}"')
    out.append("---")
    out.append("")
    # 표지
    out.append(f"# {deck_title}")
    out.append("")
    period = _period_label(metrics)
    out.append(f"**KMU Wiki 자동 브리핑** · 문서 {metrics['document_count']}건 · 업무 {metrics['work_item_count']}건{period}")
    out.append("")
    out.append("> 검색된 근거 문서만으로 생성된 초안입니다. 사람 검토 후 사용하세요.")
    out.append("")

    # 개요
    out.append("---")
    out.append("")
    out.append("## 개요")
    out.append("")
    for cat in metrics["categories"]:
        out.append(f"- **{cat['label']}** — {cat['count']}건")
    if not metrics["categories"]:
        out.append("- 근거 문서를 찾지 못했습니다.")
    out.append("")

    # 업무별 슬라이드 (최대 8개)
    for idx, work in enumerate(work_items[:8], start=1):
        out.append("---")
        out.append("")
        out.append(f"## {idx}. {_clean(work['work_title'], 60)}")
        out.append("")
        meta_bits = []
        if work.get("terms"):
            meta_bits.append(" / ".join(work["terms"]))
        if work.get("start_date"):
            span = work["start_date"]
            if work.get("end_date") and work["end_date"] != work["start_date"]:
                span = f"{work['start_date']} ~ {work['end_date']}"
            meta_bits.append(span)
        meta_bits.append(f"{work.get('document_count', 0)}개 문서")
        out.append(f"*{' · '.join(meta_bits)}*")
        out.append("")
        for doc in work.get("documents", [])[:6]:
            label = doc.get("doc_no") or doc.get("filename") or doc.get("label") or "문서"
            date = doc.get("doc_date") or "날짜 미상"
            out.append(f"- {_clean(label, 54)} ({date})")
        out.append("")

    # 출처
    out.append("---")
    out.append("")
    out.append("## 출처")
    out.append("")
    for i, source in enumerate(_dedup_sources(sources)[:12], start=1):
        out.append(f"{i}. {_clean(source.label(), 80)}")
    if not sources:
        out.append("_근거 문서 없음_")
    out.append("")
    return "\n".join(out)


def _period_label(metrics: dict) -> str:
    start, end = metrics.get("period_start"), metrics.get("period_end")
    if start and end and start != end:
        return f" · {start} ~ {end}"
    if start:
        return f" · {start}"
    return ""


def _dedup_sources(sources: list[Source]) -> list[Source]:
    seen: set[str] = set()
    out: list[Source] = []
    for s in sources:
        if s.document_id in seen:
            continue
        seen.add(s.document_id)
        out.append(s)
    return out


# ── 4. 인포그래픽 (자립형 SVG) ───────────────────────────────────
_SVG_W = 820


def build_infographic_svg(query: str, sources: list[Source]) -> str:
    """지표를 자립형 SVG 인포그래픽으로. 외부 폰트/스크립트 의존 없음.

    상단 요약 카드 + 카테고리 막대차트 + 문서유형 분포. 텍스트는 SVG 이스케이프.
    색상은 CSS 변수 대신 고정 팔레트(다운로드/캡처 시에도 동일 렌더 보장).
    """
    metrics = studio_metrics(query, sources)
    cards = [
        ("문서", metrics["document_count"]),
        ("업무", metrics["work_item_count"]),
        ("분류", metrics["category_count"]),
    ]
    categories = metrics["categories"][:6]
    max_count = max((c["count"] for c in categories), default=1) or 1

    bar_area_h = max(1, len(categories)) * 34 + 20
    height = 250 + bar_area_h
    palette = ["#2563eb", "#7c3aed", "#0891b2", "#db2777", "#ca8a04", "#16a34a"]

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_SVG_W} {height}" '
        f'width="{_SVG_W}" height="{height}" font-family="Pretendard, \'Apple SD Gothic Neo\', sans-serif">'
    )
    parts.append(f'<rect x="0" y="0" width="{_SVG_W}" height="{height}" fill="#f8fafc"/>')
    parts.append(f'<rect x="0" y="0" width="{_SVG_W}" height="72" fill="#0f172a"/>')
    parts.append(
        f'<text x="32" y="34" fill="#ffffff" font-size="20" font-weight="700">'
        f'{_svg_escape(_clean(query or "KMU Wiki", 44))}</text>'
    )
    period = _period_label(metrics).lstrip(" ·") or "기간 미상"
    parts.append(
        f'<text x="32" y="56" fill="#94a3b8" font-size="13">KMU Wiki 인포그래픽 · {_svg_escape(period)}</text>'
    )

    # 요약 카드
    card_w = (_SVG_W - 64 - 32) / 3
    for i, (label, value) in enumerate(cards):
        x = 32 + i * (card_w + 16)
        parts.append(f'<rect x="{x:.0f}" y="92" width="{card_w:.0f}" height="96" rx="12" fill="#ffffff" stroke="#e2e8f0"/>')
        parts.append(
            f'<text x="{x + card_w / 2:.0f}" y="146" fill="#0f172a" font-size="40" font-weight="800" '
            f'text-anchor="middle">{value}</text>'
        )
        parts.append(
            f'<text x="{x + card_w / 2:.0f}" y="172" fill="#64748b" font-size="14" '
            f'text-anchor="middle">{_svg_escape(label)}</text>'
        )

    # 카테고리 막대차트
    parts.append('<text x="32" y="228" fill="#0f172a" font-size="15" font-weight="700">분류별 문서 수</text>')
    bar_x = 180
    bar_max_w = _SVG_W - bar_x - 60
    y = 248
    if not categories:
        parts.append('<text x="32" y="272" fill="#94a3b8" font-size="13">근거 문서를 찾지 못했습니다.</text>')
    for i, cat in enumerate(categories):
        color = palette[i % len(palette)]
        w = max(6, bar_max_w * cat["count"] / max_count)
        parts.append(
            f'<text x="{bar_x - 12}" y="{y + 16}" fill="#334155" font-size="13" '
            f'text-anchor="end">{_svg_escape(_clean(cat["label"], 14))}</text>'
        )
        parts.append(f'<rect x="{bar_x}" y="{y}" width="{w:.0f}" height="24" rx="6" fill="{color}"/>')
        parts.append(
            f'<text x="{bar_x + w + 8:.0f}" y="{y + 17}" fill="#0f172a" font-size="13" '
            f'font-weight="700">{cat["count"]}</text>'
        )
        y += 34

    parts.append("</svg>")
    return "".join(parts)


# ── 마인드맵 의미 그룹핑 (선택적 LLM) ────────────────────────────
CLUSTER_SYSTEM_PROMPT = (
    "당신은 대학 행정 업무를 주제별로 묶는 분류기입니다. 주어진 업무 목록을 의미가 비슷한 "
    "2~5개의 그룹으로 묶으세요. 각 그룹 라벨은 12자 이내의 한국어 명사구입니다. "
    "반드시 아래 JSON 형식만 출력하세요(설명·코드블록 금지): "
    '{"groups": [{"label": "그룹명", "work_ids": ["id1", "id2"]}]}. '
    "제공된 work_id 만 사용하고, 새 업무를 지어내지 마세요."
)


def build_cluster_prompt(query: str, work_items: list[dict]) -> str:
    """의미 그룹핑용 LLM 프롬프트(사용자 메시지). 업무 목록만 근거로 준다."""
    lines = [f"주제: {query}", "", "업무 목록:"]
    for work in work_items:
        types = ", ".join(work.get("document_types") or []) or "문서"
        term = (work.get("terms") or [None])[0] or ""
        lines.append(
            f'- work_id="{work["work_id"]}" 제목="{_clean(work["work_title"], 60)}" '
            f'분류="{work.get("task_category", "")}" 문서유형="{types}" {term}'.rstrip()
        )
    lines.append("")
    lines.append("위 업무들을 의미가 비슷한 그룹으로 묶어 지정된 JSON으로만 답하세요.")
    return "\n".join(lines)


def parse_cluster_response(text: str, work_items: list[dict]) -> dict[str, str]:
    """LLM JSON 응답을 work_id → 그룹 라벨 매핑으로. 안전 파싱·검증.

    - 유효한 work_id 만 채택(환각 id 무시).
    - 파싱 실패/누락 업무는 규칙기반 task_category 로 폴백.
    - 라벨은 셰이프 안전 문자로 정제.
    """
    valid_ids = {w["work_id"] for w in work_items}
    fallback = {w["work_id"]: w.get("task_category") or "일반 행정" for w in work_items}
    mapping: dict[str, str] = {}

    obj = _extract_json(text)
    if isinstance(obj, dict):
        for group in obj.get("groups", []) or []:
            if not isinstance(group, dict):
                continue
            label = _mermaid_node(str(group.get("label") or "").strip(), 24)
            if not label:
                continue
            for wid in group.get("work_ids", []) or []:
                wid = str(wid)
                if wid in valid_ids and wid not in mapping:
                    mapping[wid] = label

    # 누락된 업무는 규칙기반 분류로 채운다(항상 완전한 매핑 반환).
    for wid in valid_ids:
        mapping.setdefault(wid, fallback[wid])
    return mapping


def _extract_json(text: str) -> object:
    """LLM 응답에서 첫 JSON 오브젝트를 관대하게 추출(코드블록/잡텍스트 허용)."""
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except (ValueError, TypeError):
            return None
    return None


def cluster_work_items(query: str, sources: list[Source], generate) -> dict[str, str]:
    """업무를 의미 그룹으로 묶어 work_id → 라벨 매핑을 반환한다.

    generate: (system, prompt) -> str. 실패 시 규칙기반 task_category 로 폴백한다.
    업무가 2개 미만이면 그룹핑 이득이 없어 규칙기반을 그대로 쓴다.
    """
    work_items = insights.group_work_items(sources)
    fallback = {w["work_id"]: w.get("task_category") or "일반 행정" for w in work_items}
    if len(work_items) < 2:
        return fallback
    try:
        text = generate(CLUSTER_SYSTEM_PROMPT, build_cluster_prompt(query, work_items))
    except Exception:
        return fallback
    return parse_cluster_response(text or "", work_items)
