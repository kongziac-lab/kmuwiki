from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))

from evaluation.search_quality import evaluate_cases, format_metrics, load_cases  # noqa: E402


def main() -> int:
    cases = load_cases(ROOT / "ingest/evaluation/golden/search_quality_synth.jsonl")
    metrics = evaluate_cases(cases)
    print(format_metrics(metrics))
    return 0 if metrics.passed else 1


if __name__ == "__main__":
    sys.exit(main())
