import tempfile
import unittest
import zipfile
from pathlib import Path

from kmu_ingest.backfill import BackfillCandidate, backfill_candidates, bounded_passwords, run_backfill


class TestBackfillPlanning(unittest.TestCase):
    def test_only_pending_password_and_ocr_are_selected(self):
        rows = [
            {"id": "p1", "status": "processed", "sha256": "s1", "path_in_zip": "done.pdf", "filename": "done.pdf"},
            {"id": "p2", "status": "pending_password", "sha256": "s2", "path_in_zip": "locked.pdf", "filename": "locked.pdf"},
            {
                "id": "p3", "status": "pending_ocr", "sha256": "s3",
                "path_in_zip": "scan.pdf", "filename": "scan.pdf",
                "zip_archives": {"filename": "archive.zip", "source_path": "incoming/2026/archive.zip"},
            },
            {"id": "p4", "status": "failed", "sha256": "s4", "path_in_zip": "bad.pdf", "filename": "bad.pdf"},
        ]

        selected = backfill_candidates(rows)

        self.assertEqual([c.document_id for c in selected], ["p2", "p3"])
        self.assertEqual([c.status for c in selected], ["pending_password", "pending_ocr"])
        self.assertEqual(selected[1].zip_source_path, "incoming/2026/archive.zip")

    def test_password_dictionary_is_bounded_and_deduplicated(self):
        passwords = bounded_passwords(["", "1234", "1234", "2026", "  kmu  "], max_attempts=3)

        self.assertEqual(passwords, ["1234", "2026", "kmu"])

    def test_backfill_candidate_records_manual_queue_reason(self):
        candidate = BackfillCandidate(
            document_id="doc-1",
            sha256="sha",
            status="pending_password",
            zip_filename="archive.zip",
            zip_source_path=None,
            path_in_zip="locked.hwp",
            filename="locked.hwp",
        )

        self.assertEqual(candidate.manual_queue("unsupported file-level encryption")["reason"],
                         "unsupported file-level encryption")

    def test_backfill_uses_source_path_to_find_nested_zip(self):
        class FakeDeps:
            reprocess_statuses = set()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "incoming" / "2026"
            nested.mkdir(parents=True)
            with zipfile.ZipFile(nested / "archive.zip", "w") as zf:
                zf.writestr("scan.txt", "OCR 대기 문서")

            stats = run_backfill(
                candidates=[
                    BackfillCandidate(
                        document_id="doc-1",
                        sha256="sha",
                        status="pending_ocr",
                        zip_filename="archive.zip",
                        zip_source_path="incoming/2026/archive.zip",
                        path_in_zip="scan.txt",
                        filename="scan.txt",
                    )
                ],
                zip_dir=str(root),
                deps=FakeDeps(),
                passwords=[],
                dry_run=True,
            )

        self.assertEqual(stats["would_pending_ocr"], 1)


if __name__ == "__main__":
    unittest.main()
