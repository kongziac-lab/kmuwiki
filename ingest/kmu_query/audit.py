"""Audit logging helpers for search/RAG access."""

from __future__ import annotations

from .retriever import Source


def log_access(
    client,
    *,
    action: str,
    query: str,
    sources: list[Source],
    latency_ms: int | None = None,
    rerank_provider: str | None = None,
    rerank_applied: bool = False,
) -> None:
    """Write access audit rows through the database RPC.

    Audit failure must never break the user request path, so errors are swallowed.
    The database function records auth.uid(); the service only supplies action/query/doc ids.
    """
    seen: set[str] = set()
    document_ids: list[str] = []
    for source in sources:
        if source.document_id in seen:
            continue
        seen.add(source.document_id)
        document_ids.append(source.document_id)
    try:
        client.rpc("log_search_event", {
            "action_text": action,
            "query_text": query,
            "document_ids": document_ids,
            "result_count": len(document_ids),
            "latency_ms": latency_ms,
            "rerank_provider": rerank_provider,
            "rerank_applied": rerank_applied,
        }).execute()
    except Exception:
        try:
            client.rpc("log_access", {
                "action_text": action,
                "query_text": query,
                "document_ids": document_ids,
            }).execute()
        except Exception:
            return
