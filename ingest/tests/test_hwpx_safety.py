import io
import unittest
import zipfile

from kmu_ingest.hwp_support import extract_hwpx


class TestHwpxParsingSafety(unittest.TestCase):
    def test_extracts_normal_section_xml(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("Contents/section0.xml", "<hp:t>안전한 본문</hp:t>")

        self.assertIn("안전한 본문", extract_hwpx(archive.getvalue()))

    def test_rejects_nested_zip_bomb_ratio(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("Contents/section0.xml", "0" * 100_000)

        with self.assertRaisesRegex(ValueError, "compression ratio"):
            extract_hwpx(archive.getvalue())


if __name__ == "__main__":
    unittest.main()
