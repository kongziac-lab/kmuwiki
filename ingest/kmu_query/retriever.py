"""검색기 — 쿼리 임베딩 + 하이브리드 검색(RLS 적용).

Supabase 클라이언트는 '호출 사용자의 JWT'로 인증되어야 RLS가 적용된다(권한 강제).
검색기는 클라이언트/임베더를 주입받아 테스트 가능하게 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Source:
    document_id: str
    chunk_index: int
    content: str            # 마스킹된 본문
    score: float
    filename: str | None = None
    doc_no: str | None = None
    doc_date: str | None = None
    dept: str | None = None

    def label(self) -> str:
        """인용 표기용 짧은 출처 라벨."""
        bits = [b for b in (self.dept, self.doc_no, self.doc_date, self.filename) if b]
        return " · ".join(bits) if bits else f"문서 {self.document_id[:8]}"


class Retriever:
    def __init__(self, supabase_client, embedder):
        self.client = supabase_client
        self.embedder = embedder

    def retrieve(self, query: str, k: int = 8, dept: str | None = None) -> list[Source]:
        if not query or not query.strip():
            return []
        vec = self.embedder.embed([query])[0]
        res = self.client.rpc("hybrid_search", {
            "query_embedding": vec,
            "query_text": query,
            "match_count": k,
            "filter_dept": dept,
        }).execute()
        rows = res.data or []
        return [Source(
            document_id=str(r["document_id"]),
            chunk_index=r.get("chunk_index", 0),
            content=r.get("content", ""),
            score=float(r.get("score", 0.0)),
            filename=r.get("filename"),
            doc_no=r.get("doc_no"),
            doc_date=str(r["doc_date"]) if r.get("doc_date") else None,
            dept=r.get("dept"),
        ) for r in rows]
