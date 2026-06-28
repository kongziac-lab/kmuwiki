"""파이프라인 상태 머신 (Phase 1).

한 파일의 처리 경로(불변식 1·2·4·7·8을 코드로 강제):

  해시 → 멱등성 검사 → 잠금탐지
     ├─ 잠김           → pending_password (메타만, 본문 미오픈)
     └─ 안 잠김 → 파싱
           ├─ needs_ocr & OCR 불가 → pending_ocr
           ├─ 텍스트 없음          → failed
           └─ 텍스트 있음 → 메타추출 → 마스킹 → [이그레스 게이트]
                 ├─ 차단 → quarantine
                 └─ 통과 → 청킹 → 임베딩 → processed
"""

from __future__ import annotations

from dataclasses import dataclass

from . import lockdetect
from .chunking import chunk_text
from .config import Settings
from .hashing import sha256_bytes
from .metadata import extract_meta
from .models import DocStatus, FileMeta
from .ocr import OCREngine
from .parsers import extract_text
from .pii.egress_gate import EgressBlocked, assert_clean
from .pii.masker import Masker


@dataclass
class WorkItem:
    zip_sha256: str
    zip_id: str
    path_in_zip: str
    filename: str
    data: bytes
    zip_entry_encrypted: bool


@dataclass
class Deps:
    settings: Settings
    store: object
    masker: Masker
    ocr: OCREngine
    embedder: object


def _meta_prefix(meta: FileMeta) -> str | None:
    bits = [b for b in (meta.dept, meta.doc_no,
                        meta.doc_date.isoformat() if meta.doc_date else None) if b]
    return f"[{' '.join(bits)}]" if bits else None


def process(item: WorkItem, deps: Deps) -> DocStatus:
    store = deps.store
    # 콘텐츠 해시(멱등성 키). 잠긴 엔트리는 본문이 없으므로 ZIP해시+경로로 안정 식별.
    sha = (sha256_bytes(item.data) if item.data
           else sha256_bytes(f"{item.zip_sha256}:{item.path_in_zip}".encode()))

    # 1) 멱등성 (불변식 4): 이미 끝난 것은 재처리 안 함
    existing = store.document_status(sha)
    if existing in ("processed", "superseded", "revoked", "pending_password", "pending_ocr"):
        return DocStatus(existing)

    base_meta = FileMeta(filename=item.filename, path_in_zip=item.path_in_zip)

    # 2) 잠금탐지 (불변식 2): 본문을 열지 않고 판별
    head = item.data[:8192]
    if item.zip_entry_encrypted or lockdetect.file_is_encrypted(item.filename, head):
        store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=base_meta,
                              status=DocStatus.PENDING_PASSWORD.value, is_encrypted=True)
        return DocStatus.PENDING_PASSWORD

    # 3) 파싱
    pr = extract_text(item.filename, item.data)
    from_ocr = False
    if pr.needs_ocr:
        text = deps.ocr.image_to_text(item.data) if deps.ocr.available else ""
        from_ocr = True
        # OCR 엔진이 없거나(미설치) 비활성 → 처리 보류(2차 백필 대상), 실패 아님.
        if not deps.ocr.available:
            store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=base_meta,
                                  status=DocStatus.PENDING_OCR.value)
            return DocStatus.PENDING_OCR
    else:
        text = pr.text

    if not text or not text.strip():
        store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=base_meta,
                              status=DocStatus.FAILED.value,
                              error="텍스트 추출 실패(빈 본문)")
        return DocStatus.FAILED

    # 4) 메타추출
    meta = extract_meta(item.path_in_zip, item.filename, text)
    meta.mime_type = pr.mime_type

    # 5) 마스킹 (OCR 본문은 고위험)
    masked = deps.masker.mask(text)

    # 6) 이그레스 게이트 (불변식 7): 통과 못 하면 전송 금지·격리.
    #    마스킹 정책과 동일한 라벨만 강제(정책상 보존하는 라벨은 차단 대상 아님).
    try:
        assert_clean(masked.text, enforce_labels=deps.masker.policy.enforced_high())
    except EgressBlocked as e:
        store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=meta,
                              status=DocStatus.QUARANTINE.value, error=str(e))
        return DocStatus.QUARANTINE

    # 7) 청킹 → 임베딩 → 적재 (마스킹된 본문만)
    chunks = chunk_text(masked.text, deps.settings.chunk_chars,
                        deps.settings.chunk_overlap, prefix=_meta_prefix(meta))
    if not chunks:
        store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=meta,
                              status=DocStatus.FAILED.value, error="청크 0개")
        return DocStatus.FAILED

    embeddings = deps.embedder.embed([c.content for c in chunks])
    doc_id = store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=meta,
                                   status=DocStatus.PROCESSED.value)
    store.insert_chunks(doc_id, chunks, embeddings,
                        deps.embedder.model, deps.embedder.version)
    _ = from_ocr  # 추후 고위험 메트릭/감사에 사용
    return DocStatus.PROCESSED
