import io
import unittest
import zipfile

from kmu_query.hwpx_export import HWPX_MIME, build_approval_hwpx, safe_hwpx_filename


class TestHwpxExport(unittest.TestCase):
    def test_builds_hwpx_package_with_approval_content(self):
        data = build_approval_hwpx(
            title="2027년도 2학기 해외 파견 교환학생 후보 선발 시험 실시.hwpx",
            body="본문입니다.\n붙임 1. 계획(안) 1부",
            source_label="국제교류팀 · 국제교류팀-1843 · 2026-02-27",
            approval_form_plan=["전자결재 PDF의 기본 결재문 영역을 HWPX 섹션으로 재구성"],
        )

        self.assertTrue(data.startswith(b"PK"))
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            self.assertEqual(zf.read("mimetype").decode("utf-8"), HWPX_MIME)
            self.assertIn("Contents/content.hpf", zf.namelist())
            self.assertIn("Contents/header.xml", zf.namelist())
            section_xml = zf.read("Contents/section0.xml").decode("utf-8")
            preview = zf.read("Preview/PrvText.txt").decode("utf-8")

        self.assertIn("전자결재 문서 초안", section_xml)
        self.assertIn("국제교류팀-1843", section_xml)
        self.assertIn("붙임 1. 계획(안) 1부", section_xml)
        self.assertIn("본문입니다.", preview)

    def test_safe_hwpx_filename_normalizes_extension(self):
        self.assertEqual(safe_hwpx_filename("결재문.pdf"), "결재문.hwpx")
        self.assertEqual(safe_hwpx_filename("../결재문.docx"), "결재문.hwpx")


if __name__ == "__main__":
    unittest.main()
