"""CLI 진입점.

  python -m kmu_ingest.cli run [--path ./zips] [--dry-run]

--dry-run 이면 DB 없이 파이프라인을 끝까지 돌려 상태 분포만 출력한다.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from .backfill import DEFAULT_MAX_PASSWORD_ATTEMPTS, load_password_dictionary, run_backfill
from .config import load_settings
from .embedding import make_embedder
from .ocr import OCREngine
from .pii.masker import Masker
from .pipeline import Deps, process
from .store import make_store
from .watcher import iter_work, iter_zip_files


def cmd_run(args: argparse.Namespace) -> int:
    settings = load_settings()
    if args.path:
        settings.zip_dir = args.path
    if args.dry_run:
        settings.dry_run = True

    store = make_store(settings)
    deps = Deps(
        settings=settings,
        store=store,
        masker=Masker(enable_ner=settings.enable_ner, ner_model=settings.ner_model),
        ocr=OCREngine(settings.ocr_backend),
        embedder=make_embedder(settings.embed_provider, settings.embed_model, settings.embed_version),
    )

    zips = iter_zip_files(settings.zip_dir)
    print(f"ZIP {len(zips)}개 발견 @ {settings.zip_dir} "
          f"(dry_run={settings.dry_run}, embed={settings.embed_provider}, ocr={settings.ocr_backend})")

    stats: Counter[str] = Counter()
    zip_root = Path(settings.zip_dir)
    for zp in zips:
        print(f"\n# {zp.name}")
        for item in iter_work(zp, store, zip_root=zip_root):
            status = process(item, deps)
            stats[status.value] += 1

    print("\n=== 처리 결과 ===")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    return 0


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
    deps = Deps(
        settings=settings,
        store=store,
        masker=Masker(enable_ner=settings.enable_ner, ner_model=settings.ner_model),
        ocr=OCREngine(settings.ocr_backend),
        embedder=make_embedder(settings.embed_provider, settings.embed_model, settings.embed_version),
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kmu_ingest")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="ZIP 폴더 인제스트 실행")
    r.add_argument("--path", help="ZIP 폴더 경로(기본 KMU_ZIP_DIR)")
    r.add_argument("--dry-run", action="store_true", help="DB 미적재, 콘솔 출력만")
    r.set_defaults(func=cmd_run)
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
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
