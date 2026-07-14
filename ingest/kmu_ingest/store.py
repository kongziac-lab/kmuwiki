"""Supabase 적재 어댑터.

인제스트 워커는 service_role 키로 RLS를 우회한다(서버 전용; 클라이언트 노출 금지).
DryRunStore 는 DB 없이 파이프라인을 끝까지 돌려보기 위한 콘솔 출력 구현.
"""

from __future__ import annotations

from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

from .config import Settings
from .backfill import BACKFILL_STATUSES, backfill_candidates
from .hashing import sha256_bytes
from .models import Chunk, DocumentAsset, FileMeta, SearchUnit


class DryRunStore:
    """DB 미적재. 멱등성 검사용 인메모리 집합 + 요약 출력."""

    def __init__(self) -> None:
        self._zips: set[str] = set()
        self._docs: dict[str, str] = {}  # sha256 -> status
        self._doc_ids: dict[str, str] = {}  # dryrun id -> sha256
        self._security_levels: dict[str, str | None] = {}
        self.assets: list[DocumentAsset] = []
        self.search_units: list[SearchUnit] = []

    def zip_seen(self, sha256: str) -> bool:
        return sha256 in self._zips

    def register_zip(self, filename: str, sha256: str, file_count: int, *, source_path: str | None = None) -> str:
        self._zips.add(sha256)
        return f"dryrun-zip-{sha256[:8]}"

    def document_status(self, sha256: str) -> str | None:
        return self._docs.get(sha256)

    def document_security_level(self, sha256: str) -> str | None:
        return self._security_levels.get(sha256)

    def upsert_document(
        self, *, sha256: str, zip_id: str, meta: FileMeta, status: str,
        is_encrypted: bool = False, error: str | None = None,
    ) -> str:
        self._docs[sha256] = status
        if meta.security_level is not None:
            self._security_levels[sha256] = meta.security_level
        print(f"  [doc] {meta.path_in_zip} -> {status}"
              + f" (task={meta.task_category}, review={meta.review_required})"
              + (f" (enc, dept={meta.dept}, sec={meta.security_level})" if is_encrypted else ""))
        document_id = f"dryrun-doc-{sha256[:8]}"
        self._doc_ids[document_id] = sha256
        return document_id

    def insert_chunks(
        self, document_id: str, chunks: list[Chunk],
        embeddings: list[list[float]], model: str, version: str,
    ) -> None:
        print(f"  [chunks] {len(chunks)}개 임베딩 적재 (model={model}/{version}, dim={len(embeddings[0]) if embeddings else 0})")

    def replace_index_v2(
        self,
        document_id: str,
        assets: list[DocumentAsset],
        units: list[SearchUnit],
        embeddings: list[list[float]],
        model: str,
        version: str,
        *,
        visual_status: str,
        legacy_chunks: list[Chunk] | None = None,
        legacy_embeddings: list[list[float]] | None = None,
    ) -> None:
        self.assets = list(assets)
        self.search_units = list(units)
        sha = self._doc_ids.get(document_id)
        if sha:
            self._docs[sha] = "processed"
        print(
            f"  [v2] assets={len(assets)}, units={len(units)}, visual={visual_status}, "
            f"model={model}/{version}, dim={len(embeddings[0]) if embeddings else 0}"
        )

    def list_backfill_candidates(self, limit: int = 100):
        return []

    def ensure_v2_ready(self) -> None:
        return None

    def multimodal_status(self) -> dict:
        return {
            "source_archives": {"total": len(self._zips)},
            "documents": {
                "total": len(self._docs), "v1": 0, "v2": len(self._docs),
                "processed": sum(value == "processed" for value in self._docs.values()),
                "processed_v1": 0,
            },
            "assets": {
                "total": len(self.assets), "ready": 0, "pending_review": 0,
                "pending_ocr": 0, "blocked": 0, "failed": 0,
            },
            "search_units": {
                "total": len(self.search_units), "text": 0, "table": 0,
                "image": 0, "mixed": 0, "models": {},
            },
            "integrity": {
                "v2_without_search_units": 0,
                "legacy_documents_without_v2": 0,
                "ready_without_storage": 0,
                "ready_without_redaction": 0,
            },
            "legacy_models": {},
        }

    def source_archive_report(self, zip_dir: str) -> dict:
        return {"expected": 0, "available": 0, "missing": [], "unsafe": []}


class SupabaseStore:
    """실제 Supabase 적재. supabase-py 필요."""

    def __init__(self, settings: Settings):
        from supabase import create_client  # lazy

        if not settings.supabase_url or not settings.supabase_service_key:
            raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY 가 필요합니다.")
        self.c = create_client(settings.supabase_url, settings.supabase_service_key)
        self.settings = settings

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

    def document_security_level(self, sha256: str) -> str | None:
        r = self.c.table("documents").select("security_level").eq("sha256", sha256).execute()
        return r.data[0].get("security_level") if r.data else None

    def upsert_document(
        self, *, sha256: str, zip_id: str, meta: FileMeta, status: str,
        is_encrypted: bool = False, error: str | None = None,
    ) -> str:
        row = self.document_row(
            sha256=sha256, zip_id=zip_id, meta=meta, status=status,
            is_encrypted=is_encrypted, error=error,
        )
        r = self.c.table("documents").upsert(row, on_conflict="sha256").execute()
        return r.data[0]["id"]

    @staticmethod
    def document_row(
        *, sha256: str, zip_id: str, meta: FileMeta, status: str,
        is_encrypted: bool = False, error: str | None = None,
    ) -> dict:
        row = {
            "sha256": sha256, "zip_id": zip_id,
            "filename": meta.filename, "path_in_zip": meta.path_in_zip,
            "mime_type": meta.mime_type, "is_encrypted": is_encrypted,
            "status": status, "dept": meta.dept,
            "task_category": meta.task_category,
            "classification_confidence": meta.classification_confidence,
            "review_required": meta.review_required,
            "title": meta.title,
            "attachment_names": meta.attachment_names,
            "document_kind": meta.document_kind,
            "doc_no": meta.doc_no, "author": meta.author, "version": meta.version,
            "doc_date": meta.doc_date.isoformat() if meta.doc_date else None,
            "error": error,
            "processed_at": datetime.now(timezone.utc).isoformat()
            if status == "processed" else None,
        }
        # security_level 은 파이프라인이 판정하지 않는 '운영자 결정'(관리자 검토로 승급).
        # 파이프라인 meta 는 항상 None 이므로(metadata.py §7.B), None 이면 컬럼을 아예
        # 보내지 않아 재처리(run --force)가 기존 등급을 NULL 로 파괴하지 않게 한다.
        # (PostgREST upsert 는 전송한 컬럼만 갱신한다. RLS 는 '일반'만 노출하므로
        #  등급 파괴 = 검색에서 문서 소실이었다.)
        if meta.security_level is not None:
            row["security_level"] = meta.security_level
        return row

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
            "section_type": ch.section_type,
        } for ch, emb in zip(chunks, embeddings)]
        if rows:
            self.c.table("doc_chunks").insert(rows).execute()

    def replace_index_v2(
        self,
        document_id: str,
        assets: list[DocumentAsset],
        units: list[SearchUnit],
        embeddings: list[list[float]],
        model: str,
        version: str,
        *,
        visual_status: str,
        legacy_chunks: list[Chunk] | None = None,
        legacy_embeddings: list[list[float]] | None = None,
    ) -> None:
        if len(units) != len(embeddings):
            raise ValueError("search unit / embedding count mismatch")
        if (self.settings.write_legacy_index and legacy_chunks is not None
                and len(legacy_chunks) != len(legacy_embeddings or [])):
            raise ValueError("legacy chunk / embedding count mismatch")

        old_paths = self._existing_asset_paths(document_id)
        uploaded_paths: set[str] = set()
        try:
            for asset in assets:
                if not asset.image_bytes:
                    continue
                digest = asset.media_sha256 or sha256_bytes(asset.image_bytes)
                asset.media_sha256 = digest
                extension = _media_extension(asset.media_type)
                asset.storage_path = f"{document_id}/{asset.asset_index}-{digest[:16]}.{extension}"
                uploaded_paths.add(asset.storage_path)
                # 네트워크가 저장 직후 끊겨도 정리 대상에 포함되도록 호출 전에 기록한다.
                self._upload_asset(asset.storage_path, asset.image_bytes, asset.media_type)

            asset_rows = [self.asset_row(asset) for asset in assets]
            unit_rows = [self.search_unit_row(unit, embedding, model, version)
                         for unit, embedding in zip(units, embeddings)]
            legacy_rows = []
            if self.settings.write_legacy_index and legacy_chunks is not None:
                legacy_rows = [self.legacy_chunk_row(chunk, embedding, model, version)
                               for chunk, embedding in zip(
                                   legacy_chunks, legacy_embeddings or [])]
            self.c.rpc("replace_document_index_v2", {
                "target_document_id": document_id,
                "asset_rows": asset_rows,
                "unit_rows": unit_rows,
                "target_visual_status": visual_status,
                "legacy_rows": legacy_rows,
            }).execute()
        except Exception:
            # Storage와 PostgreSQL은 한 트랜잭션으로 묶을 수 없다. 이번 시도에서
            # 처음 생긴 파생본만 제거하고 기존(동일 digest) 자산은 보존한다.
            self._remove_asset_paths(sorted(uploaded_paths - old_paths))
            raise

        stale_paths = sorted(old_paths - uploaded_paths)
        self._remove_asset_paths(stale_paths)

    def _existing_asset_paths(self, document_id: str) -> set[str]:
        try:
            response = (
                self.c.table("document_assets")
                .select("storage_path")
                .eq("document_id", document_id)
                .execute()
            )
            return {row["storage_path"] for row in (response.data or []) if row.get("storage_path")}
        except Exception:
            return set()

    def _upload_asset(self, path: str, payload: bytes, media_type: str | None) -> None:
        bucket = self.c.storage.from_(self.settings.visual_asset_bucket)
        options = {"content-type": media_type or "image/jpeg", "upsert": "true"}
        bucket.upload(path=path, file=payload, file_options=options)

    def _remove_asset_paths(self, paths: list[str]) -> None:
        if not paths:
            return
        try:
            self.c.storage.from_(self.settings.visual_asset_bucket).remove(paths)
        except Exception:
            # 파생본은 비공개이고 RLS로 보호된다. 정리 실패가 원래 인제스트
            # 오류를 가리지 않도록 운영 정리 작업에서 재시도한다.
            pass

    @staticmethod
    def asset_row(asset: DocumentAsset) -> dict:
        return {
            "asset_index": asset.asset_index,
            "asset_type": asset.asset_type,
            "page_no": asset.page_no,
            "bbox": list(asset.bbox) if asset.bbox else None,
            "text_content": asset.text_content,
            "structured_content": asset.structured_content,
            "caption": asset.caption,
            "storage_path": asset.storage_path,
            "media_type": asset.media_type,
            "media_sha256": asset.media_sha256,
            "width": asset.width,
            "height": asset.height,
            "status": asset.status.value,
            "redaction_applied": asset.redaction_applied,
            "extraction_model": asset.extraction_model,
            "extraction_version": asset.extraction_version,
            "error": asset.error,
        }

    @staticmethod
    def search_unit_row(
        unit: SearchUnit,
        embedding: list[float],
        model: str,
        version: str,
    ) -> dict:
        return {
            "unit_index": unit.unit_index,
            "asset_index": unit.asset_index,
            "modality": unit.modality,
            "asset_type": unit.asset_type,
            "page_no": unit.page_no,
            "bbox": list(unit.bbox) if unit.bbox else None,
            "content": unit.content,
            "embedding": embedding,
            "token_count": unit.token_count,
            "embed_model": model,
            "embed_version": version,
            "extraction_version": unit.extraction_version,
        }

    @staticmethod
    def legacy_chunk_row(chunk: Chunk, embedding: list[float], model: str, version: str) -> dict:
        return {
            "chunk_index": chunk.chunk_index,
            "content": chunk.content,
            "embedding": embedding,
            "token_count": chunk.token_count,
            "embed_model": model,
            "embed_version": version,
            "section_type": chunk.section_type,
        }

    def ensure_v2_ready(self) -> None:
        """Fail before a rebuild if migration 0012 is not visible."""
        try:
            self.c.table("document_assets").select("id").limit(1).execute()
            self.c.table("search_units").select("id").limit(1).execute()
            self.c.table("documents").select("id,index_version,visual_status").limit(1).execute()
        except Exception as exc:
            raise RuntimeError("multimodal migration 0012 is not applied") from exc

    def multimodal_status(self) -> dict:
        def count(table: str, **equals) -> int:
            query = self.c.table(table).select("id", count="exact")
            for key, value in equals.items():
                query = query.eq(key, value)
            response = query.limit(1).execute()
            return int(getattr(response, "count", 0) or 0)

        legacy_rows: list[dict] = []
        try:
            legacy_rows = self._select_all(
                "doc_chunks", "document_id,embed_model,embed_version")
            legacy_models = dict(Counter(
                f"{row.get('embed_model') or 'unknown'}/{row.get('embed_version') or 'unknown'}"
                for row in legacy_rows
            ))
        except Exception:
            legacy_models = {}

        unit_rows = self._select_all(
            "search_units", "document_id,embed_model,embed_version")
        unit_models = dict(Counter(
            f"{row.get('embed_model') or 'unknown'}/{row.get('embed_version') or 'unknown'}"
            for row in unit_rows
        ))
        v2_rows = self._select_all("documents", "id", index_version="v2")
        v2_ids = {str(row["id"]) for row in v2_rows}
        indexed_ids = {str(row["document_id"]) for row in unit_rows}
        legacy_document_ids = {
            str(row["document_id"]) for row in legacy_rows if row.get("document_id")
        }
        ready_assets = self._select_all(
            "document_assets", "storage_path,redaction_applied", status="ready")

        return {
            "source_archives": {"total": count("zip_archives")},
            "documents": {
                "total": count("documents"),
                "v1": count("documents", index_version="v1"),
                "v2": count("documents", index_version="v2"),
                "processed": count("documents", status="processed"),
                "processed_v1": count(
                    "documents", status="processed", index_version="v1"),
            },
            "assets": {
                "total": count("document_assets"),
                "ready": count("document_assets", status="ready"),
                "pending_review": count("document_assets", status="pending_review"),
                "pending_ocr": count("document_assets", status="pending_ocr"),
                "blocked": count("document_assets", status="blocked"),
                "failed": count("document_assets", status="failed"),
            },
            "search_units": {
                "total": count("search_units"),
                "text": count("search_units", modality="text"),
                "table": count("search_units", modality="table"),
                "image": count("search_units", modality="image"),
                "mixed": count("search_units", modality="mixed"),
                "models": unit_models,
            },
            "integrity": {
                "v2_without_search_units": len(v2_ids - indexed_ids),
                "legacy_documents_without_v2": len(legacy_document_ids - v2_ids),
                "ready_without_storage": sum(
                    not row.get("storage_path") for row in ready_assets),
                "ready_without_redaction": sum(
                    not bool(row.get("redaction_applied")) for row in ready_assets),
            },
            "legacy_models": legacy_models,
        }

    def source_archive_report(self, zip_dir: str) -> dict:
        """DB에 등록된 원본 ZIP이 지정한 읽기 루트에 모두 있는지 확인한다."""
        root = Path(zip_dir).expanduser().resolve()
        rows = self._select_all("zip_archives", "filename,source_path")
        missing: list[str] = []
        unsafe: list[str] = []
        available = 0
        for row in rows:
            source = str(row.get("source_path") or row.get("filename") or "").strip()
            if not source:
                missing.append("<source_path 없음>")
                continue
            source_path = Path(source).expanduser()
            candidate = source_path.resolve() if source_path.is_absolute() \
                else (root / source_path).resolve()
            if not source_path.is_absolute() and root not in candidate.parents:
                unsafe.append(source)
            elif candidate.is_file():
                available += 1
            else:
                missing.append(source)
        return {
            "expected": len(rows),
            "available": available,
            "missing": sorted(missing),
            "unsafe": sorted(unsafe),
        }

    def _select_all(self, table: str, columns: str, **equals) -> list[dict]:
        """PostgREST 기본 행 제한을 넘겨도 운영 집계가 잘리지 않게 페이지 조회한다."""
        rows: list[dict] = []
        page_size = 1000
        start = 0
        while True:
            query = self.c.table(table).select(columns)
            for key, value in equals.items():
                query = query.eq(key, value)
            response = query.range(start, start + page_size - 1).execute()
            page = list(response.data or [])
            rows.extend(page)
            if len(page) < page_size:
                return rows
            start += page_size

    def list_backfill_candidates(self, limit: int = 100):
        r = (self.c.table("documents")
             .select("id,sha256,status,path_in_zip,filename,zip_archives(filename,source_path)")
             .in_("status", sorted(BACKFILL_STATUSES))
             .limit(limit)
             .execute())
        return backfill_candidates(r.data or [])


def make_store(settings: Settings):
    return DryRunStore() if settings.dry_run else SupabaseStore(settings)


def _media_extension(media_type: str | None) -> str:
    return {"image/png": "png", "image/webp": "webp"}.get(media_type or "", "jpg")
