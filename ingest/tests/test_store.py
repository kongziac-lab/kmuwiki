import unittest

from kmu_ingest.metadata import build_file_meta
from kmu_ingest.store import SupabaseStore


class TestDocumentRow(unittest.TestCase):
    def _meta(self, **fields):
        return build_file_meta("기안문.pdf", "기안문.pdf", "application/pdf", fields)

    def test_security_level_none_is_omitted_to_preserve_operator_grade(self):
        # 파이프라인 meta 는 security_level=None(§7.B) → 컬럼을 보내지 않아
        # 재처리(run --force)가 관리자 승급('일반')을 NULL 로 덮지 않는다.
        row = SupabaseStore.document_row(
            sha256="a" * 64, zip_id="z1", meta=self._meta(), status="processed",
        )
        self.assertNotIn("security_level", row)

    def test_explicit_security_level_is_written(self):
        meta = self._meta()
        meta.security_level = "일반"
        row = SupabaseStore.document_row(
            sha256="a" * 64, zip_id="z1", meta=meta, status="processed",
        )
        self.assertEqual(row["security_level"], "일반")

    def test_row_keeps_core_identity_and_status_fields(self):
        row = SupabaseStore.document_row(
            sha256="b" * 64, zip_id="z2", meta=self._meta(), status="pending_ocr",
        )
        self.assertEqual(row["sha256"], "b" * 64)
        self.assertEqual(row["status"], "pending_ocr")
        self.assertIsNone(row["processed_at"])  # processed 일 때만 기록


if __name__ == "__main__":
    unittest.main()
