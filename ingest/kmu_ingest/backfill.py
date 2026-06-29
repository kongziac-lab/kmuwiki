"""Phase 3 backfill helpers.

백필은 `pending_password`와 `pending_ocr` 문서만 다룬다. 이미 `processed`인 문서는
절대 후보에 넣지 않고, 비밀번호 자동 시도는 설정된 사전 범위 안에서만 수행한다.
"""

from __future__ import annotations

import json
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .pipeline import Deps, WorkItem, process
from .watcher import _decode_name


BACKFILL_STATUSES = {"pending_password", "pending_ocr"}
DEFAULT_MAX_PASSWORD_ATTEMPTS = 20


@dataclass(frozen=True)
class BackfillCandidate:
    document_id: str
    sha256: str
    status: str
    zip_filename: str | None
    path_in_zip: str
    filename: str

    def manual_queue(self, reason: str) -> dict[str, str | None]:
        return {
            "document_id": self.document_id,
            "sha256": self.sha256,
            "status": self.status,
            "zip_filename": self.zip_filename,
            "path_in_zip": self.path_in_zip,
            "filename": self.filename,
            "reason": reason,
        }


def backfill_candidates(rows: Iterable[dict]) -> list[BackfillCandidate]:
    """Supabase row dicts → 안전한 백필 후보.

    `processed`·`failed` 등은 제외한다. zip relation은 supabase-py의 nested select
    결과(`zip_archives`) 또는 평탄화된 테스트 row 둘 다 허용한다.
    """
    candidates: list[BackfillCandidate] = []
    for row in rows:
        status = row.get("status")
        if status not in BACKFILL_STATUSES:
            continue
        archive = row.get("zip_archives") or {}
        candidates.append(BackfillCandidate(
            document_id=str(row["id"]),
            sha256=str(row["sha256"]),
            status=str(status),
            zip_filename=archive.get("filename") or row.get("zip_filename"),
            path_in_zip=str(row["path_in_zip"]),
            filename=str(row["filename"]),
        ))
    return candidates


def bounded_passwords(passwords: Iterable[str], max_attempts: int = DEFAULT_MAX_PASSWORD_ATTEMPTS) -> list[str]:
    """빈 값/중복을 제거하고 최대 시도 횟수로 제한한다."""
    if max_attempts < 1:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in passwords:
        pw = raw.strip()
        if not pw or pw in seen:
            continue
        seen.add(pw)
        out.append(pw)
        if len(out) >= max_attempts:
            break
    return out


def load_password_dictionary(path: str | None, max_attempts: int = DEFAULT_MAX_PASSWORD_ATTEMPTS) -> list[str]:
    if not path:
        return []
    lines = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)
    return bounded_passwords(lines, max_attempts=max_attempts)


def append_manual_queue(path: str, entries: Iterable[dict]) -> int:
    """수동 처리 큐를 JSONL로 남긴다. 비밀값이나 원문 본문은 저장하지 않는다."""
    count = 0
    with Path(path).open("a", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def _find_zip_entry(zf: zipfile.ZipFile, path_in_zip: str) -> zipfile.ZipInfo | None:
    for info in zf.infolist():
        if not info.is_dir() and _decode_name(info) == path_in_zip:
            return info
    return None


def _read_with_passwords(zf: zipfile.ZipFile, info: zipfile.ZipInfo, passwords: list[str]) -> bytes | None:
    for password in passwords:
        try:
            return zf.read(info, pwd=password.encode("utf-8"))
        except RuntimeError:
            continue
    return None


def run_backfill(
    *,
    candidates: Iterable[BackfillCandidate],
    zip_dir: str,
    deps: Deps,
    passwords: list[str],
    manual_queue_path: str | None = None,
    dry_run: bool = False,
) -> Counter:
    """선택된 pending 후보만 백필한다.

    실제 복호가 가능한 ZIP 엔트리 암호와 OCR 대기 문서만 `process()`로 넘긴다.
    지원하지 않는 파일 내부 암호는 수동 큐로 남긴다.
    """
    stats: Counter[str] = Counter()
    manual_entries: list[dict] = []
    zip_root = Path(zip_dir)
    deps.reprocess_statuses = set(BACKFILL_STATUSES)

    for candidate in candidates:
        if not candidate.zip_filename:
            stats["manual_queue"] += 1
            manual_entries.append(candidate.manual_queue("missing source zip filename"))
            continue
        zip_path = zip_root / candidate.zip_filename
        if not zip_path.exists():
            stats["manual_queue"] += 1
            manual_entries.append(candidate.manual_queue(f"source zip not found: {candidate.zip_filename}"))
            continue

        with zipfile.ZipFile(zip_path) as zf:
            info = _find_zip_entry(zf, candidate.path_in_zip)
            if info is None:
                stats["manual_queue"] += 1
                manual_entries.append(candidate.manual_queue("file not found in source zip"))
                continue
            encrypted_zip_entry = bool(info.flag_bits & 0x1)
            if candidate.status == "pending_password":
                if not encrypted_zip_entry:
                    stats["manual_queue"] += 1
                    manual_entries.append(candidate.manual_queue("file-level encryption requires manual decryptor"))
                    continue
                data = _read_with_passwords(zf, info, passwords)
                if data is None:
                    stats["manual_queue"] += 1
                    manual_entries.append(candidate.manual_queue("password dictionary exhausted"))
                    continue
            else:
                if encrypted_zip_entry:
                    stats["manual_queue"] += 1
                    manual_entries.append(candidate.manual_queue("ocr source zip entry is encrypted"))
                    continue
                data = zf.read(info)

        if dry_run:
            stats[f"would_{candidate.status}"] += 1
            continue

        status = process(WorkItem(
            zip_sha256="backfill",
            zip_id="backfill",
            path_in_zip=candidate.path_in_zip,
            filename=candidate.filename,
            data=data,
            zip_entry_encrypted=False,
            sha256_override=candidate.sha256,
        ), deps)
        stats[status.value] += 1

    if manual_queue_path and manual_entries:
        append_manual_queue(manual_queue_path, manual_entries)
    return stats
