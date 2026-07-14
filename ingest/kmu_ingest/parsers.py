"""문서 → 텍스트 추출. 무거운 의존성은 lazy import.

반환 ParseResult.needs_ocr=True 이면 스캔본으로 보고 OCR 단계로 넘긴다.
잠긴 파일은 이 단계에 오지 않는다(lockdetect 에서 걸러짐, 불변식 2).

지원 포맷(실제 전자결재 ZIP 기준): pdf, hwp/hwpx, docx, xls/xlsx, html/htm, mht, txt/csv/md/json/xml.
"""

from __future__ import annotations

import html as _htmlmod
import io
import re
from dataclasses import dataclass


@dataclass
class ParseResult:
    text: str
    needs_ocr: bool = False
    mime_type: str | None = None


_PLAIN_EXT = (".txt", ".csv", ".md", ".json")
_HTML_EXT = (".html", ".htm", ".xml")
_IMG_EXT = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")


def extract_text(filename: str, data: bytes) -> ParseResult:
    name = filename.lower()

    if name.endswith(_PLAIN_EXT):
        return ParseResult(_decode(data), mime_type="text/plain")
    if name.endswith(_HTML_EXT):
        return ParseResult(_strip_html(_decode(data)), mime_type="text/html")
    if name.endswith(".pdf"):
        return _pdf(data)
    if name.endswith(".docx"):
        return ParseResult(_docx(data), mime_type="application/vnd.openxmlformats")
    if name.endswith(".xlsx"):
        return ParseResult(_xlsx(data), mime_type="application/vnd.openxmlformats")
    if name.endswith(".xls"):
        return ParseResult(_xls(data), mime_type="application/vnd.ms-excel")
    if name.endswith(".mht") or name.endswith(".mhtml"):
        return ParseResult(_mht(data), mime_type="multipart/related")
    if name.endswith((".hwp", ".hwpx")):
        return _hwp(name, data)
    if name.endswith(_IMG_EXT):
        return ParseResult("", needs_ocr=True, mime_type="image/*")
    return ParseResult("", needs_ocr=False, mime_type=None)


# ── 텍스트/HTML ────────────────────────────────────────────────
def _decode(data: bytes) -> str:
    for enc in ("utf-8", "cp949", "euc-kr", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = _htmlmod.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n\s*\n+", "\n", s).strip()


# ── PDF ────────────────────────────────────────────────────────
def _pdf(data: bytes) -> ParseResult:
    try:
        import pdfplumber  # lazy
    except ImportError:
        return ParseResult("", needs_ocr=True, mime_type="application/pdf")
    try:
        parts: list[str] = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
    except Exception as exc:
        # pdfminer 가 깨지는 PDF(예: "Invalid octal")는 pypdf 로 한 번 더 시도한다.
        # 폴백까지 실패하면 원 예외를 그대로 올려 기존 failed 기록을 유지한다.
        text = _pdf_via_pypdf(data, original=exc)
    # 텍스트가 거의 없으면 스캔 PDF로 보고 OCR 대상
    return ParseResult(text, needs_ocr=(len(text) < 20), mime_type="application/pdf")


def _pdf_via_pypdf(data: bytes, *, original: Exception) -> str:
    try:
        from pypdf import PdfReader  # lazy
        reader = PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception:
        raise original


# ── Office ─────────────────────────────────────────────────────
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


def _xls(data: bytes) -> str:
    """구형 .xls (BIFF). xlrd 필요."""
    import xlrd  # lazy

    wb = xlrd.open_workbook(file_contents=data)
    parts: list[str] = []
    for sh in wb.sheets():
        parts.append(f"# {sh.name}")
        for r in range(sh.nrows):
            parts.append("\t".join(_xls_cell(c) for c in sh.row(r)))
    return "\n".join(parts).strip()


def _xls_cell(cell) -> str:
    v = cell.value
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return "" if v is None else str(v)


# ── MHT (MHTML 웹 아카이브) ─────────────────────────────────────
def _mht(data: bytes) -> str:
    import email

    msg = email.message_from_bytes(data)
    parts: list[str] = []
    for part in msg.walk():
        ct = part.get_content_type()
        if ct not in ("text/html", "text/plain"):
            continue
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        text = payload.decode(charset, "replace")
        parts.append(_strip_html(text) if ct == "text/html" else text)
    return "\n".join(p for p in parts if p.strip()).strip()


# ── HWP ────────────────────────────────────────────────────────
def _hwp(name: str, data: bytes) -> ParseResult:
    """HWP/HWPX 텍스트 추출. 실패 시 빈 텍스트 → 파이프라인에서 failed 처리(§7.H)."""
    try:
        from . import hwp_support
        if name.endswith(".hwpx"):
            return ParseResult(hwp_support.extract_hwpx(data), mime_type="application/hwpx")
        return ParseResult(hwp_support.extract_hwp(data), mime_type="application/hwp")
    except Exception:
        return ParseResult("", needs_ocr=False, mime_type="application/hwp")
