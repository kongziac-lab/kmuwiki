from kmu_ingest.config import load_settings
from kmu_ingest.embedding import CohereEmbedder
from kmu_query import rag
from kmu_query.retriever import Retriever
from kmu_query.source_quality import refine_sources
from kmu_query.verification import build_verification_memo, focus_sources
from supabase import create_client


def main() -> int:
    settings = load_settings()
    client = create_client(settings.supabase_url, settings.supabase_service_key)
    embedder = CohereEmbedder(settings.embed_model, settings.embed_version, api_key=settings.cohere_api_key)
    retriever = Retriever(client, embedder)

    query = "공자아카데미 이사회는 언제 개최되었나?"
    raw = retriever.retrieve(query, 24)
    refined = refine_sources(query, raw, limit=8)
    focused = focus_sources(query, refined)
    expanded = retriever.expand_zip_context(focused)
    memo = build_verification_memo(query, expanded)
    answer = "".join(rag.stream_answer(query, expanded, provider="anthropic", model="unused"))
    citations = rag.citations(expanded)

    print("raw", len(raw), "refined", len(refined), "focused", len(focused), "expanded", len(expanded))
    print(memo.to_prompt_block())
    print("ANSWER:", answer)
    print("CITATIONS:")
    for citation in citations:
        print(f"[{citation['n']}] {citation['label']}")

    if memo.query_type != "date":
        raise SystemExit("expected date verification")
    if "단정할 수 없습니다" not in answer:
        raise SystemExit("answer did not downgrade uncertain event date")
    if "2026년 5월 30일" in answer:
        raise SystemExit("unrelated event date leaked into answer")
    if "2026-06-26" not in answer:
        raise SystemExit("representative document date missing")
    if not citations or "제20회 계명공자아카데미 이사회 개최.pdf" not in citations[0]["label"]:
        raise SystemExit("representative citation missing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
