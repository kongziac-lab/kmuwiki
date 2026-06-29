import unittest

from kmu_ingest.backfill import BackfillCandidate, backfill_candidates, bounded_passwords


class TestBackfillPlanning(unittest.TestCase):
    def test_only_pending_password_and_ocr_are_selected(self):
        rows = [
            {"id": "p1", "status": "processed", "sha256": "s1", "path_in_zip": "done.pdf", "filename": "done.pdf"},
            {"id": "p2", "status": "pending_password", "sha256": "s2", "path_in_zip": "locked.pdf", "filename": "locked.pdf"},
            {"id": "p3", "status": "pending_ocr", "sha256": "s3", "path_in_zip": "scan.pdf", "filename": "scan.pdf"},
            {"id": "p4", "status": "failed", "sha256": "s4", "path_in_zip": "bad.pdf", "filename": "bad.pdf"},
        ]

        selected = backfill_candidates(rows)

        self.assertEqual([c.document_id for c in selected], ["p2", "p3"])
        self.assertEqual([c.status for c in selected], ["pending_password", "pending_ocr"])

    def test_password_dictionary_is_bounded_and_deduplicated(self):
        passwords = bounded_passwords(["", "1234", "1234", "2026", "  kmu  "], max_attempts=3)

        self.assertEqual(passwords, ["1234", "2026", "kmu"])

    def test_backfill_candidate_records_manual_queue_reason(self):
        candidate = BackfillCandidate(
            document_id="doc-1",
            sha256="sha",
            status="pending_password",
            zip_filename="archive.zip",
            path_in_zip="locked.hwp",
            filename="locked.hwp",
        )

        self.assertEqual(candidate.manual_queue("unsupported file-level encryption")["reason"],
                         "unsupported file-level encryption")


if __name__ == "__main__":
    unittest.main()
