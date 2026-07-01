from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
failures: list[str] = []


def check(name: str, condition: bool) -> None:
    if condition:
        print(f"[OK] {name}")
    else:
        print(f"[FAIL] {name}")
        failures.append(name)


def contains(path: str, needle: str) -> bool:
    return needle in (ROOT / path).read_text(encoding="utf-8")


def main() -> int:
    vercel = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    services = vercel.get("experimentalServices") or {}
    web = services.get("web") or {}
    rag = services.get("rag") or {}

    check("Vercel serves Next.js web at /", web.get("entrypoint") == "web" and web.get("routePrefix") == "/")
    check(
        "Vercel serves Python RAG API at /rag",
        rag.get("entrypoint") == "ingest/main.py" and rag.get("routePrefix") == "/rag",
    )

    sql_path = "supabase/migrations/0008_operational_guardrails.sql"
    check("dept/year processed document index exists", contains(sql_path, "idx_documents_processed_dept_doc_date"))
    check("document chunk foreign-key index exists", contains(sql_path, "idx_doc_chunks_document_id"))
    check("access log user/time index exists", contains(sql_path, "idx_access_log_user_at"))
    check("hybrid search accepts filter_year", contains(sql_path, "filter_year int default null"))
    check("hybrid search clamps result k to 20", contains(sql_path, "least(coalesce(match_count, 8), 20)"))
    check("hybrid search clamps candidate pool to 80", contains(sql_path, "least(coalesce(pool, 50), 80)"))
    check("audit cleanup RPC exists", contains(sql_path, "create or replace function cleanup_access_log"))
    check("storage health RPC exists", contains(sql_path, "create or replace function admin_storage_health"))
    check("pgvector HNSW index health is reported", contains(sql_path, "'pgvector_hnsw'"))

    check("chunk limit env setting exists", contains("ingest/kmu_ingest/config.py", "KMU_MAX_CHUNKS_PER_DOC"))
    check("API k limit env setting exists", contains("ingest/kmu_ingest/config.py", "KMU_API_MAX_K"))
    check("pipeline enforces max_chunks_per_doc", contains("ingest/kmu_ingest/pipeline.py", "deps.settings.max_chunks_per_doc"))
    check("service clamps request k", contains("ingest/kmu_query/service.py", "def _bounded_k"))
    check("service extracts target year", contains("ingest/kmu_query/service.py", "def _target_year"))
    check("retriever passes year filter to DB", contains("ingest/kmu_query/retriever.py", '"filter_year": year'))

    if failures:
        print("\nGuardrail verification failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nOperational guardrail verification passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
