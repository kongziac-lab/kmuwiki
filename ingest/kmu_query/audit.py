"""Audit logging helpers for search/RAG access."""

from __future__ import annotations

import re

from .retriever import Source


_AUDIT_PATTERNS = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[이메일]"),
    (re.compile(r"(?<!\d)\d{6}-?[1-4]\d{6}(?!\d)"), "[주민등록번호]"),
    (re.compile(r"(?<!\d)01[016789]-?\d{3,4}-?\d{4}(?!\d)"), "[전화번호]"),
)


def sanitize_audit_query(query: str, limit: int = 500) -> str:
    value = (query or "")[:limit]
    for pattern, replacement in _AUDIT_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


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
            "query_text": sanitize_audit_query(query),
            "document_ids": document_ids[:50],
            "result_count": len(document_ids),
            "latency_ms": latency_ms,
            "rerank_provider": rerank_provider,
            "rerank_applied": rerank_applied,
        }).execute()
    except Exception:
        try:
            client.rpc("log_access", {
                "action_text": action,
                "query_text": sanitize_audit_query(query),
                "document_ids": document_ids[:50],
            }).execute()
        except Exception:
            return
