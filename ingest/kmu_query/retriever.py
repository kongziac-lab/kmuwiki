"""검색기 — 쿼리 임베딩 + 하이브리드 검색(RLS 적용).

Supabase 클라이언트는 '호출 사용자의 JWT'로 인증되어야 RLS가 적용된다(권한 강제).
검색기는 클라이언트/임베더를 주입받아 테스트 가능하게 둔다.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
import re


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
    citation_filename: str | None = None
    citation_doc_no: str | None = None
    citation_doc_date: str | None = None
    citation_dept: str | None = None

    def label(self) -> str:
        """인용 표기용 짧은 출처 라벨."""
        dept = self.citation_dept or self.dept
        doc_no = self.citation_doc_no or self.doc_no
        if dept and doc_no and doc_no.startswith(f"{dept}-"):
            dept = None
        bits = [b for b in (
            dept,
            doc_no,
            self.citation_doc_date or self.doc_date,
            self.citation_filename or self.filename,
        ) if b]
        return " · ".join(bits) if bits else f"문서 {self.document_id[:8]}"


class Retriever:
    def __init__(self, supabase_client, embedder):
        self.client = supabase_client
        self.embedder = embedder

    def retrieve(self, query: str, k: int = 8, dept: str | None = None) -> list[Source]:
        if not query or not query.strip():
            return []
        # 쿼리 전용 임베딩(Cohere 등은 search_query input_type 사용)
        if hasattr(self.embedder, "embed_query"):
            vec = self.embedder.embed_query(query)
        else:
            vec = self.embedder.embed([query])[0]
        res = self.client.rpc("hybrid_search", {
            "query_embedding": vec,
            "query_text": query,
            "match_count": k,
            "filter_dept": dept,
        }).execute()
        rows = res.data or []
        sources = [Source(
            document_id=str(r["document_id"]),
            chunk_index=r.get("chunk_index", 0),
            content=r.get("content", ""),
            score=float(r.get("score", 0.0)),
            filename=r.get("filename"),
            doc_no=r.get("doc_no"),
            doc_date=str(r["doc_date"]) if r.get("doc_date") else None,
            dept=r.get("dept"),
        ) for r in rows]
        return self._with_representative_citations(sources)

    def expand_zip_context(self, sources: list[Source], *, limit_per_zip: int = 12) -> list[Source]:
        """검색된 문서와 같은 ZIP의 대표 PDF·첨부 청크를 검증 자료로 확장한다."""
        if not sources:
            return []
        try:
            docs = self._fetch_source_documents([s.document_id for s in sources])
            zip_ids = sorted({str(row.get("zip_id")) for row in docs.values() if row.get("zip_id")})
            if not zip_ids:
                return sources
            rows = self._fetch_zip_chunk_sources(zip_ids, limit_per_zip=limit_per_zip)
            expanded = self._with_representative_citations(rows)
        except Exception:
            return sources

        by_id_chunk = {(s.document_id, s.chunk_index): s for s in sources}
        for source in expanded:
            by_id_chunk.setdefault((source.document_id, source.chunk_index), source)
        return list(by_id_chunk.values())

    def _with_representative_citations(self, sources: list[Source]) -> list[Source]:
        """첨부 검색 결과의 인용 라벨을 같은 ZIP의 대표 결재 PDF로 보정한다.

        ZIP 안에는 ZIP 파일명과 같은 PDF 결재문이 있고 그 문서에 문서번호가
        있다는 운영 규칙을 우선한다. 실패하면 원래 검색 결과 메타데이터를 둔다.
        """
        if not sources:
            return sources
        try:
            docs = self._fetch_source_documents([s.document_id for s in sources])
            zip_ids = sorted({str(row.get("zip_id")) for row in docs.values() if row.get("zip_id")})
            if not zip_ids:
                return sources
            reps = self._fetch_representative_documents(zip_ids, docs)
        except Exception:
            return sources

        for source in sources:
            doc = docs.get(source.document_id)
            zip_id = str(doc.get("zip_id")) if doc and doc.get("zip_id") else None
            rep = reps.get(zip_id or "")
            if not rep:
                continue
            source.citation_filename = rep.get("filename")
            source.citation_doc_no = rep.get("doc_no")
            source.citation_doc_date = str(rep["doc_date"]) if rep.get("doc_date") else None
            source.citation_dept = rep.get("dept")
        return sources

    def _fetch_source_documents(self, document_ids: list[str]) -> dict[str, dict]:
        res = (
            self.client.table("documents")
            .select("id,zip_id,zip_archives(filename,source_path)")
            .in_("id", document_ids)
            .execute()
        )
        return {str(row["id"]): row for row in (res.data or [])}

    def _fetch_representative_documents(self, zip_ids: list[str], source_docs: dict[str, dict]) -> dict[str, dict]:
        res = (
            self.client.table("documents")
            .select("id,zip_id,filename,doc_no,doc_date,dept,zip_archives(filename,source_path)")
            .in_("zip_id", zip_ids)
            .execute()
        )
        rows = res.data or []
        by_zip: dict[str, list[dict]] = {}
        for row in rows:
            by_zip.setdefault(str(row.get("zip_id")), []).append(row)
        representatives = {
            zip_id: rep
            for zip_id, group in by_zip.items()
            if (rep := _representative_pdf(group)) is not None
        }
        for zip_id, fallback in _fallback_representatives(zip_ids, source_docs).items():
            representatives.setdefault(zip_id, fallback)
        return representatives

    def _fetch_zip_chunk_sources(self, zip_ids: list[str], *, limit_per_zip: int) -> list[Source]:
        res = (
            self.client.table("documents")
            .select("id,zip_id,filename,doc_no,doc_date,dept,doc_chunks(chunk_index,content)")
            .in_("zip_id", zip_ids)
            .eq("status", "processed")
            .execute()
        )
        sources: list[Source] = []
        per_zip: dict[str, int] = {}
        for row in sorted(res.data or [], key=_zip_context_sort_key):
            zip_id = str(row.get("zip_id"))
            count = per_zip.get(zip_id, 0)
            if count >= limit_per_zip:
                continue
            chunks = row.get("doc_chunks") or []
            for chunk in sorted(chunks, key=lambda c: int(c.get("chunk_index") or 0)):
                if count >= limit_per_zip:
                    break
                sources.append(Source(
                    document_id=str(row["id"]),
                    chunk_index=int(chunk.get("chunk_index") or 0),
                    content=chunk.get("content") or "",
                    score=0.0,
                    filename=row.get("filename"),
                    doc_no=row.get("doc_no"),
                    doc_date=str(row["doc_date"]) if row.get("doc_date") else None,
                    dept=row.get("dept"),
                ))
                count += 1
            per_zip[zip_id] = count
        return sources


def _representative_pdf(rows: list[dict]) -> dict | None:
    pdfs = [row for row in rows if _is_pdf(row.get("filename")) and row.get("doc_no")]
    if not pdfs:
        return None

    zip_stems = {
        _stem(name)
        for row in rows
        for name in _zip_names(row.get("zip_archives"))
        if _stem(name)
    }
    exact = [row for row in pdfs if _stem(row.get("filename")) in zip_stems]
    candidates = exact or pdfs
    return sorted(
        candidates,
        key=lambda row: (
            0 if _stem(row.get("filename")) in zip_stems else 1,
            str(row.get("doc_date") or "9999-12-31"),
            str(row.get("filename") or ""),
        ),
    )[0]


def _fallback_representatives(zip_ids: list[str], source_docs: dict[str, dict]) -> dict[str, dict]:
    """대표 PDF 행이 DB에 없을 때 ZIP 파일명으로 표시용 대표 PDF명을 복원한다."""
    fallbacks: dict[str, dict] = {}
    for zip_id in zip_ids:
        docs = [row for row in source_docs.values() if str(row.get("zip_id")) == zip_id]
        names = [name for row in docs for name in _zip_names(row.get("zip_archives"))]
        stem = next((_stem(name) for name in names if _stem(name)), "")
        display = next((_display_stem(name) for name in names if _display_stem(name)), "")
        if not stem or not display:
            continue
        fallbacks[zip_id] = {"filename": f"{display}.pdf"}
    return fallbacks


def _zip_context_sort_key(row: dict) -> tuple:
    filename = str(row.get("filename") or "")
    has_doc_no = 0 if row.get("doc_no") else 1
    is_pdf = 0 if _is_pdf(filename) else 1
    is_attachment = 1 if filename.startswith(("붙임", "[붙임")) else 0
    return (str(row.get("zip_id") or ""), has_doc_no, is_pdf, is_attachment, filename)


def _zip_names(zip_archive) -> list[str]:
    if isinstance(zip_archive, dict):
        return [name for name in (zip_archive.get("filename"), zip_archive.get("source_path")) if name]
    return []


def _is_pdf(filename: str | None) -> bool:
    return bool(filename and filename.lower().endswith(".pdf"))


def _stem(name: str | None) -> str:
    if not name:
        return ""
    filename = str(name).replace("\\", "/").split("/")[-1]
    filename = PurePosixPath(PureWindowsPath(filename).name).name
    filename = re.sub(r"\.(zip|pdf)$", "", filename, flags=re.IGNORECASE)
    return re.sub(r"\s+", "", filename).lower()


def _display_stem(name: str | None) -> str:
    if not name:
        return ""
    filename = str(name).replace("\\", "/").split("/")[-1]
    filename = PurePosixPath(PureWindowsPath(filename).name).name
    filename = re.sub(r"\.(zip|pdf)$", "", filename, flags=re.IGNORECASE)
    return filename.strip()
