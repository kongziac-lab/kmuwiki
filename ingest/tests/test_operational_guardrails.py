import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class TestOperationalGuardrails(unittest.TestCase):
    def test_vercel_services_split_web_and_rag(self):
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
        services = config.get("experimentalServices") or {}

        self.assertEqual(services["web"]["entrypoint"], "web")
        self.assertEqual(services["web"]["routePrefix"], "/")
        self.assertEqual(services["rag"]["entrypoint"], "ingest/main.py")
        self.assertEqual(services["rag"]["routePrefix"], "/rag")

    def test_supabase_migration_has_operational_rpc_and_indexes(self):
        sql = (ROOT / "supabase/migrations/0008_operational_guardrails.sql").read_text(
            encoding="utf-8"
        )

        self.assertIn("idx_documents_processed_dept_doc_date", sql)
        self.assertIn("idx_doc_chunks_document_id", sql)
        self.assertIn("idx_access_log_user_at", sql)
        self.assertIn("filter_year int default null", sql)
        self.assertIn("least(coalesce(pool, 50), 80)", sql)
        self.assertIn("create or replace function cleanup_access_log", sql)
        self.assertIn("create or replace function admin_storage_health", sql)
        self.assertIn("'pgvector_hnsw'", sql)

    def test_rerank_candidate_pool_migration_raises_match_count_clamp(self):
        sql = (ROOT / "supabase/migrations/0010_rerank_candidate_pool.sql").read_text(
            encoding="utf-8"
        )
        # 후보 상한을 20 → 60 으로 올리고, 사용되지 않는 6-인자 오버로드를 정리한다.
        self.assertIn("least(coalesce(match_count, 8), 60)", sql)
        self.assertIn("drop function if exists hybrid_search(vector, text, int, int, int, text)", sql)

    def test_runtime_code_exposes_chunk_and_search_limits(self):
        config = (ROOT / "ingest/kmu_ingest/config.py").read_text(encoding="utf-8")
        pipeline = (ROOT / "ingest/kmu_ingest/pipeline.py").read_text(encoding="utf-8")
        service = (ROOT / "ingest/kmu_query/service.py").read_text(encoding="utf-8")
        retriever = (ROOT / "ingest/kmu_query/retriever.py").read_text(encoding="utf-8")

        self.assertIn("KMU_MAX_CHUNKS_PER_DOC", config)
        self.assertIn("KMU_API_MAX_K", config)
        self.assertIn("KMU_AUDIT_RETENTION_DAYS", config)
        self.assertIn("deps.settings.max_chunks_per_doc", pipeline)
        self.assertIn("def _bounded_k", service)
        self.assertIn("def _target_year", service)
        self.assertIn('"filter_year": year', retriever)


if __name__ == "__main__":
    unittest.main()
