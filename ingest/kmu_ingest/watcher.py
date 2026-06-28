"""ZIP 폴더 스캔 → WorkItem 생성.

요구사항 1·2: ZIP을 한 폴더에 누적 → 새/미처리 ZIP을 위 구조로 처리.
ZIP 자체 해시로 중복 적재를 막고(불변식 4), 엔트리 단위로 잠금 여부를 표시한다.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from pathlib import Path

from . import lockdetect
from .hashing import sha256_file
from .pipeline import WorkItem


def iter_zip_files(zip_dir: str) -> list[Path]:
    return sorted(Path(zip_dir).glob("*.zip"))


def iter_work(zip_path: Path, store) -> Iterator[WorkItem]:
    """한 ZIP을 열어 처리 대상 파일들을 WorkItem 으로 산출."""
    zsha = sha256_file(zip_path)
    if store.zip_seen(zsha):
        return  # 이미 적재된 ZIP → 스킵(멱등)

    with zipfile.ZipFile(zip_path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        zip_id = store.register_zip(zip_path.name, zsha, len(infos))
        for info in infos:
            entry_enc = lockdetect.zip_entry_encrypted(info)
            # 엔트리가 암호화면 읽지 않는다(본문 미오픈, 불변식 2).
            data = b"" if entry_enc else zf.read(info)
            yield WorkItem(
                zip_sha256=zsha, zip_id=zip_id,
                path_in_zip=info.filename, filename=Path(info.filename).name,
                data=data, zip_entry_encrypted=entry_enc,
            )
