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
        for name in zf.namelist():
            if name.lower().startswith("contents/") and name.lower().endswith(".xml"):
                xml = zf.read(name).decode("utf-8", "replace")
                parts.append(_TAG.sub(" ", xml))
    return _WS.sub(" ", " ".join(parts)).strip()
