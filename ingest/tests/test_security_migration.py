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

    def test_multimodal_v2_preserves_document_authority_and_rls(self):
        sql = (ROOT / "supabase/migrations/0012_multimodal_v2.sql").read_text(
            encoding="utf-8",
        ).lower()

        self.assertIn("create table if not exists document_assets", sql)
        self.assertIn("create table if not exists search_units", sql)
        self.assertIn("embedding          vector(1024) not null", sql)
        self.assertIn("alter table document_assets enable row level security", sql)
        self.assertIn("alter table search_units enable row level security", sql)
        self.assertIn("d.security_level = '일반'", sql)
        self.assertIn("d.status = 'processed'", sql)
        self.assertIn("'kmuwiki-assets', 'kmuwiki-assets', false", sql)
        self.assertIn("create or replace function replace_document_index_v2", sql)
        self.assertIn("grant execute on function replace_document_index_v2", sql)
        self.assertIn("to service_role", sql)
        self.assertIn("create or replace function hybrid_search_v2", sql)
        self.assertNotIn("drop table doc_chunks", sql)


if __name__ == "__main__":
    unittest.main()
