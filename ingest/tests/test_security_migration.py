from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class TestSecurityMigration(unittest.TestCase):
    def test_rate_limit_audit_retention_and_search_indexes_are_defined(self):
        sql = (ROOT / "supabase/migrations/0011_security_performance_guardrails.sql").read_text(
            encoding="utf-8",
        ).lower()

        self.assertIn("consume_api_rate_limit", sql)
        self.assertIn("security definer", sql)
        self.assertIn("auth.uid()", sql)
        self.assertIn("regexp_replace", sql)
        self.assertIn("idx_documents_zip_id", sql)
        self.assertIn("d.doc_date >= b.year_start", sql)
        self.assertNotIn("extract(year from d.doc_date)", sql)
        self.assertIn("cron.schedule", sql)
        self.assertIn("delete from public.access_log", sql)


if __name__ == "__main__":
    unittest.main()
