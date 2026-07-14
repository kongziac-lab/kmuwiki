import io
import unittest
import zipfile
import xml.etree.ElementTree as ET

from kmu_query.hwpx_export import HWPX_MIME, build_approval_hwpx, fill_template_hwpx, safe_hwpx_filename


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
            self.assertEqual(zf.namelist()[:6], [
                "mimetype",
                "version.xml",
                "Contents/header.xml",
                "Contents/section0.xml",
                "Preview/PrvText.txt",
                "settings.xml",
            ])
            self.assertEqual(zf.read("mimetype").decode("utf-8"), HWPX_MIME)
            self.assertIn("Contents/content.hpf", zf.namelist())
            self.assertIn("Contents/header.xml", zf.namelist())
            self.assertIn("settings.xml", zf.namelist())
            self.assertIn("META-INF/container.rdf", zf.namelist())
            self.assertIn("META-INF/container.xml", zf.namelist())
            self.assertIn("META-INF/manifest.xml", zf.namelist())
            self.assertEqual(zf.getinfo("mimetype").compress_type, zipfile.ZIP_STORED)
            self.assertEqual(zf.getinfo("META-INF/manifest.xml").compress_type, zipfile.ZIP_DEFLATED)
            section_xml = zf.read("Contents/section0.xml").decode("utf-8")
            preview = zf.read("Preview/PrvText.txt").decode("utf-8")
            for name in ["version.xml", "settings.xml", "Contents/content.hpf",
                         "Contents/header.xml", "Contents/section0.xml",
                         "META-INF/container.xml", "META-INF/manifest.xml",
                         "META-INF/container.rdf"]:
                ET.fromstring(zf.read(name))

        self.assertIn("전자결재 문서 초안", section_xml)
        self.assertIn("국제교류팀-1843", section_xml)
        self.assertIn("붙임 1. 계획(안) 1부", section_xml)
        self.assertIn("본문입니다.", preview)

    def test_safe_hwpx_filename_normalizes_extension(self):
        self.assertEqual(safe_hwpx_filename("결재문.pdf"), "결재문.hwpx")
        self.assertEqual(safe_hwpx_filename("../결재문.docx"), "결재문.hwpx")

    def test_fills_uploaded_hwpx_template_preserving_zip_order_and_compression(self):
        template = io.BytesIO()
        with zipfile.ZipFile(template, "w") as zf:
            zf.writestr("mimetype", HWPX_MIME, compress_type=zipfile.ZIP_STORED)
            zf.writestr("Contents/content.hpf", "<hpf:package><hpf:title>기존</hpf:title></hpf:package>")
            zf.writestr(
                "Contents/section0.xml",
                '<hp:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
                "<hp:p><hp:run><hp:t>제목 자리</hp:t></hp:run></hp:p>"
                "<hp:p><hp:run><hp:t>본문 자리</hp:t></hp:run></hp:p>"
                "<hp:p><hp:run><hp:t>끝 자리</hp:t></hp:run></hp:p>"
                "</hp:sec>",
            )
            zf.writestr("Preview/PrvText.txt", "기존 미리보기")

        data = fill_template_hwpx(
            template_data=template.getvalue(),
            title="보고서.hwpx",
            body="첫 줄\n둘째 줄",
        )

        with zipfile.ZipFile(io.BytesIO(template.getvalue())) as original, zipfile.ZipFile(io.BytesIO(data)) as filled:
            self.assertEqual(filled.namelist(), original.namelist())
            self.assertEqual(
                [info.compress_type for info in filled.infolist()],
                [info.compress_type for info in original.infolist()],
            )
            section_xml = filled.read("Contents/section0.xml").decode("utf-8")
            preview = filled.read("Preview/PrvText.txt").decode("utf-8")

        self.assertIn("<hp:t>보고서</hp:t>", section_xml)
        self.assertIn("<hp:t>첫 줄</hp:t>", section_xml)
        self.assertIn("<hp:t>둘째 줄</hp:t>", section_xml)
        self.assertIn("첫 줄", preview)

    def test_rejects_suspiciously_compressed_template_entry(self):
        template = io.BytesIO()
        with zipfile.ZipFile(template, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Contents/section0.xml", "0" * 100_000)

        with self.assertRaisesRegex(ValueError, "압축률"):
            fill_template_hwpx(
                template_data=template.getvalue(),
                title="보고서.hwpx",
                body="본문",
            )


if __name__ == "__main__":
    unittest.main()
