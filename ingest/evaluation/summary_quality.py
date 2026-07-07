"""Summary quality harness for KMU Wiki 스튜디오 요약(NotebookLM식).

검색 품질 하네스(search_quality.py)와 같은 철학: 순수 JSONL 로 동작해 CI 에서
결정론적으로 게이트할 수 있다. 각 케이스는 생성된 요약 텍스트(고정 fixture)와
근거 출처 수·핵심 출처 번호를 담는다.

결정론적 지표(LLM 불필요):
  - citation_precision : 요약의 [n] 인용 중 유효 출처(1..source_count)를 가리키는 비율.
                         환각 인용(존재하지 않는 출처 번호)을 잡는다.
  - coverage           : 핵심 출처(relevant_ns) 중 요약이 실제 인용한 비율.
  - structure_ok       : 요약이 지정된 섹션 헤더를 모두 포함하는가.
  - has_citation       : 최소 1개 이상 인용을 달았는가.

선택 지표(LLM-judge 주입 시):
  - faithfulness       : judge(query, summary, sources_text) -> [0,1] 평균.
                         judge 를 주입하지 않으면 계산·게이트에서 제외(CI 결정론성 유지).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Callable

# rag.SUMMARY_SYSTEM_PROMPT 이 강제하는 섹션 헤더. 프롬프트와 동기화 유지.
REQUIRED_SECTIONS = ("## 한눈에 보기", "## 핵심 내용", "## 주요 일정·수치", "## 확인이 필요한 점")

# 게이트 임계값.
GATE_CITATION_PRECISION = 0.95
GATE_COVERAGE = 0.60
GATE_FAITHFULNESS = 0.70

_CITE = re.compile(r"\[(\d+)\]")

# judge: (query, summary, sources_text) -> [0,1]. 주입 시 faithfulness 계산.
Judge = Callable[[str, str, str], float]


@dataclass(frozen=True)
class SummaryCase:
    id: str
    query: str
    source_count: int
    summary: str
    relevant_ns: tuple[int, ...] = ()
    sources_text: str = ""


@dataclass
class SummaryMetrics:
    count: int
    citation_precision: float
    coverage: float
    structure_rate: float
    citation_rate: float
    faithfulness: float | None = None
    failures: list[dict] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        ok = (
            self.citation_precision >= GATE_CITATION_PRECISION
            and self.coverage >= GATE_COVERAGE
            and self.structure_rate >= 1.0
            and self.citation_rate >= 1.0
        )
        if self.faithfulness is not None:
            ok = ok and self.faithfulness >= GATE_FAITHFULNESS
        return ok


def load_cases(path: str | Path) -> list[SummaryCase]:
    cases: list[SummaryCase] = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            cases.append(SummaryCase(
                id=str(row["id"]),
                query=str(row["query"]),
                source_count=int(row["source_count"]),
                summary=str(row["summary"]),
                relevant_ns=tuple(int(v) for v in row.get("relevant_ns", [])),
                sources_text=str(row.get("sources_text", "")),
            ))
    return cases


def _cited_numbers(summary: str) -> list[int]:
    return [int(m) for m in _CITE.findall(summary)]


def _case_scores(case: SummaryCase) -> dict:
    cited = _cited_numbers(case.summary)
    valid = [n for n in cited if 1 <= n <= case.source_count]
    precision = (len(valid) / len(cited)) if cited else 0.0
    cited_set = set(valid)
    if case.relevant_ns:
        coverage = len(cited_set.intersection(case.relevant_ns)) / len(set(case.relevant_ns))
    else:
        coverage = 1.0
    structure_ok = all(section in case.summary for section in REQUIRED_SECTIONS)
    return {
        "citation_precision": precision,
        "coverage": coverage,
        "structure_ok": structure_ok,
        "has_citation": len(cited) > 0,
        "invalid_citations": sorted(n for n in cited if not (1 <= n <= case.source_count)),
    }


def evaluate_cases(cases: list[SummaryCase], *, judge: Judge | None = None) -> SummaryMetrics:
    if not cases:
        return SummaryMetrics(
            count=0, citation_precision=0.0, coverage=0.0,
            structure_rate=0.0, citation_rate=0.0,
            faithfulness=None if judge is None else 0.0,
        )

    precisions: list[float] = []
    coverages: list[float] = []
    structure_hits = 0
    citation_hits = 0
    faithfulness_scores: list[float] = []
    failures: list[dict] = []

    for case in cases:
        s = _case_scores(case)
        precisions.append(s["citation_precision"])
        coverages.append(s["coverage"])
        structure_hits += 1 if s["structure_ok"] else 0
        citation_hits += 1 if s["has_citation"] else 0
        if judge is not None:
            faithfulness_scores.append(_clamp01(judge(case.query, case.summary, case.sources_text)))

        reasons = []
        if s["citation_precision"] < GATE_CITATION_PRECISION:
            reasons.append(f"citation_precision={s['citation_precision']:.2f} invalid={s['invalid_citations']}")
        if s["coverage"] < GATE_COVERAGE:
            reasons.append(f"coverage={s['coverage']:.2f}")
        if not s["structure_ok"]:
            reasons.append("missing_sections")
        if not s["has_citation"]:
            reasons.append("no_citation")
        if reasons:
            failures.append({"id": case.id, "query": case.query, "reasons": reasons})

    return SummaryMetrics(
        count=len(cases),
        citation_precision=mean(precisions),
        coverage=mean(coverages),
        structure_rate=structure_hits / len(cases),
        citation_rate=citation_hits / len(cases),
        faithfulness=(mean(faithfulness_scores) if judge is not None else None),
        failures=failures,
    )


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def format_metrics(metrics: SummaryMetrics) -> str:
    lines = [
        "KMU Wiki summary quality report",
        f"cases: {metrics.count}",
        f"citation_precision: {metrics.citation_precision:.3f}",
        f"coverage: {metrics.coverage:.3f}",
        f"structure_rate: {metrics.structure_rate:.3f}",
        f"citation_rate: {metrics.citation_rate:.3f}",
    ]
    if metrics.faithfulness is not None:
        lines.append(f"faithfulness: {metrics.faithfulness:.3f}")
    lines.append(f"Gate: {'PASS' if metrics.passed else 'FAIL'}")
    if metrics.failures:
        lines.append("")
        lines.append("Failures:")
        for f in metrics.failures:
            lines.append(f"- {f['id']}: {', '.join(f['reasons'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate summary quality from JSONL fixtures.")
    parser.add_argument("--cases", default="evaluation/golden/summary_quality_synth.jsonl")
    parser.add_argument("--json", help="Write machine-readable metrics.")
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    metrics = evaluate_cases(cases)
    print(format_metrics(metrics))
    if args.json:
        out = {
            "count": metrics.count,
            "citation_precision": metrics.citation_precision,
            "coverage": metrics.coverage,
            "structure_rate": metrics.structure_rate,
            "citation_rate": metrics.citation_rate,
            "faithfulness": metrics.faithfulness,
            "passed": metrics.passed,
            "failures": metrics.failures,
        }
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if metrics.passed else 1


if __name__ == "__main__":
    sys.exit(main())
