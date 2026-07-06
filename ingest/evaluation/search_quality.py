"""Search quality harness for KMU Wiki retrieval experiments.

The harness intentionally works on plain JSONL so it can measure either live
retriever output or deterministic fixtures in CI. Each query item names one or
more relevant document ids and one ranked retrieval result list.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean


@dataclass(frozen=True)
class SearchCase:
    id: str
    query: str
    relevant_ids: tuple[str, ...]
    retrieved_ids: tuple[str, ...] = ()
    dept: str | None = None
    year: int | None = None
    intent: str = "general"


@dataclass
class SearchMetrics:
    count: int
    recall_at: dict[int, float]
    mrr: float
    misses: list[dict] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.recall_at.get(5, 0.0) >= 0.80 and self.recall_at.get(10, 0.0) >= 0.90


def load_cases(path: str | Path) -> list[SearchCase]:
    cases: list[SearchCase] = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            cases.append(SearchCase(
                id=str(row["id"]),
                query=str(row["query"]),
                relevant_ids=tuple(str(v) for v in row.get("relevant_ids", [])),
                retrieved_ids=tuple(str(v) for v in row.get("retrieved_ids", [])),
                dept=row.get("dept"),
                year=row.get("year"),
                intent=row.get("intent") or "general",
            ))
    return cases


def evaluate_cases(cases: list[SearchCase], ks: tuple[int, ...] = (5, 10)) -> SearchMetrics:
    if not cases:
        return SearchMetrics(count=0, recall_at={k: 0.0 for k in ks}, mrr=0.0)

    recall_hits = {k: 0 for k in ks}
    reciprocal_ranks: list[float] = []
    misses: list[dict] = []

    for case in cases:
        relevant = set(case.relevant_ids)
        retrieved = list(case.retrieved_ids)
        first_rank = next((i + 1 for i, doc_id in enumerate(retrieved) if doc_id in relevant), None)
        reciprocal_ranks.append(1.0 / first_rank if first_rank else 0.0)
        for k in ks:
            if relevant.intersection(retrieved[:k]):
                recall_hits[k] += 1
        if first_rank is None:
            misses.append({
                "id": case.id,
                "query": case.query,
                "relevant_ids": sorted(relevant),
                "retrieved_ids": retrieved[:max(ks)],
            })

    return SearchMetrics(
        count=len(cases),
        recall_at={k: recall_hits[k] / len(cases) for k in ks},
        mrr=mean(reciprocal_ranks),
        misses=misses,
    )


def format_metrics(metrics: SearchMetrics) -> str:
    lines = [
        "KMU Wiki search quality report",
        f"cases: {metrics.count}",
        *(f"Recall@{k}: {v:.3f}" for k, v in sorted(metrics.recall_at.items())),
        f"MRR: {metrics.mrr:.3f}",
        f"Gate: {'PASS' if metrics.passed else 'FAIL'}",
    ]
    if metrics.misses:
        lines.append("")
        lines.append("Misses:")
        for miss in metrics.misses:
            lines.append(f"- {miss['id']}: {miss['query']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality from JSONL fixtures.")
    parser.add_argument("--cases", default="evaluation/golden/search_quality_synth.jsonl")
    parser.add_argument("--json", help="Write machine-readable metrics.")
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    metrics = evaluate_cases(cases)
    print(format_metrics(metrics))
    if args.json:
        out = {
            "count": metrics.count,
            "recall_at": metrics.recall_at,
            "mrr": metrics.mrr,
            "passed": metrics.passed,
            "misses": metrics.misses,
        }
        Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if metrics.passed else 1


if __name__ == "__main__":
    sys.exit(main())
