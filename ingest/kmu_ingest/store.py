"""Supabase 적재 어댑터.

인제스트 워커는 service_role 키로 RLS를 우회한다(서버 전용; 클라이언트 노출 금지).
DryRunStore 는 DB 없이 파이프라인을 끝까지 돌려보기 위한 콘솔 출력 구현.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .config import Settings
from .backfill import BACKFILL_STATUSES, backfill_candidates
from .models import Chunk, FileMeta


class DryRunStore:
    """DB 미적재. 멱등성 검사용 인메모리 집합 + 요약 출력."""

    def __init__(self) -> None:
        self._zips: set[str] = set()
        self._docs: dict[str, str] = {}  # sha256 -> status

    def zip_seen(self, sha256: str) -> bool:
        return sha256 in self._zips

    def register_zip(self, filename: str, sha256: str, file_count: int, *, source_path: str | None = None) -> str:
        self._zips.add(sha256)
        return f"dryrun-zip-{sha256[:8]}"

    def document_status(self, sha256: str) -> str | None:
        return self._docs.get(sha256)

    def upsert_document(
        self, *, sha256: str, zip_id: str, meta: FileMeta, status: str,
        is_encrypted: bool = False, error: str | None = None,
    ) -> str:
        self._docs[sha256] = status
        print(f"  [doc] {meta.path_in_zip} -> {status}"
              + f" (task={meta.task_category}, review={meta.review_required})"
              + (f" (enc, dept={meta.dept}, sec={meta.security_level})" if is_encrypted else ""))
        return f"dryrun-doc-{sha256[:8]}"

    def insert_chunks(
        self, document_id: str, chunks: list[Chunk],
        embeddings: list[list[float]], model: str, version: str,
    ) -> None:
        print(f"  [chunks] {len(chunks)}개 임베딩 적재 (model={model}/{version}, dim={len(embeddings[0]) if embeddings else 0})")

    def list_backfill_candidates(self, limit: int = 100):
        return []


class SupabaseStore:
    """실제 Supabase 적재. supabase-py 필요."""

    def __init__(self, settings: Settings):
        from supabase import create_client  # lazy

        if not settings.supabase_url or not settings.supabase_service_key:
            raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 가 필요합니다.")
        self.c = create_client(settings.supabase_url, settings.supabase_service_key)

    def zip_seen(self, sha256: str) -> bool:
        r = self.c.table("zip_archives").select("id").eq("sha256", sha256).execute()
        return bool(r.data)

    def register_zip(self, filename: str, sha256: str, file_count: int, *, source_path: str | None = None) -> str:
        r = (self.c.table("zip_archives")
             .upsert({
                 "filename": filename,
                 "sha256": sha256,
                 "file_count": file_count,
                 "source_path": source_path or filename,
             },
                     on_conflict="sha256")
             .execute())
        return r.data[0]["id"]

    def document_status(self, sha256: str) -> str | None:
        r = self.c.table("documents").select("status").eq("sha256", sha256).execute()
        return r.data[0]["status"] if r.data else None

    def upsert_document(
        self, *, sha256: str, zip_id: str, meta: FileMeta, status: str,
        is_encrypted: bool = False, error: str | None = None,
    ) -> str:
        row = {
            "sha256": sha256, "zip_id": zip_id,
            "filename": meta.filename, "path_in_zip": meta.path_in_zip,
            "mime_type": meta.mime_type, "is_encrypted": is_encrypted,
            "status": status, "dept": meta.dept, "security_level": meta.security_level,
            "task_category": meta.task_category,
            "classification_confidence": meta.classification_confidence,
            "review_required": meta.review_required,
            "doc_no": meta.doc_no, "author": meta.author, "version": meta.version,
            "doc_date": meta.doc_date.isoformat() if meta.doc_date else None,
            "error": error,
            "processed_at": datetime.now(timezone.utc).isoformat()
            if status == "processed" else None,
        }
        r = self.c.table("documents").upsert(row, on_conflict="sha256").execute()
        return r.data[0]["id"]

    def insert_chunks(
        self, document_id: str, chunks: list[Chunk],
        embeddings: list[list[float]], model: str, version: str,
    ) -> None:
        # 재적재 안전: 기존 청크 삭제 후 삽입
        self.c.table("doc_chunks").delete().eq("document_id", document_id).execute()
        rows = [{
            "document_id": document_id, "chunk_index": ch.chunk_index,
            "content": ch.content, "embedding": emb,
            "token_count": ch.token_count, "embed_model": model, "embed_version": version,
        } for ch, emb in zip(chunks, embeddings)]
        if rows:
            self.c.table("doc_chunks").insert(rows).execute()

    def list_backfill_candidates(self, limit: int = 100):
        r = (self.c.table("documents")
             .select("id,sha256,status,path_in_zip,filename,zip_archives(filename,source_path)")
             .in_("status", sorted(BACKFILL_STATUSES))
             .limit(limit)
             .execute())
        return backfill_candidates(r.data or [])


def make_store(settings: Settings):
    return DryRunStore() if settings.dry_run else SupabaseStore(settings)
