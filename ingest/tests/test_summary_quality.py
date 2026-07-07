import unittest
from pathlib import Path

from evaluation.summary_quality import (
    SummaryCase,
    evaluate_cases,
    format_metrics,
    load_cases,
)

ROOT = Path(__file__).resolve().parents[2]


class TestSummaryQualityHarness(unittest.TestCase):
    def test_golden_set_passes_gate(self):
        cases = load_cases(ROOT / "ingest/evaluation/golden/summary_quality_synth.jsonl")
        metrics = evaluate_cases(cases)
        report = format_metrics(metrics)

        self.assertEqual(metrics.count, 5)
        self.assertEqual(metrics.citation_precision, 1.0)
        self.assertEqual(metrics.structure_rate, 1.0)
        self.assertEqual(metrics.citation_rate, 1.0)
        self.assertGreaterEqual(metrics.coverage, 0.60)
        self.assertIsNone(metrics.faithfulness)  # judge 미주입 → None
        self.assertTrue(metrics.passed)
        self.assertIn("Gate: PASS", report)

    def test_hallucinated_citation_fails_precision(self):
        # 출처가 2개인데 [3] 을 인용 → 유효 인용 1/2 = 0.5 < 0.95
        case = SummaryCase(
            id="halluc", query="q", source_count=2, relevant_ns=(1,),
            summary=(
                "## 한눈에 보기\n요약 [1].\n## 핵심 내용\n- 근거 [3].\n"
                "## 주요 일정·수치\n- 해당 없음\n## 확인이 필요한 점\n- 없음"
            ),
        )
        metrics = evaluate_cases([case])
        self.assertAlmostEqual(metrics.citation_precision, 0.5)
        self.assertFalse(metrics.passed)
        self.assertEqual(metrics.failures[0]["id"], "halluc")
        self.assertTrue(any("citation_precision" in r for r in metrics.failures[0]["reasons"]))

    def test_missing_section_fails_structure(self):
        case = SummaryCase(
            id="nostruct", query="q", source_count=1, relevant_ns=(1,),
            summary="핵심만 [1] 적었고 섹션 헤더가 없다.",
        )
        metrics = evaluate_cases([case])
        self.assertEqual(metrics.structure_rate, 0.0)
        self.assertFalse(metrics.passed)

    def test_low_coverage_fails(self):
        # 핵심 출처 1,2 인데 1만 인용 → coverage 0.5 < 0.6
        case = SummaryCase(
            id="lowcov", query="q", source_count=3, relevant_ns=(1, 2),
            summary=(
                "## 한눈에 보기\n요약 [1].\n## 핵심 내용\n- 근거 [1].\n"
                "## 주요 일정·수치\n- 해당 없음\n## 확인이 필요한 점\n- 없음"
            ),
        )
        metrics = evaluate_cases([case])
        self.assertAlmostEqual(metrics.coverage, 0.5)
        self.assertFalse(metrics.passed)

    def test_injected_judge_computes_faithfulness_and_gates(self):
        cases = load_cases(ROOT / "ingest/evaluation/golden/summary_quality_synth.jsonl")

        high = evaluate_cases(cases, judge=lambda q, s, src: 1.0)
        self.assertEqual(high.faithfulness, 1.0)
        self.assertTrue(high.passed)

        low = evaluate_cases(cases, judge=lambda q, s, src: 0.1)
        self.assertEqual(low.faithfulness, 0.1)
        self.assertFalse(low.passed)  # faithfulness 게이트 미달

    def test_empty_cases_safe(self):
        metrics = evaluate_cases([])
        self.assertEqual(metrics.count, 0)
        self.assertFalse(metrics.passed)


if __name__ == "__main__":
    unittest.main()
