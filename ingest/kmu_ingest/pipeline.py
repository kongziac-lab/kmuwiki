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
from .cleaning import sanitize_text, strip_boilerplate
from .config import Settings
from .embedding import EmbeddingInput
from .hashing import sha256_bytes
from .layout import LayoutAnalyzer
from .metadata import build_file_meta, resolve_file_fields
from .models import AssetStatus, DocStatus, DocumentAsset, ParsedAsset, SearchUnit
from .ocr import OCREngine
from .parsers import extract_text
from .pii.egress_gate import EgressBlocked, assert_clean
from .pii.masker import Masker
from .visual import VisualSanitizer


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
    visual_masker: Masker | None = None
    visual_sanitizer: VisualSanitizer | None = None
    layout_analyzer: LayoutAnalyzer | None = None
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
        pr = extract_text(
            item.filename,
            item.data,
            max_visual_pages=deps.settings.max_visual_pages,
        )
    except Exception as exc:
        store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=meta,
                              status=DocStatus.FAILED.value,
                              error=f"text extraction error: {type(exc).__name__}: {exc}")
        return DocStatus.FAILED
    from_ocr = False
    layout_text = _enrich_layout_assets(pr.assets or [], deps.layout_analyzer)
    if pr.needs_ocr:
        ocr_text, asset_ocr = _ocr_document_assets(pr.assets or [], item.data, deps.ocr)
        text = _join_unique(pr.text, layout_text, ocr_text)
        from_ocr = True
        # OCR 엔진이 없거나(미설치) 비활성 → 처리 보류(2차 백필 대상), 실패 아님.
        if not deps.ocr.available:
            store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=meta,
                                  status=DocStatus.PENDING_OCR.value)
            return DocStatus.PENDING_OCR
        for index, ocr_text in asset_ocr.items():
            if index < len(pr.assets or []) and ocr_text:
                pr.assets[index].text = _join_unique(pr.assets[index].text, ocr_text)
    else:
        text = _join_unique(pr.text, layout_text)

    has_visual_source = any(asset.image_bytes for asset in (pr.assets or []))
    if (not text or not text.strip()) and not has_visual_source:
        store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=meta,
                              status=DocStatus.FAILED.value,
                              error="텍스트 추출 실패(빈 본문)")
        return DocStatus.FAILED
    text = (text or item.filename).strip()

    # 파일별 시행번호 해석(붙임=상속, 그 외 PDF/문서=자기 번호 우선) — §7.B 개선
    fields = resolve_file_fields(item.filename, item.data, text, item.zip_fields)
    meta = build_file_meta(item.filename, item.path_in_zip, pr.mime_type, fields)
    _apply_organization(meta, text)

    # 5) 마스킹 (OCR 본문은 고위험: 전화번호 등 업무 메타도 보수적으로 제거)
    masker = (deps.visual_masker or deps.masker.high_risk_copy()) if from_ocr else deps.masker
    masked = masker.mask(text)

    # 6) 이그레스 게이트 (불변식 7): 통과 못 하면 전송 금지·격리.
    #    마스킹 정책과 동일한 라벨만 강제(정책상 보존하는 라벨은 차단 대상 아님).
    try:
        assert_clean(masked.text, enforce_labels=masker.policy.enforced_high())
    except EgressBlocked as e:
        store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=meta,
                              status=DocStatus.QUARANTINE.value, error=str(e))
        return DocStatus.QUARANTINE

    # 7) 검색용 본문/자산 정리 → v2 검색 단위 → 임베딩 → 원자적 적재.
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

    security_level = (
        store.document_security_level(sha)
        if hasattr(store, "document_security_level") else meta.security_level
    )
    try:
        assets = _prepare_assets(
            pr.assets or [],
            meta=meta,
            deps=deps,
            security_level=security_level,
        )
        units = _build_search_units(chunks, assets, meta, deps.settings)
        if not units:
            store.upsert_document(sha256=sha, zip_id=item.zip_id, meta=meta,
                                  status=DocStatus.FAILED.value, error="v2 검색 단위 0개")
            return DocStatus.FAILED
        inputs = [EmbeddingInput(
            text=unit.content,
            image_bytes=unit.image_bytes,
            media_type=unit.media_type,
        ) for unit in units]
        if any(value.image_bytes for value in inputs) and not getattr(
                deps.embedder, "supports_images", False):
            raise RuntimeError("ready visual assets require a multimodal Embed v4 provider")
        if hasattr(deps.embedder, "embed_inputs"):
            embeddings = deps.embedder.embed_inputs(inputs)
        else:
            embeddings = deps.embedder.embed([value.text for value in inputs])
        if len(embeddings) != len(units):
            raise RuntimeError("embedding provider returned an unexpected result count")

        # Custom/legacy stores used by focused tests keep the old adapter path.
        # Production DryRunStore/SupabaseStore always implement replace_index_v2.
        if not hasattr(store, "replace_index_v2"):
            legacy_embeddings = embeddings[:len(chunks)]
            doc_id = store.upsert_document(
                sha256=sha, zip_id=item.zip_id, meta=meta,
                status=DocStatus.PROCESSED.value,
            )
            store.insert_chunks(
                doc_id, chunks, legacy_embeddings,
                deps.embedder.model, deps.embedder.version,
            )
            return DocStatus.PROCESSED

        doc_id = store.upsert_document(
            sha256=sha, zip_id=item.zip_id, meta=meta,
            status=DocStatus.PROCESSING.value,
        )
        store.replace_index_v2(
            doc_id,
            assets,
            units,
            embeddings,
            deps.embedder.model,
            deps.embedder.version,
            visual_status=_visual_status(assets, deps.settings.visual_index_enabled),
            legacy_chunks=chunks,
            legacy_embeddings=embeddings[:len(chunks)],
        )
        return DocStatus.PROCESSED
    except EgressBlocked as exc:
        store.upsert_document(
            sha256=sha, zip_id=item.zip_id, meta=meta,
            status=DocStatus.QUARANTINE.value, error=str(exc),
        )
        return DocStatus.QUARANTINE
    except Exception as exc:
        store.upsert_document(
            sha256=sha, zip_id=item.zip_id, meta=meta,
            status=DocStatus.FAILED.value,
            error=f"multimodal indexing error: {type(exc).__name__}: {exc}",
        )
        return DocStatus.FAILED


def _ocr_document_assets(
    assets: list[ParsedAsset], fallback_bytes: bytes, ocr: OCREngine,
) -> tuple[str, dict[int, str]]:
    texts: list[str] = []
    by_asset: dict[int, str] = {}
    # OCR full pages/source images once. PP-Structure table/chart crops are
    # derivatives of those pages and would otherwise duplicate the text.
    image_assets = [(index, asset) for index, asset in enumerate(assets)
                    if asset.image_bytes and asset.asset_type in {"page", "image"}]
    if image_assets:
        for index, asset in image_assets:
            value = ocr.image_to_text(asset.image_bytes or b"")
            if value.strip():
                texts.append(value)
                by_asset[index] = value
    else:
        value = ocr.image_to_text(fallback_bytes) if ocr.available else ""
        if value.strip():
            texts.append(value)
    return "\n".join(texts).strip(), by_asset


def _enrich_layout_assets(
    assets: list[ParsedAsset], analyzer: LayoutAnalyzer | None,
) -> str:
    """Attach PP-StructureV3 Markdown/regions without making it a hard dependency."""
    if analyzer is None or not analyzer.available:
        return ""
    markdown_parts: list[str] = []
    new_assets: list[ParsedAsset] = []
    for asset in list(assets):
        if not asset.image_bytes or asset.asset_type not in {"page", "image"}:
            continue
        analysis = analyzer.analyze(asset.image_bytes, page_no=asset.page_no)
        if not analysis.succeeded:
            continue
        if analysis.markdown.strip():
            asset.structured_content = _join_unique(
                asset.structured_content, analysis.markdown)
            markdown_parts.append(analysis.markdown)
        new_assets.extend(analysis.assets)
    assets.extend(new_assets)
    return "\n\n".join(markdown_parts).strip()


def _prepare_assets(
    parsed_assets: list[ParsedAsset], *, meta, deps: Deps, security_level: str | None,
) -> list[DocumentAsset]:
    assets: list[DocumentAsset] = []
    for asset_index, parsed in enumerate(parsed_assets[:deps.settings.max_assets_per_doc]):
        visual_derived = bool(
            deps.settings.visual_index_enabled
            and (parsed.image_bytes or parsed.extraction_model == "PP-StructureV3")
        )
        text_masker = (deps.visual_masker or deps.masker.high_risk_copy()) \
            if (parsed.needs_ocr or visual_derived) else deps.masker
        text_result = text_masker.mask(sanitize_text(parsed.text))
        structured_result = text_masker.mask(sanitize_text(parsed.structured_content))
        caption_result = text_masker.mask(sanitize_text(parsed.caption))
        for value, current_masker in (
            (text_result.text, text_masker),
            (structured_result.text, text_masker),
            (caption_result.text, text_masker),
        ):
            assert_clean(value, enforce_labels=current_masker.policy.enforced_high())
        if visual_derived and text_masker.policy.ner_labels:
            for raw, result in (
                (parsed.text, text_result),
                (parsed.structured_content, structured_result),
                (parsed.caption, caption_result),
            ):
                if raw.strip() and not result.ner_available:
                    raise EgressBlocked(
                        reason="visual-derived text requires local NER redaction")

        prepared = DocumentAsset(
            asset_index=asset_index,
            asset_type=parsed.asset_type,
            page_no=parsed.page_no,
            bbox=parsed.bbox,
            text_content=text_result.text,
            structured_content=structured_result.text,
            caption=caption_result.text,
            media_type=parsed.media_type,
            width=parsed.width,
            height=parsed.height,
            status=AssetStatus.METADATA_ONLY,
            extraction_model=parsed.extraction_model,
            extraction_version=parsed.extraction_version,
        )
        if parsed.image_bytes:
            prepared = _prepare_visual_asset(
                prepared,
                parsed.image_bytes,
                deps=deps,
                security_level=security_level,
            )
        assets.append(prepared)
    return assets


def _prepare_visual_asset(
    asset: DocumentAsset,
    raw_image: bytes,
    *,
    deps: Deps,
    security_level: str | None,
) -> DocumentAsset:
    if not deps.settings.visual_index_enabled:
        asset.status = AssetStatus.METADATA_ONLY
        asset.error = "visual indexing disabled"
        return asset
    required = deps.settings.visual_require_security_level
    if required and security_level != required:
        asset.status = AssetStatus.PENDING_REVIEW
        asset.error = f"visual egress requires security_level={required}"
        return asset
    if deps.visual_sanitizer is None or deps.visual_masker is None:
        asset.status = AssetStatus.PENDING_OCR
        asset.error = "local visual sanitizer is unavailable"
        return asset

    result = deps.visual_sanitizer.sanitize(raw_image, masker=deps.visual_masker)
    if not result.safe:
        asset.status = (AssetStatus.PENDING_OCR
                        if "OCR" in (result.error or "") or "NER" in (result.error or "")
                        else AssetStatus.BLOCKED)
        asset.error = result.error
        return asset
    asset.image_bytes = result.image_bytes
    asset.media_type = result.media_type
    asset.width = result.width
    asset.height = result.height
    asset.media_sha256 = sha256_bytes(result.image_bytes or b"")
    asset.text_content = _join_unique(asset.text_content, result.masked_ocr_text)
    assert_clean(asset.text_content, enforce_labels=deps.visual_masker.policy.enforced_high())
    asset.redaction_applied = result.redaction_applied
    asset.status = AssetStatus.READY
    return asset


def _build_search_units(
    chunks,
    assets: list[DocumentAsset],
    meta,
    settings: Settings,
) -> list[SearchUnit]:
    units: list[SearchUnit] = [SearchUnit(
        unit_index=index,
        content=chunk.content,
        modality="text",
        token_count=chunk.token_count,
        extraction_version="chunk-v2",
    ) for index, chunk in enumerate(chunks)]

    for asset in assets:
        if len(units) >= settings.max_search_units_per_doc:
            break
        content = _asset_surrogate(meta, asset)
        has_structured = bool(asset.structured_content.strip())
        has_text = bool(asset.text_content.strip() or asset.caption.strip())
        has_image = asset.status == AssetStatus.READY and bool(asset.image_bytes)
        if not (has_structured or has_text or has_image):
            continue
        if has_image:
            modality = "mixed" if content.strip() else "image"
        elif asset.asset_type in {"table", "worksheet"}:
            modality = "table"
        else:
            modality = "text"
        units.append(SearchUnit(
            unit_index=len(units),
            content=content or f"파일: {meta.filename}\n자산유형: {asset.asset_type}",
            modality=modality,
            asset_index=asset.asset_index,
            asset_type=asset.asset_type,
            page_no=asset.page_no,
            bbox=asset.bbox,
            token_count=len(content),
            extraction_version=asset.extraction_version,
            image_bytes=asset.image_bytes if has_image else None,
            media_type=asset.media_type if has_image else None,
        ))
    return units[:settings.max_search_units_per_doc]


def _asset_surrogate(meta, asset: DocumentAsset) -> str:
    parts = [
        f"파일: {meta.filename}",
        f"제목: {meta.title}" if meta.title else "",
        f"부서: {meta.dept}" if meta.dept else "",
        f"문서번호: {meta.doc_no}" if meta.doc_no else "",
        f"페이지: {asset.page_no}" if asset.page_no else "",
        f"자산유형: {asset.asset_type}",
        f"캡션: {asset.caption}" if asset.caption else "",
        asset.structured_content,
        asset.text_content,
    ]
    return "\n".join(part for part in parts if part and part.strip()).strip()


def _visual_status(assets: list[DocumentAsset], enabled: bool) -> str:
    visual = [asset for asset in assets if asset.media_type or asset.image_bytes]
    if not enabled:
        return "disabled"
    if not visual:
        return "ready"
    statuses = {asset.status for asset in visual}
    if statuses == {AssetStatus.READY}:
        return "ready"
    if AssetStatus.READY in statuses:
        return "partial"
    if AssetStatus.PENDING_REVIEW in statuses:
        return "pending_review"
    if AssetStatus.PENDING_OCR in statuses:
        return "pending_ocr"
    return "blocked"


def _join_unique(*values: str) -> str:
    parts: list[str] = []
    for value in values:
        value = (value or "").strip()
        if value and value not in parts:
            parts.append(value)
    return "\n".join(parts)
