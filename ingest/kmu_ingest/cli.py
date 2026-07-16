"""CLI 진입점.

  python -m kmu_ingest.cli run [--path ./zips] [--dry-run]

--dry-run 이면 DB 없이 파이프라인을 끝까지 돌려 상태 분포만 출력한다.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

from .backfill import DEFAULT_MAX_PASSWORD_ATTEMPTS, load_password_dictionary, run_backfill
from .config import load_settings
from .hashing import sha256_bytes
from .staging import StageLimits, stage_inbox
from .embedding import make_embedder
from .layout import LayoutAnalyzer
from .ocr import OCREngine
from .pii.masker import Masker
from .pii.policy import MaskPolicy
from .pipeline import Deps, process
from .retention import cleanup_security_retention
from .store import make_store
from .visual import VisualSanitizer
from .watcher import iter_work, iter_zip_files


# --force 재처리 대상: 인제스트가 만든 종결 상태. superseded/revoked(관리자 라이프사이클)는
# 되돌리지 않는다. failed는 파서/모델 개선으로 복구할 수 있으므로 전체 v2 재구축에 포함한다.
FORCE_REPROCESS_STATUSES = {"processed", "pending_password", "pending_ocr", "failed"}


def cmd_run(args: argparse.Namespace) -> int:
    settings = load_settings()
    if getattr(args, "path", None):
        settings.zip_dir = args.path
    if getattr(args, "dry_run", False):
        settings.dry_run = True

    force = getattr(args, "force", False)
    store = make_store(settings)
    if getattr(args, "require_v2", False):
        _validate_v2_ingest_settings(settings)
        store.ensure_v2_ready()
        if not settings.dry_run:
            source_report = store.source_archive_report(settings.zip_dir)
            if source_report["missing"] or source_report["unsafe"]:
                print("v2 재색인 중단: DB에 등록된 원본 ZIP이 모두 필요합니다.", file=sys.stderr)
                print(json.dumps(source_report, ensure_ascii=False, indent=2), file=sys.stderr)
                return 2
    ocr = OCREngine(settings.ocr_backend)
    visual_masker = _make_visual_masker(settings)
    deps = Deps(
        settings=settings,
        store=store,
        masker=Masker(enable_ner=settings.enable_ner, ner_model=settings.ner_model),
        ocr=ocr,
        embedder=make_embedder(
            settings.embed_provider, settings.embed_model, settings.embed_version,
            output_dimension=settings.embed_output_dimension,
        ),
        visual_masker=visual_masker,
        visual_sanitizer=_make_visual_sanitizer(settings, ocr, visual_masker),
        layout_analyzer=LayoutAnalyzer(settings.layout_backend),
        reprocess_statuses=FORCE_REPROCESS_STATUSES if force else set(),
    )

    zips = iter_zip_files(settings.zip_dir)
    zip_root = Path(settings.zip_dir)
    only_sources = set(getattr(args, "only_source", None) or [])
    if only_sources:
        zips = [zip_path for zip_path in zips
                if zip_path.relative_to(zip_root).as_posix() in only_sources]
        missing_sources = only_sources - {
            zip_path.relative_to(zip_root).as_posix() for zip_path in zips
        }
        if missing_sources:
            raise RuntimeError(f"requested source ZIP not found: {sorted(missing_sources)}")
    only_sha256 = {value.lower() for value in (getattr(args, "only_sha256", None) or [])}
    print(f"ZIP {len(zips)}개 발견 @ {settings.zip_dir} "
          f"(dry_run={settings.dry_run}, embed={settings.embed_provider}, "
          f"ocr={settings.ocr_backend}, force={force})")

    stats: Counter[str] = Counter()
    for zp in zips:
        print(f"\n# {zp.name}")
        for item in iter_work(
            zp,
            store,
            zip_root=zip_root,
            force=force,
            max_entry_bytes=settings.max_zip_entry_bytes,
            max_compression_ratio=settings.max_zip_compression_ratio,
        ):
            if only_sha256 and sha256_bytes(item.data) not in only_sha256:
                continue
            status = process(item, deps)
            stats[status.value] += 1

    print("\n=== 처리 결과 ===")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    return 0


def cmd_v2_status(args: argparse.Namespace) -> int:
    settings = load_settings()
    store = make_store(settings)
    store.ensure_v2_ready()
    print(json.dumps(store.multimodal_status(), ensure_ascii=False, indent=2))
    return 0


def cmd_rollback_check(args: argparse.Namespace) -> int:
    settings = load_settings()
    store = make_store(settings)
    store.ensure_v2_ready()
    status = store.multimodal_status()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    print("\n롤백 전환값:")
    print("  KMU_SEARCH_RPC=hybrid_search")
    print("  KMU_ALLOW_V1_SEARCH_FALLBACK=0")
    legacy_models = status.get("legacy_models") or {}
    if legacy_models:
        model_version = max(legacy_models, key=legacy_models.get)
        model, _, version = model_version.partition("/")
        print(f"  KMU_EMBED_MODEL={model}")
        print(f"  KMU_EMBED_VERSION={version}")
    print("v2 섀도 재구축 기본값은 기존 doc_chunks 모델을 변경하지 않습니다.")
    return 0


def evaluate_cutover(
    status: dict,
    *,
    expected_source_archives: int,
    minimum_total_documents: int,
    minimum_v2_documents: int,
    embed_model: str,
    embed_version: str,
) -> dict:
    """운영 전환의 데이터·모델·보안 불변식을 기계적으로 판정한다."""
    failures: list[str] = []
    warnings: list[str] = []
    sources = status.get("source_archives") or {}
    documents = status.get("documents") or {}
    assets = status.get("assets") or {}
    units = status.get("search_units") or {}
    integrity = status.get("integrity") or {}
    legacy_models = status.get("legacy_models") or {}

    if int(sources.get("total") or 0) != expected_source_archives:
        failures.append(
            f"원본 ZIP 기준 불일치: expected={expected_source_archives}, "
            f"actual={int(sources.get('total') or 0)}")
    if int(documents.get("total") or 0) < minimum_total_documents:
        failures.append(
            f"문서 기준 미달: minimum={minimum_total_documents}, "
            f"actual={int(documents.get('total') or 0)}")
    if int(documents.get("v2") or 0) < minimum_v2_documents:
        failures.append(
            f"v2 문서 기준 미달: minimum={minimum_v2_documents}, "
            f"actual={int(documents.get('v2') or 0)}")
    if int(documents.get("processed_v1") or 0):
        failures.append(
            f"기존 검색 가능 문서가 v1에 남아 있음: {documents['processed_v1']}개")
    if int(documents.get("processed") or 0) != int(documents.get("v2") or 0):
        failures.append(
            "processed 문서 수와 v2 문서 수가 달라 부분 전환 상태임")

    unit_total = int(units.get("total") or 0)
    if unit_total <= 0:
        failures.append("v2 검색 단위가 0개임")
    if int(integrity.get("v2_without_search_units") or 0):
        failures.append(
            "검색 단위가 없는 v2 문서가 있음: "
            f"{integrity['v2_without_search_units']}개")
    if int(integrity.get("legacy_documents_without_v2") or 0):
        failures.append(
            "기존 검색 가능 문서 중 v2로 재구축되지 않은 문서가 있음: "
            f"{integrity['legacy_documents_without_v2']}개")
    expected_model = f"{embed_model}/{embed_version}"
    models = units.get("models") or {}
    if set(models) != {expected_model} or int(models.get(expected_model) or 0) != unit_total:
        failures.append(
            f"v2 임베딩 모델 혼합 또는 핀 불일치: expected={expected_model}, actual={models}")

    if int(integrity.get("ready_without_storage") or 0):
        failures.append("ready 시각 자산 중 Storage 경로가 없는 항목이 있음")
    if int(integrity.get("ready_without_redaction") or 0):
        failures.append("ready 시각 자산 중 마스킹 확인이 없는 항목이 있음")
    if not legacy_models:
        failures.append("즉시 롤백할 기존 doc_chunks 인덱스가 없음")
    elif len(legacy_models) != 1:
        failures.append(f"롤백 인덱스의 임베딩 모델이 혼합됨: {legacy_models}")

    for key in ("pending_review", "pending_ocr", "blocked", "failed"):
        value = int(assets.get(key) or 0)
        if value:
            warnings.append(f"시각 자산 {key}: {value}개 (검색에는 안전한 대체 표현만 사용)")

    return {
        "ready": not failures,
        "failures": failures,
        "warnings": warnings,
        "expected": {
            "source_archives": expected_source_archives,
            "minimum_total_documents": minimum_total_documents,
            "minimum_v2_documents": minimum_v2_documents,
            "embed_model": expected_model,
        },
    }


def cmd_cutover_check(args: argparse.Namespace) -> int:
    settings = load_settings()
    _validate_v2_ingest_settings(settings)
    store = make_store(settings)
    store.ensure_v2_ready()
    status = store.multimodal_status()
    report = evaluate_cutover(
        status,
        expected_source_archives=args.expected_source_archives,
        minimum_total_documents=args.minimum_total_documents,
        minimum_v2_documents=args.minimum_v2_documents,
        embed_model=settings.embed_model,
        embed_version=settings.embed_version,
    )
    print(json.dumps({"cutover": report, "status": status}, ensure_ascii=False, indent=2))
    return 0 if report["ready"] else 2


def _validate_v2_ingest_settings(settings) -> None:
    if settings.index_version != "v2":
        raise RuntimeError("KMU_INDEX_VERSION=v2 is required")
    if settings.embed_provider != "cohere" or settings.embed_model != "embed-v4.0":
        raise RuntimeError("v2 rebuild requires Cohere embed-v4.0")
    if settings.embed_output_dimension != 1024:
        raise RuntimeError("v2 rebuild requires KMU_EMBED_OUTPUT_DIMENSION=1024")


def cmd_backfill(args: argparse.Namespace) -> int:
    settings = load_settings()
    if args.zip_dir:
        settings.zip_dir = args.zip_dir
    if args.dry_run:
        settings.dry_run = True
    if args.ocr_backend:
        settings.ocr_backend = args.ocr_backend

    store = make_store(settings)
    candidates = store.list_backfill_candidates(limit=args.limit)
    passwords = load_password_dictionary(args.passwords, max_attempts=args.max_password_attempts)
    ocr = OCREngine(settings.ocr_backend)
    visual_masker = _make_visual_masker(settings)
    deps = Deps(
        settings=settings,
        store=store,
        masker=Masker(enable_ner=settings.enable_ner, ner_model=settings.ner_model),
        ocr=ocr,
        embedder=make_embedder(
            settings.embed_provider, settings.embed_model, settings.embed_version,
            output_dimension=settings.embed_output_dimension,
        ),
        visual_masker=visual_masker,
        visual_sanitizer=_make_visual_sanitizer(settings, ocr, visual_masker),
        layout_analyzer=LayoutAnalyzer(settings.layout_backend),
    )

    print(f"백필 후보 {len(candidates)}개 @ {settings.zip_dir} "
          f"(dry_run={settings.dry_run}, ocr={settings.ocr_backend}, passwords={len(passwords)})")
    stats = run_backfill(
        candidates=candidates,
        zip_dir=settings.zip_dir,
        deps=deps,
        passwords=passwords,
        manual_queue_path=args.manual_queue,
        dry_run=args.dry_run,
    )
    print("\n=== 백필 결과 ===")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    return 0


def cmd_stage(args: argparse.Namespace) -> int:
    report = stage_inbox(
        Path(args.inbox), Path(args.raw), Path(args.rejected),
        limits=StageLimits.from_env(),
    )
    print(f"스테이징: 반입 {len(report.staged)} · 중복 {len(report.duplicates)} "
          f"· 보류 {len(report.skipped)} · 격리 {len(report.rejected)}")
    for rel in report.staged:
        print(f"  [in]   {rel}")
    for rel, why in report.skipped:
        print(f"  [wait] {rel} ({why})")
    for rel, why in report.rejected:
        print(f"  [rej]  {rel} ({why})")
    return 0


def cmd_retention_cleanup(args: argparse.Namespace) -> int:
    from supabase import create_client

    settings = load_settings()
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("Supabase service credentials are required")
    result = cleanup_security_retention(
        create_client(settings.supabase_url, settings.supabase_service_key),
        audit_days=args.audit_days,
        rate_limit_days=args.rate_limit_days,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _make_visual_masker(settings):
    if not settings.visual_index_enabled or settings.ocr_backend == "none":
        return None
    return Masker(
        enable_ner=settings.enable_ner,
        ner_model=settings.ner_model,
        policy=MaskPolicy.all(),
    )


def _make_visual_sanitizer(settings, ocr, visual_masker):
    if visual_masker is None:
        return None
    return VisualSanitizer(
        ocr,
        max_input_bytes=settings.visual_max_input_bytes,
        max_pixels=settings.visual_max_pixels,
        max_side=settings.visual_max_side,
        jpeg_quality=settings.visual_jpeg_quality,
        verify_after_redaction=settings.visual_verify_redaction,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kmu_ingest")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="ZIP 폴더 인제스트 실행")
    r.add_argument("--path", help="ZIP 폴더 경로(기본 KMU_ZIP_DIR)")
    r.add_argument("--dry-run", action="store_true", help="DB 미적재, 콘솔 출력만")
    r.add_argument("--force", action="store_true",
                   help="이미 적재된 ZIP도 재처리(파서·청킹·메타 개선 소급 적용)")
    r.add_argument("--only-source", action="append",
                   help="재처리할 원본 ZIP의 ZIP 폴더 기준 상대 경로(반복 가능)")
    r.add_argument("--only-sha256", action="append",
                   help="재처리할 문서 SHA-256(반복 가능)")
    r.set_defaults(func=cmd_run)
    rv2 = sub.add_parser("reindex-v2", help="모든 기존 문서를 Embed v4 멀티모달 v2로 재구축")
    rv2.add_argument("--path", help="ZIP 폴더 경로(기본 KMU_ZIP_DIR)")
    rv2.add_argument("--dry-run", action="store_true", help="DB 미적재 사전 검증")
    rv2.add_argument("--only-source", action="append",
                     help="재처리할 원본 ZIP의 ZIP 폴더 기준 상대 경로(반복 가능)")
    rv2.add_argument("--only-sha256", action="append",
                     help="재처리할 문서 SHA-256(반복 가능)")
    rv2.set_defaults(func=cmd_run, force=True, require_v2=True)
    status = sub.add_parser("v2-status", help="v1/v2 문서·자산·검색 단위 전환 현황")
    status.set_defaults(func=cmd_v2_status)
    rollback = sub.add_parser("rollback-check", help="v1 검색 롤백 준비 상태와 전환값 확인")
    rollback.set_defaults(func=cmd_rollback_check)
    cutover = sub.add_parser(
        "cutover-check", help="v2 데이터·모델·보안 완전성 검사(성공할 때만 RPC 전환)")
    cutover.add_argument("--expected-source-archives", type=int, required=True,
                         help="재색인 시작 전에 확인한 등록 원본 ZIP 수")
    cutover.add_argument("--minimum-total-documents", type=int, required=True,
                         help="재색인 전 documents 최소 기준")
    cutover.add_argument("--minimum-v2-documents", type=int, required=True,
                         help="재색인 전 검색 가능 문서 수 이상의 v2 기준")
    cutover.set_defaults(func=cmd_cutover_check)
    b = sub.add_parser("backfill", help="pending_password/pending_ocr 문서만 안전하게 백필")
    b.add_argument("--zip-dir", help="원본 ZIP 폴더 경로(기본 KMU_ZIP_DIR)")
    b.add_argument("--passwords", help="비밀번호 후보 사전 파일(줄 단위, 주석 # 허용)")
    b.add_argument("--max-password-attempts", type=int, default=DEFAULT_MAX_PASSWORD_ATTEMPTS,
                   help="문서당 최대 비밀번호 시도 수")
    b.add_argument("--manual-queue", default="backfill-manual-queue.jsonl",
                   help="자동 처리 실패분 JSONL 큐 경로")
    b.add_argument("--ocr-backend", choices=["easyocr", "paddle", "none"],
                   help="백필 OCR 백엔드(예: GPU 서버에서는 paddle)")
    b.add_argument("--limit", type=int, default=100, help="이번 실행에서 조회할 최대 후보 수")
    b.add_argument("--dry-run", action="store_true", help="실제 처리 없이 후보/큐 동작만 확인")
    b.set_defaults(func=cmd_backfill)
    s = sub.add_parser("stage", help="00_inbox 검증 후 01_raw 반입(실패분 99_rejected 격리)")
    s.add_argument("--inbox", default=os.environ.get("KMU_INBOX_DIR", "/data/inbox"))
    s.add_argument("--raw", default=os.environ.get("KMU_RAW_DIR", "/data/raw"))
    s.add_argument("--rejected", default=os.environ.get("KMU_REJECTED_DIR", "/data/rejected"))
    s.set_defaults(func=cmd_stage)
    retention = sub.add_parser(
        "retention-cleanup", help="감사 로그와 API rate-limit 만료 행 정리")
    retention.add_argument("--audit-days", type=int, default=180)
    retention.add_argument("--rate-limit-days", type=int, default=1)
    retention.set_defaults(func=cmd_retention_cleanup)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
