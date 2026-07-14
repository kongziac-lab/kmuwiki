"""HWP/HWPX 텍스트 추출.

HWP 5.x: olefile 로 'PrvText' 스트림(미리보기 텍스트, UTF-16LE)을 읽는다.
  - 무거운 본문 디컴프레션 없이 검색·임베딩에 충분한 텍스트를 얻는다.
  - 암호화 HWP는 이 단계에 오지 않는다(lockdetect 차단). PrvText 없으면 빈 문자열.
  - 한계: PrvText는 '미리보기'라 매우 긴 문서는 일부만 담길 수 있다(추후 hwp5 본문 파서로 보강 가능).

HWPX: zip 기반 → Contents/section*.xml 의 텍스트를 태그 제거 후 추출.
"""

from __future__ import annotations

import io
import re
import zipfile

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")
_MAX_HWPX_ENTRIES = 2000
_MAX_HWPX_TOTAL_BYTES = 128 * 1024 * 1024
_MAX_HWPX_XML_BYTES = 16 * 1024 * 1024
_MAX_HWPX_COMPRESSION_RATIO = 200
_READ_CHUNK_BYTES = 1024 * 1024


def extract_hwp(data: bytes) -> str:
    import olefile  # lazy

    ole = olefile.OleFileIO(io.BytesIO(data))
    try:
        if not ole.exists("PrvText"):
            return ""
        raw = ole.openstream("PrvText").read()
    finally:
        ole.close()
    text = raw.decode("utf-16-le", "replace")
    # PrvText의 표식 문자 정리
    text = text.replace("\x00", "").replace("\r", "\n")
    return _WS.sub(" ", text).strip()


def extract_hwpx(data: bytes) -> str:
    parts: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        infos = zf.infolist()
        if len(infos) > _MAX_HWPX_ENTRIES:
            raise ValueError("HWPX entry count exceeds safety limit")
        if sum(info.file_size for info in infos) > _MAX_HWPX_TOTAL_BYTES:
            raise ValueError("HWPX uncompressed size exceeds safety limit")
        for info in infos:
            name = info.filename
            if name.lower().startswith("contents/") and name.lower().endswith(".xml"):
                if info.file_size > _MAX_HWPX_XML_BYTES:
                    raise ValueError("HWPX XML entry exceeds safety limit")
                if (info.file_size > 0
                        and info.file_size / max(1, info.compress_size) > _MAX_HWPX_COMPRESSION_RATIO):
                    raise ValueError("HWPX compression ratio exceeds safety limit")
                xml = _read_zip_entry(zf, info, _MAX_HWPX_XML_BYTES).decode("utf-8", "replace")
                parts.append(_TAG.sub(" ", xml))
    return _WS.sub(" ", " ".join(parts)).strip()


def _read_zip_entry(zf: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
    output = bytearray()
    with zf.open(info) as stream:
        while chunk := stream.read(_READ_CHUNK_BYTES):
            output.extend(chunk)
            if len(output) > limit:
                raise ValueError("HWPX entry exceeds safety limit")
    return bytes(output)
