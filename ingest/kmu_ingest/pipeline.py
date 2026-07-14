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

from dataclasses import dataclass, field

from . import lockdetect
from .chunking import chunk_prefix, chunk_text
from .classification import classify_document
from .cleaning import strip_boilerplate
from .config import Settings
from .hashing import sha256_bytes
from .metadata import build_file_meta, resolve_file_fields
from .models import DocStatus
from .ocr import OCREngine
from .parsers import extract_text
from .pii.egress_gate import EgressBlocked, assert_clean
from .pii.masker import Masker


def _apply_organization(meta, text: str | None) -> None:
    classification = classify_document(meta.filename, meta.path_in_zip, text)
    meta.task_category = classification.task_category
    meta.classification_confidence = classification.confidence
    meta.review_required = classification.review_required


@dataclass
class WorkItem:
    zip_sha256: str
    zip_id: str
    path_in_zip: str
    filename: str
    data: bytes
    zip_entry_encrypted: bool
    zip_fields: dict = field(default_factory=dict)  # ZIP 단위 상속 메타(§7.B)
    sha256_override: str | None = None              # 백필: 기존 pending row 를 같은 sha 로 갱신
    ingest_error: str | None = None                 # 런타임 ZIP 한도/해제 오류(본문 미처리)


@dataclass
class Deps:
    settings: Settings
    store: object
    masker: Masker
    ocr: OCREngine
    embedder: object
    reprocess_statuses: set[str] = field(default_factory=set)

def process(item: WorkItem, deps: Deps) -> DocStatus:
    store = deps.store
    # 콘텐츠 해시(멱등성 키). 잠긴 엔트리는 본문이 없으므로 ZIP해시+경로로 안정 식별.
    sha = item.sha256_override or (
        sha256_bytes(item.data) if item.data
        else sha256_bytes(f"{item.zip_sha256}:{item.path_in_zip}".encode())
    )

    # 1) 멱등성 (불변식 4): 이미 끝난 것은 재처리 안 함
    existing = store.document_status(sha)
    if (existing in ("processed", "superseded", "revoked", "pending_password", "pending_ocr")
            and existing not in deps.reprocess_statuses):
        return DocStatus(existing)

    # ZIP 단위 메타(부서·문서번호·시행일)를 파일에 상속(§7.B). dept 미상이면 None=관리자 전용.
    meta = build_file_meta(item.filename, item.path_in_zip, None, item.zip_fields)
    _apply_organization(meta, None)

    if item.ingest_error:
        store.upsert_document(
            sha256=sha,
            zip_id=item.zip_id,
            meta=meta,
            status=DocStatus.FAILED.value,
            error=item.ingest_error,
        )
        return DocStatus.FAILED

    # 2) 잠금탐지 (불변식 2): 본문을 열지 않고 판별. HWP 암호비트는 앞부분 밖일 수 있어 전체 전달.
    if item.zip_entry_encrypted or lockdetect.file_is_encrypted(item.filename, item.data):
        store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=meta,
                              status=DocStatus.PENDING_PASSWORD.value, is_encrypted=True)
        return DocStatus.PENDING_PASSWORD

    # 3) 파싱
    try:
        pr = extract_text(item.filename, item.data)
    except Exception as exc:
        store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=meta,
                              status=DocStatus.FAILED.value,
                              error=f"text extraction error: {type(exc).__name__}: {exc}")
        return DocStatus.FAILED
    from_ocr = False
    if pr.needs_ocr:
        text = deps.ocr.image_to_text(item.data) if deps.ocr.available else ""
        from_ocr = True
        # OCR 엔진이 없거나(미설치) 비활성 → 처리 보류(2차 백필 대상), 실패 아님.
        if not deps.ocr.available:
            store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=meta,
                                  status=DocStatus.PENDING_OCR.value)
            return DocStatus.PENDING_OCR
    else:
        text = pr.text

    if not text or not text.strip():
        store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=meta,
                              status=DocStatus.FAILED.value,
                              error="텍스트 추출 실패(빈 본문)")
        return DocStatus.FAILED

    # 파일별 시행번호 해석(붙임=상속, 그 외 PDF/문서=자기 번호 우선) — §7.B 개선
    fields = resolve_file_fields(item.filename, item.data, text, item.zip_fields)
    meta = build_file_meta(item.filename, item.path_in_zip, pr.mime_type, fields)
    _apply_organization(meta, text)

    # 5) 마스킹 (OCR 본문은 고위험: 전화번호 등 업무 메타도 보수적으로 제거)
    masker = deps.masker.high_risk_copy() if from_ocr else deps.masker
    masked = masker.mask(text)

    # 6) 이그레스 게이트 (불변식 7): 통과 못 하면 전송 금지·격리.
    #    마스킹 정책과 동일한 라벨만 강제(정책상 보존하는 라벨은 차단 대상 아님).
    try:
        assert_clean(masked.text, enforce_labels=masker.policy.enforced_high())
    except EgressBlocked as e:
        store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=meta,
                              status=DocStatus.QUARANTINE.value, error=str(e))
        return DocStatus.QUARANTINE

    # 7) 검색용 본문 정리 → 청킹 → 임베딩 → 적재 (마스킹된 본문만)
    searchable_text = strip_boilerplate(masked.text)
    prefix = chunk_prefix(
        title=meta.title,
        dept=meta.dept,
        doc_no=meta.doc_no,
        doc_date=meta.doc_date,
        document_kind=meta.document_kind,
        attachment_names=meta.attachment_names,
    )
    chunks = chunk_text(searchable_text, deps.settings.chunk_chars,
                        deps.settings.chunk_overlap, prefix=prefix or None)
    if len(chunks) > deps.settings.max_chunks_per_doc:
        chunks = chunks[:deps.settings.max_chunks_per_doc]
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
