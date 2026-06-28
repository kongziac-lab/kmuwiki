"""잠금(암호화) 탐지 — 본문을 열지 않고 판별(불변식 2).

두 층위를 구분한다:
  1) ZIP 엔트리 자체 암호화  → zip_entry_encrypted(ZipInfo)
  2) 내부 파일(PDF/Office/HWP) 암호화 → file_is_encrypted(name, head_bytes)

내부 파일은 ZIP에서 추출한 '앞부분 바이트'만으로 판별한다(전체 파싱 금지).
"""

from __future__ import annotations

import zipfile

# 매직 바이트
_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # MS Compound File (OLE/CFB)
_PDF_MAGIC = b"%PDF"


def zip_entry_encrypted(info: zipfile.ZipInfo) -> bool:
    """ZIP 엔트리 자체가 암호화되었는지(general purpose bit 0)."""
    return bool(info.flag_bits & 0x1)


def file_is_encrypted(filename: str, head: bytes) -> bool:
    """내부 파일이 암호로 잠겼는지 best-effort 판별.

    head: 파일 앞부분(예: 8KB). 전체를 읽지 않아도 대부분 판별 가능.
    판별 불가한 경우 False(잠금 아님)로 두되, 이후 파싱 실패 시 failed 처리된다.
    """
    name = filename.lower()

    if name.endswith(".pdf") or head[:4] == _PDF_MAGIC:
        # 암호화 PDF는 trailer에 /Encrypt 딕셔너리를 갖는다.
        return b"/Encrypt" in head

    if name.endswith((".docx", ".xlsx", ".pptx")):
        # 정상 OOXML은 ZIP(PK). 암호화되면 OLE 컨테이너(EncryptedPackage)로 감싸진다.
        return head[:8] == _OLE_MAGIC

    if name.endswith(".hwp"):
        # HWP 5.x는 항상 OLE. 암호화 여부는 FileHeader 스트림 플래그에 있다 → olefile 필요.
        return _hwp_encrypted(head)

    if name.endswith(".hwpx"):
        # HWPX는 ZIP 기반. 암호화는 드묾 → 보수적으로 False, 파싱 단계에서 재확인.
        return False

    return False


def _hwp_encrypted(head: bytes) -> bool:
    """HWP FileHeader의 암호화 비트 확인. olefile 있으면 정확, 없으면 False."""
    if head[:8] != _OLE_MAGIC:
        return False
    try:
        import io

        import olefile  # lazy: 없으면 판별 생략
    except ImportError:
        return False
    try:
        ole = olefile.OleFileIO(io.BytesIO(head))
        if not ole.exists("FileHeader"):
            return False
        with ole.openstream("FileHeader") as s:
            fh = s.read()
        # HWP5 FileHeader: signature(32) + version(4) + properties(4, little-endian).
        # properties bit1(0x02) = 암호 설정.
        if len(fh) >= 40:
            props = int.from_bytes(fh[36:40], "little")
            return bool(props & 0x02)
    except Exception:
        return False
    return False
