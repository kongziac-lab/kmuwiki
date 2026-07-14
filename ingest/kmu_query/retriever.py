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
    zip_id: str | None = None

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


# ZIP 전체 투입(limit_per_zip=None) 시 총 문자 수 상한. 한국어 약 1자≈1토큰이므로
# 15만 자로 두면 Gemini 저가 요금 티어(프롬프트 20만 토큰)와 컨텍스트 한도를 넘지 않는다.
FULL_ZIP_CHAR_BUDGET = 150_000


class Retriever:
    def __init__(self, supabase_client, embedder):
        self.client = supabase_client
        self.embedder = embedder

    def retrieve(
        self,
        query: str,
        k: int = 8,
        dept: str | None = None,
        year: int | None = None,
    ) -> list[Source]:
        if not query or not query.strip():
            return []
        rows: list[dict] = []
        for query_text in _expanded_retrieval_queries(query):
            rows.extend(self._hybrid_rows(query_text, k, dept, year))
        sources = _dedupe_sources(_sources_from_rows(rows))
        sources.extend(self._filename_fallback_sources(query, dept=dept, year=year, limit=k))
        sources = _dedupe_sources(sources)
        sources.sort(key=lambda source: source.score, reverse=True)
        selected = sources[:k]
        # 0011+ hybrid_search returns representative metadata inline. Keep the
        # older lookup path only as a rolling-deploy compatibility fallback.
        if selected and all(source.citation_filename for source in selected):
            return selected
        return self._with_representative_citations(selected)

    def _hybrid_rows(
        self,
        query: str,
        k: int,
        dept: str | None,
        year: int | None,
    ) -> list[dict]:
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
            "filter_year": year,
        }).execute()
        return res.data or []

    def _filename_fallback_sources(
        self,
        query: str,
        *,
        dept: str | None,
        year: int | None,
        limit: int,
    ) -> list[Source]:
        terms = _filename_fallback_terms(query)
        if not terms:
            return []
        sources: list[Source] = []
        seen_docs: set[str] = set()
        for term_index, term in enumerate(terms):
            try:
                q = (
                    self.client.table("documents")
                    .select("id,filename,doc_no,doc_date,dept,doc_chunks(chunk_index,content)")
                    .eq("status", "processed")
                    .ilike("filename", f"%{term}%")
                )
                if dept:
                    q = q.eq("dept", dept)
                if year:
                    q = q.gte("doc_date", f"{year}-01-01").lt("doc_date", f"{year + 1}-01-01")
                rows = q.limit(max(limit * 2, 8)).execute().data or []
            except Exception:
                continue

            for row in rows:
                doc_id = str(row.get("id") or "")
                if not doc_id or doc_id in seen_docs:
                    continue
                seen_docs.add(doc_id)
                chunks = sorted(row.get("doc_chunks") or [], key=lambda c: int(c.get("chunk_index") or 0))
                for chunk in chunks[:3] or [{"chunk_index": 0, "content": ""}]:
                    sources.append(Source(
                        document_id=doc_id,
                        chunk_index=int(chunk.get("chunk_index") or 0),
                        content=chunk.get("content") or "",
                        score=0.08 - (0.005 * term_index),
                        filename=row.get("filename"),
                        doc_no=row.get("doc_no"),
                        doc_date=str(row["doc_date"]) if row.get("doc_date") else None,
                        dept=row.get("dept"),
                    ))
                    if len(sources) >= limit:
                        return sources
        return sources

    def expand_zip_context(
        self,
        sources: list[Source],
        *,
        limit_per_zip: int | None = 12,
        char_budget: int | None = None,
    ) -> list[Source]:
        """검색된 문서와 같은 ZIP의 대표 PDF·첨부 청크를 검증 자료로 확장한다.

        limit_per_zip=None이면 해당 ZIP의 전체 청크를 투입한다(루프 없는 전수 대조).
        이때 char_budget(기본 FULL_ZIP_CHAR_BUDGET)으로 총량을 제한해 ZIP이 커져도
        비용과 컨텍스트가 폭주하지 않게 한다. 정렬 순서상 결재문서가 첨부보다 먼저
        채워지므로 예산이 모자라면 덜 중요한 첨부부터 잘린다.
        """
        if not sources:
            return []
        if limit_per_zip is None and char_budget is None:
            char_budget = FULL_ZIP_CHAR_BUDGET
        try:
            zip_ids = sorted({str(source.zip_id) for source in sources if source.zip_id})
            if not zip_ids:
                docs = self._fetch_source_documents([s.document_id for s in sources])
                zip_ids = sorted({str(row.get("zip_id")) for row in docs.values() if row.get("zip_id")})
            if not zip_ids:
                return sources
            rows = self._fetch_zip_chunk_sources(
                zip_ids, limit_per_zip=limit_per_zip, char_budget=char_budget)
            expanded = rows
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

    def _fetch_zip_chunk_sources(
        self,
        zip_ids: list[str],
        *,
        limit_per_zip: int | None,
        char_budget: int | None = None,
    ) -> list[Source]:
        res = (
            self.client.table("documents")
            .select(
                "id,zip_id,filename,doc_no,doc_date,dept,document_kind,"
                "zip_archives(filename,source_path),doc_chunks(chunk_index,content)"
            )
            .in_("zip_id", zip_ids)
            .eq("status", "processed")
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
        for zip_id, fallback in _fallback_representatives_from_rows(zip_ids, rows).items():
            representatives.setdefault(zip_id, fallback)

        sources: list[Source] = []
        per_zip: dict[str, int] = {}
        total_chars = 0
        for row in sorted(rows, key=_zip_context_sort_key):
            zip_id = str(row.get("zip_id"))
            representative = representatives.get(zip_id, {})
            count = per_zip.get(zip_id, 0)
            if limit_per_zip is not None and count >= limit_per_zip:
                continue
            chunks = row.get("doc_chunks") or []
            for chunk in sorted(chunks, key=lambda c: int(c.get("chunk_index") or 0)):
                if limit_per_zip is not None and count >= limit_per_zip:
                    break
                content = chunk.get("content") or ""
                if char_budget is not None and sources and total_chars + len(content) > char_budget:
                    return sources
                sources.append(Source(
                    document_id=str(row["id"]),
                    chunk_index=int(chunk.get("chunk_index") or 0),
                    content=content,
                    score=0.0,
                    filename=row.get("filename"),
                    doc_no=row.get("doc_no"),
                    doc_date=str(row["doc_date"]) if row.get("doc_date") else None,
                    dept=row.get("dept"),
                    citation_filename=representative.get("filename") or row.get("filename"),
                    citation_doc_no=representative.get("doc_no") or row.get("doc_no"),
                    citation_doc_date=(str(representative["doc_date"])
                                       if representative.get("doc_date") else None),
                    citation_dept=representative.get("dept") or row.get("dept"),
                    zip_id=zip_id,
                ))
                total_chars += len(content)
                count += 1
            per_zip[zip_id] = count
        return sources


_ATTACHMENT_NAME = re.compile(r"^\s*(?:\[?\s*붙임|\d+\.\s)")


def _looks_like_attachment_name(filename) -> bool:
    """'[붙임 1] …' / '붙임 2. …' / '2. Tentative …' 류의 첨부 파일명인가."""
    return bool(filename and _ATTACHMENT_NAME.match(str(filename)))


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
    # ZIP 이름과 정확히 일치하는 기안문이 없으면(제목이 다른 결재문서) 첨부가 아닌
    # PDF 를 우선한다 — 그렇지 않으면 사전순 첫 붙임([붙임 1] …)이 대표로 뽑혀
    # 출처 라벨이 붙임 파일명으로 표기된다.
    main_docs = [row for row in pdfs if not _looks_like_attachment_name(row.get("filename"))]
    candidates = exact or main_docs or pdfs
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


def _fallback_representatives_from_rows(zip_ids: list[str], rows: list[dict]) -> dict[str, dict]:
    return _fallback_representatives(
        zip_ids,
        {str(row.get("id") or index): row for index, row in enumerate(rows)},
    )


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


def _sources_from_rows(rows: list[dict]) -> list[Source]:
    return [Source(
        document_id=str(r["document_id"]),
        chunk_index=r.get("chunk_index", 0),
        content=r.get("content", ""),
        score=float(r.get("score", 0.0)),
        filename=r.get("filename"),
        doc_no=r.get("doc_no"),
        doc_date=str(r["doc_date"]) if r.get("doc_date") else None,
        dept=r.get("dept"),
        citation_filename=r.get("citation_filename"),
        citation_doc_no=r.get("citation_doc_no"),
        citation_doc_date=(str(r["citation_doc_date"])
                           if r.get("citation_doc_date") else None),
        citation_dept=r.get("citation_dept"),
        zip_id=str(r["zip_id"]) if r.get("zip_id") else None,
    ) for r in rows]


def _dedupe_sources(sources: list[Source]) -> list[Source]:
    by_key: dict[tuple[str, int], Source] = {}
    for source in sources:
        key = (source.document_id, source.chunk_index)
        existing = by_key.get(key)
        if existing is None or source.score > existing.score:
            by_key[key] = source
    return list(by_key.values())


def _expanded_retrieval_queries(query: str) -> tuple[str, ...]:
    queries = [query.strip()]
    compact = re.sub(r"\s+", "", query)
    if _is_busan_china_consulate_query(compact):
        queries.extend([
            "주부산중국총영사",
            "주부산중국부총영사",
            "주부산중국총영사 내방",
            "주부산중국부총영사 내방",
        ])
    return tuple(dict.fromkeys(q for q in queries if q))


def _filename_fallback_terms(query: str) -> tuple[str, ...]:
    compact = re.sub(r"\s+", "", query)
    if not _is_busan_china_consulate_query(compact):
        return ()
    return ("주부산중국총영사", "주부산중국부총영사")


def _is_busan_china_consulate_query(compact_query: str) -> bool:
    return (
        "주부산중국총영사관" in compact_query
        or "주부산중국총영사" in compact_query
        or "주부산중국부총영사" in compact_query
        or ("중국" in compact_query and "총영사관" in compact_query)
    )


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
