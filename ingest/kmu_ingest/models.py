"""상태 머신과 데이터 구조. (스키마 supabase/migrations/0001_init.sql 와 1:1 대응)"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class DocStatus(str, Enum):
    """문서 처리 상태. DB의 doc_status enum 과 값이 일치해야 한다."""

    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    PENDING_PASSWORD = "pending_password"  # 잠김: 1차에서 본문 미오픈
    PENDING_OCR = "pending_ocr"            # 스캔본: GPU OCR 대기
    QUARANTINE = "quarantine"              # 이그레스 게이트 차단(PII 잔존 의심)
    FAILED = "failed"
    SUPERSEDED = "superseded"
    REVOKED = "revoked"


@dataclass
class FileMeta:
    """ZIP 내 한 파일의 추출된 메타데이터(§7.B/§7.E).

    sample ZIP 구조 확정 전까지 dept/security_level/doc_no 등은 best-effort.
    채우지 못하면 None → deny-by-default(관리자 전용)로 취급된다.
    """

    filename: str
    path_in_zip: str
    mime_type: str | None = None
    dept: str | None = None
    security_level: str | None = None
    task_category: str | None = None
    classification_confidence: float = 0.0
    review_required: bool = True
    title: str | None = None
    attachment_names: list[str] = field(default_factory=list)
    document_kind: str | None = None
    doc_no: str | None = None
    doc_date: date | None = None
    author: str | None = None
    version: int = 1


@dataclass
class Chunk:
    chunk_index: int
    content: str            # 반드시 마스킹된 텍스트
    token_count: int | None = None
    section_type: str | None = None


@dataclass
class DocumentRecord:
    """파이프라인이 다루는 한 문서의 작업 상태."""

    sha256: str
    filename: str
    path_in_zip: str
    zip_sha256: str
    is_encrypted: bool = False
    status: DocStatus = DocStatus.PENDING
    meta: FileMeta | None = None
    masked_text: str | None = None
    chunks: list[Chunk] = field(default_factory=list)
    error: str | None = None
    processed_at: datetime | None = None
