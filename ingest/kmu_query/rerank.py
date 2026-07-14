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
    def __init__(self, api_key: str, model: str = "rerank-v4.0-fast", timeout: float | None = None):
        import cohere

        self.model = model
        self._client = cohere.ClientV2(api_key, timeout=timeout)

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
    # Rerank v4 is text-only.  Visual hits therefore carry their masked
    # OCR/Markdown/caption surrogate as structured YAML-like text.
    metadata = (
        ("filename", source.filename),
        ("department", source.dept),
        ("document_number", source.doc_no),
        ("document_date", source.doc_date),
        ("modality", source.modality),
        ("asset_type", source.asset_type),
        ("page", source.page_no),
    )
    lines = [f"{key}: {value}" for key, value in metadata if value not in (None, "")]
    if source.content:
        lines.append("content: |")
        lines.extend(f"  {line}" for line in source.content.splitlines())
    return "\n".join(lines)
