"""단계형 적재 스테이징 (00_inbox → 검증 → 01_raw).

투입 폴더(00_inbox)의 ZIP 을 구조 검증 후 불변 원본 폴더(01_raw)로 반입한다.

- 최근 파일(mtime < min_age)은 복사가 끝나지 않았을 수 있어 건너뛴다(다음 실행 재시도).
- 검증 실패는 99_rejected 로 격리하고 reasons.log 에 사유를 남긴다.
- 반입된 원본은 읽기 전용(0444)으로 표시한다(베스트 에포트 — 실질 불변성은
  워커의 :ro 마운트와 NAS 스냅샷이 담당).
- 같은 이름이 이미 있으면 내용(sha256)이 같을 때만 중복 제거하고, 다르면
  해시 접두 8자를 붙여 나란히 보관한다(원본은 덮어쓰지 않는다 — 불변 원칙).

워커의 sha256 중복 방어(zip_seen)와 별개로, 이 단계는 '원본 저장소를 깨끗하게'
유지하는 완충이다: zip 폭탄·비정상 파일·부분 업로드가 원본에 섞이는 것을 막는다.
암호화 ZIP 은 거부하지 않는다 — pending_password 유예 흐름의 정상 입력이다.
"""

from __future__ import annotations

import os
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .hashing import sha256_file

_MB = 1024 * 1024


@dataclass(frozen=True)
class StageLimits:
    min_age_seconds: int = 300                      # 이보다 최근 파일은 복사 중일 수 있음 → 스킵
    max_zip_bytes: int = 1024 * _MB                 # 압축 파일 자체 크기 상한
    max_entries: int = 5000                         # zip 항목 수 상한
    max_uncompressed_bytes: int = 1024 * _MB        # 선언된 해제 크기 합 상한(zip 폭탄)
    max_entry_bytes: int = 128 * _MB                 # 파서가 한 번에 메모리에 올릴 단일 항목 상한
    max_compression_ratio: int = 200                 # 비정상 고압축 엔트리 차단

    @classmethod
    def from_env(cls, env=os.environ) -> "StageLimits":
        return cls(
            min_age_seconds=int(env.get("KMU_STAGE_MIN_AGE_SECONDS", "300")),
            max_zip_bytes=int(env.get("KMU_STAGE_MAX_ZIP_MB", "1024")) * _MB,
            max_entries=int(env.get("KMU_STAGE_MAX_ENTRIES", "5000")),
            max_uncompressed_bytes=int(env.get("KMU_STAGE_MAX_UNCOMPRESSED_MB", "1024")) * _MB,
            max_entry_bytes=int(env.get("KMU_MAX_ZIP_ENTRY_MB", "128")) * _MB,
            max_compression_ratio=int(env.get("KMU_MAX_ZIP_COMPRESSION_RATIO", "200")),
        )


@dataclass
class StageReport:
    staged: list[str] = field(default_factory=list)       # 반입된 상대경로
    duplicates: list[str] = field(default_factory=list)   # 동일 내용 중복 → 투입본 삭제
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (상대경로, 사유) — 다음 실행 재시도
    rejected: list[tuple[str, str]] = field(default_factory=list)  # (상대경로, 사유) — 격리됨


def validate_zip(path: Path, limits: StageLimits) -> str | None:
    """구조 검증. 통과 시 None, 실패 시 사유 문자열."""
    size = path.stat().st_size
    if size == 0:
        return "empty"
    if size > limits.max_zip_bytes:
        return "too-large"
    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
    except (zipfile.BadZipFile, OSError):
        return "invalid-zip"
    if len(infos) > limits.max_entries:
        return "too-many-entries"
    if sum(i.file_size for i in infos) > limits.max_uncompressed_bytes:
        return "uncompressed-too-large"
    if any(i.file_size > limits.max_entry_bytes for i in infos):
        return "entry-too-large"
    if any(
        i.file_size > 0
        and i.file_size / max(1, i.compress_size) > limits.max_compression_ratio
        for i in infos
    ):
        return "suspicious-compression-ratio"
    return None


def _unique_rejected_path(rejected: Path, rel: Path) -> Path:
    dest = rejected / rel
    if not dest.exists():
        return dest
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return dest.with_name(f"{dest.stem}.{stamp}{dest.suffix}")


def _log_rejection(rejected: Path, rel: Path, reason: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()}\t{rel.as_posix()}\t{reason}\n"
    with open(rejected / "reasons.log", "a", encoding="utf-8") as f:
        f.write(line)


def stage_inbox(
    inbox: Path,
    raw: Path,
    rejected: Path,
    *,
    limits: StageLimits | None = None,
    now: float | None = None,
) -> StageReport:
    limits = limits or StageLimits()
    now = time.time() if now is None else now
    report = StageReport()

    inbox.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    rejected.mkdir(parents=True, exist_ok=True)

    for path in sorted(p for p in inbox.rglob("*") if p.is_file()):
        rel = path.relative_to(inbox)

        def reject(reason: str) -> None:
            dest = _unique_rejected_path(rejected, rel)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(dest))
            _log_rejection(rejected, rel, reason)
            report.rejected.append((rel.as_posix(), reason))

        if path.suffix.lower() != ".zip":
            reject("not-zip")
            continue
        if now - path.stat().st_mtime < limits.min_age_seconds:
            report.skipped.append((rel.as_posix(), "recent"))  # 복사 중일 수 있음
            continue

        reason = validate_zip(path, limits)
        if reason:
            reject(reason)
            continue

        # 반입 목적지 결정 — 원본은 덮어쓰지 않는다.
        dest = raw / rel
        if dest.exists():
            src_sha = sha256_file(path)
            if sha256_file(dest) == src_sha:
                path.unlink()  # 동일 내용 → 투입본만 제거
                report.duplicates.append(rel.as_posix())
                continue
            dest = dest.with_name(f"{dest.stem}-{src_sha[:8]}{dest.suffix}")
            if dest.exists():
                if sha256_file(dest) == src_sha:
                    path.unlink()
                    report.duplicates.append(rel.as_posix())
                    continue
                reject("name-collision")
                continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
        try:
            os.chmod(dest, 0o444)  # 읽기 전용 표시(베스트 에포트)
        except OSError:
            pass
        report.staged.append(dest.relative_to(raw).as_posix())

    return report
