from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class TestSearchQualityMigration(unittest.TestCase):
    def test_metadata_rerank_and_monitoring_schema_exists(self):
        sql = (ROOT / "supabase/migrations/0009_search_quality_metadata.sql").read_text(
            encoding="utf-8"
        )

        self.assertIn("attachment_names text[]", sql)
        self.assertIn("document_kind text", sql)
        self.assertIn("section_type text", sql)
        self.assertIn("rerank_applied boolean", sql)
        self.assertIn("search_quality_reports", sql)
        self.assertIn("admin_search_monitoring_summary", sql)
        self.assertIn("log_search_event", sql)


if __name__ == "__main__":
    unittest.main()
