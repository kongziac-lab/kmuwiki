"""문서 → 텍스트 추출. 무거운 의존성은 lazy import.

반환 ParseResult.needs_ocr=True 이면 스캔본으로 보고 OCR 단계로 넘긴다.
잠긴 파일은 이 단계에 오지 않는다(lockdetect 에서 걸러짐, 불변식 2).
"""

from __future__ import annotations

import io
from dataclasses import dataclass


@dataclass
class ParseResult:
    text: str
    needs_ocr: bool = False
    mime_type: str | None = None


_TEXT_EXT = (".txt", ".csv", ".md", ".json", ".xml", ".html", ".htm")


def extract_text(filename: str, data: bytes) -> ParseResult:
    name = filename.lower()

    if name.endswith(_TEXT_EXT):
        return ParseResult(_decode(data), mime_type="text/plain")

    if name.endswith(".pdf"):
        return _pdf(data)

    if name.endswith(".docx"):
        return ParseResult(_docx(data), mime_type="application/vnd.openxmlformats")

    if name.endswith(".xlsx"):
        return ParseResult(_xlsx(data), mime_type="application/vnd.openxmlformats")

    if name.endswith((".hwp", ".hwpx")):
        return _hwp(name, data)

    if name.endswith((".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")):
        # 이미지 → OCR 필요
        return ParseResult("", needs_ocr=True, mime_type="image/*")

    # 미지원 포맷
    return ParseResult("", needs_ocr=False, mime_type=None)


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "cp949", "euc-kr", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _pdf(data: bytes) -> ParseResult:
    try:
        import pdfplumber  # lazy
    except ImportError:
        return ParseResult("", needs_ocr=True, mime_type="application/pdf")
    parts: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    text = "\n".join(parts).strip()
    # 텍스트가 거의 없으면 스캔 PDF로 보고 OCR 대상
    return ParseResult(text, needs_ocr=(len(text) < 20), mime_type="application/pdf")


def _docx(data: bytes) -> str:
    import docx  # python-docx, lazy

    d = docx.Document(io.BytesIO(data))
    parts = [p.text for p in d.paragraphs]
    for table in d.tables:
        for row in table.rows:
            parts.append("\t".join(c.text for c in row.cells))
    return "\n".join(parts).strip()


def _xlsx(data: bytes) -> str:
    import openpyxl  # lazy

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts: list[str] = []
    for ws in wb.worksheets:
        parts.append(f"# {ws.title}")
        for row in ws.iter_rows(values_only=True):
            parts.append("\t".join("" if v is None else str(v) for v in row))
    return "\n".join(parts).strip()


def _hwp(name: str, data: bytes) -> ParseResult:
    """HWP/HWPX 텍스트 추출. 구형 HWP는 파싱 난도가 높아 best-effort.

    실패 시 needs_ocr=False + 빈 텍스트 → 파이프라인에서 failed 처리(§7.H 리스크).
    """
    try:
        if name.endswith(".hwpx"):
            from .hwp_support import extract_hwpx  # 추후 구현
            return ParseResult(extract_hwpx(data), mime_type="application/hwpx")
        from .hwp_support import extract_hwp
        return ParseResult(extract_hwp(data), mime_type="application/hwp")
    except Exception:
        return ParseResult("", needs_ocr=False, mime_type="application/hwp")
