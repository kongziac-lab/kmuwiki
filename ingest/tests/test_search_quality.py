import unittest
from pathlib import Path

from evaluation.search_quality import evaluate_cases, format_metrics, load_cases


ROOT = Path(__file__).resolve().parents[2]


class TestSearchQualityHarness(unittest.TestCase):
    def test_evaluates_recall_and_mrr_from_jsonl(self):
        cases = load_cases(ROOT / "ingest/evaluation/golden/search_quality_synth.jsonl")

        metrics = evaluate_cases(cases)
        report = format_metrics(metrics)

        self.assertEqual(metrics.count, 5)
        self.assertEqual(metrics.recall_at[5], 1.0)
        self.assertEqual(metrics.recall_at[10], 1.0)
        self.assertGreaterEqual(metrics.mrr, 0.9)
        self.assertTrue(metrics.passed)
        self.assertIn("Recall@5: 1.000", report)

    def test_reports_misses(self):
        path = ROOT / ".tmp_search_quality_cases.jsonl"
        try:
            path.write_text(
                '{"id":"miss","query":"q","relevant_ids":["a"],"retrieved_ids":["b","c"]}\n',
                encoding="utf-8",
            )
            metrics = evaluate_cases(load_cases(path))
        finally:
            if path.exists():
                path.unlink()

        self.assertEqual(metrics.recall_at[5], 0.0)
        self.assertEqual(metrics.mrr, 0.0)
        self.assertEqual(metrics.misses[0]["id"], "miss")
        self.assertFalse(metrics.passed)


if __name__ == "__main__":
    unittest.main()
