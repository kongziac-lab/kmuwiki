"""CLI 진입점.

  python -m kmu_ingest.cli run [--path ./zips] [--dry-run]

--dry-run 이면 DB 없이 파이프라인을 끝까지 돌려 상태 분포만 출력한다.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

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
    for zp in zips:
        print(f"\n# {zp.name}")
        for item in iter_work(zp, store):
            status = process(item, deps)
            stats[status.value] += 1

    print("\n=== 처리 결과 ===")
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
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
