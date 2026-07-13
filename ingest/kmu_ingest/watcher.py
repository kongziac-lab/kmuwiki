"""ZIP 폴더 스캔 → WorkItem 생성.

요구사항 1·2: ZIP을 한 폴더에 누적 → 새/미처리 ZIP을 위 구조로 처리.
ZIP 자체 해시로 중복 적재를 막고(불변식 4), 엔트리 단위로 잠금 여부를 표시한다.

전자결재 ZIP 특성:
  - 한국 윈도우 생성 ZIP은 엔트리명이 CP949로 인코딩된 경우가 많다 → 디코딩 복원.
  - ZIP=결재 1건. 본문 기안문 PDF(폴더명과 같은 이름)에서 부서·문서번호·시행일을 1회
    추출해 같은 ZIP의 모든 파일에 상속한다(§7.B).
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from pathlib import Path

from . import lockdetect
from .hashing import sha256_file
from .metadata import extract_pdf_fields
from .pipeline import WorkItem


def iter_zip_files(zip_dir: str) -> list[Path]:
    root = Path(zip_dir)
    return sorted(
        (p for p in root.rglob("*.zip") if p.is_file()),
        key=lambda p: p.relative_to(root).as_posix(),
    )


def _relative_source_path(zip_path: Path, zip_root: Path | None) -> str:
    if zip_root is None:
        return zip_path.name
    try:
        return zip_path.relative_to(zip_root).as_posix()
    except ValueError:
        return zip_path.name


def _decode_name(info: zipfile.ZipInfo) -> str:
    """엔트리명 복원: UTF-8 플래그(0x800) 없으면 CP437→CP949 재디코딩."""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp949")
    except Exception:
        return info.filename


def _tokens(s: str) -> set[str]:
    s = s.rsplit("/", 1)[-1]
    s = re.sub(r"\.pdf$", "", s, flags=re.I)
    return {t for t in re.split(r"[\s_()\[\].-]+", s) if len(t) >= 2}


def _zip_fields(zf: zipfile.ZipFile, infos: list[zipfile.ZipInfo],
                names: list[str]) -> dict:
    """기안문 PDF에서 ZIP 단위 메타 추출.

    기안문 선별: 폴더명과 동일한 PDF 우선, 없으면 폴더명과 제목 토큰이 가장 많이 겹치는 PDF.
    여러 PDF(기안문 + 관련 문서)가 있어도 시행 문서번호가 있는 첫 후보를 채택한다.
    """
    folder = names[0].replace("\\", "/").split("/")[0] if names else ""
    ftok = _tokens(folder)
    pdfs = [(info, name) for info, name in zip(infos, names)
            if name.lower().endswith(".pdf") and not lockdetect.zip_entry_encrypted(info)]
    if not pdfs:
        return {}

    def rank(name: str) -> tuple:
        base = name.replace("\\", "/").split("/")[-1]
        exact = base.lower() == (folder + ".pdf").lower()
        return (0 if exact else 1, -len(_tokens(name) & ftok))

    pdfs.sort(key=lambda x: rank(x[1]))

    best_any: dict | None = None
    for info, _name in pdfs:
        try:
            fields = extract_pdf_fields(zf.read(info))
        except Exception:
            continue
        if best_any is None:
            best_any = fields
        if fields.get("doc_no"):   # 시행 문서번호가 있으면 기안문으로 채택
            return fields
    return best_any or {}


def iter_work(
    zip_path: Path, store, *, zip_root: Path | None = None, force: bool = False,
) -> Iterator[WorkItem]:
    """한 ZIP을 열어 처리 대상 파일들을 WorkItem 으로 산출.

    force=True면 이미 적재된 ZIP도 재처리한다(파서·청킹·메타 개선을 소급 적용).
    재처리는 멱등이다: register_zip/upsert_document는 sha256 on-conflict 갱신,
    insert_chunks는 기존 청크 삭제 후 재삽입한다.
    """
    zsha = sha256_file(zip_path)
    if not force and store.zip_seen(zsha):
        return  # 이미 적재된 ZIP → 스킵(멱등)

    with zipfile.ZipFile(zip_path) as zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        names = [_decode_name(i) for i in infos]
        zip_fields = _zip_fields(zf, infos, names)
        zip_id = store.register_zip(
            zip_path.name, zsha, len(infos),
            source_path=_relative_source_path(zip_path, zip_root),
        )
        for info, name in zip(infos, names):
            entry_enc = lockdetect.zip_entry_encrypted(info)
            # 엔트리가 암호화면 읽지 않는다(본문 미오픈, 불변식 2).
            data = b"" if entry_enc else zf.read(info)
            yield WorkItem(
                zip_sha256=zsha, zip_id=zip_id,
                path_in_zip=name, filename=Path(name).name,
                data=data, zip_entry_encrypted=entry_enc,
                zip_fields=zip_fields,
            )
