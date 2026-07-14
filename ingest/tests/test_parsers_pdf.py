import io
import sys
import unittest

from pypdf import PdfWriter

from kmu_ingest import parsers


def _blank_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class _BrokenPlumber:
    """pdfminer 계열 파서가 특정 PDF에서 던지는 예외를 재현한다."""

    @staticmethod
    def open(*_args, **_kwargs):
        raise RuntimeError("Invalid octal b'454'")


class TestPdfFallback(unittest.TestCase):
    def setUp(self):
        self._real = sys.modules.get("pdfplumber")
        sys.modules["pdfplumber"] = _BrokenPlumber()

    def tearDown(self):
        if self._real is None:
            sys.modules.pop("pdfplumber", None)
        else:
            sys.modules["pdfplumber"] = self._real

    def test_pdfplumber_crash_falls_back_to_pypdf(self):
        # pdfplumber 가 죽어도 pypdf 가 읽을 수 있는 PDF 는 failed 가 아니라
        # 정상 ParseResult(빈 텍스트 → OCR 대상)로 이어진다.
        result = parsers._pdf(_blank_pdf_bytes())
        self.assertEqual(result.mime_type, "application/pdf")
        self.assertTrue(result.needs_ocr)

    def test_fallback_failure_reraises_original_parser_error(self):
        # 폴백까지 실패하면 원 파서 예외를 그대로 올려 기존 failed 기록을 유지한다.
        with self.assertRaises(RuntimeError) as ctx:
            parsers._pdf(b"not a pdf at all")
        self.assertIn("Invalid octal", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
