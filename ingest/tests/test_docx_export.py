import io
import unittest
import zipfile

from kmu_query.docx_export import build_approval_docx, safe_docx_filename


class TestDocxExport(unittest.TestCase):
    def test_builds_word_docx_with_approval_form_content(self):
        data = build_approval_docx(
            title="2027년도 2학기 해외 파견 교환학생 후보 선발 시험 실시.docx",
            body="본문입니다.\n붙임 1. 계획(안) 1부",
            source_label="국제교류팀 · 국제교류팀-1843 · 2026-02-27",
            approval_form_plan=["전자결재 PDF의 기본 결재문 영역을 DOCX 섹션으로 재구성"],
        )

        self.assertTrue(data.startswith(b"PK"))
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            document_xml = zf.read("word/document.xml").decode("utf-8")
        self.assertIn("전자결재 문서 초안", document_xml)
        self.assertIn("국제교류팀-1843", document_xml)
        self.assertIn("붙임 1. 계획(안) 1부", document_xml)

    def test_safe_docx_filename_normalizes_extension(self):
        self.assertEqual(safe_docx_filename("결재문.pdf"), "결재문.docx")
        self.assertEqual(safe_docx_filename("../결재문"), "결재문.docx")


if __name__ == "__main__":
    unittest.main()
