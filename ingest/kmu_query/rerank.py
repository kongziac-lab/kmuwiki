"""Optional Cohere rerank layer for search candidates."""

from __future__ import annotations

from dataclasses import dataclass

from .retriever import Source


@dataclass(frozen=True)
class RerankResult:
    sources: list[Source]
    applied: bool
    provider: str | None = None
    error: str | None = None


class CohereReranker:
    def __init__(self, api_key: str, model: str = "rerank-v3.5", timeout: float | None = None):
        import cohere

        self.model = model
        self._client = cohere.Client(api_key, timeout=timeout)

    def rerank(self, query: str, sources: list[Source], *, top_n: int) -> list[Source]:
        documents = [_document_text(source) for source in sources]
        response = self._client.rerank(
            model=self.model,
            query=query,
            documents=documents,
            top_n=min(top_n, len(documents)),
        )
        ordered: list[Source] = []
        for item in response.results:
            source = sources[int(item.index)]
            source.score = float(item.relevance_score)
            ordered.append(source)
        return ordered


def rerank_sources(
    query: str,
    sources: list[Source],
    *,
    reranker=None,
    top_n: int = 8,
    max_candidates: int = 50,
    provider: str | None = None,
) -> RerankResult:
    if not query.strip() or not sources or reranker is None:
        return RerankResult(sources=sources[:top_n], applied=False, provider=provider)
    candidates = sources[:max(1, max_candidates)]
    try:
        ranked = reranker.rerank(query, candidates, top_n=top_n)
    except Exception as exc:
        return RerankResult(
            sources=sources[:top_n],
            applied=False,
            provider=provider,
            error=f"{type(exc).__name__}: {exc}",
        )
    return RerankResult(sources=ranked[:top_n], applied=True, provider=provider)


def _document_text(source: Source) -> str:
    return "\n".join(part for part in (
        source.filename or "",
        source.dept or "",
        source.doc_no or "",
        source.doc_date or "",
        source.content or "",
    ) if part)
