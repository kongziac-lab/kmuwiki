import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from kmu_ingest.cli import evaluate_cutover
from kmu_ingest.store import SupabaseStore


def _status(**overrides):
    value = {
        "source_archives": {"total": 22},
        "documents": {
            "total": 78, "v1": 7, "v2": 71,
            "processed": 71, "processed_v1": 0,
        },
        "assets": {
            "total": 20, "ready": 18, "pending_review": 2,
            "pending_ocr": 0, "blocked": 0, "failed": 0,
        },
        "search_units": {
            "total": 300, "text": 250, "table": 20, "image": 0, "mixed": 30,
            "models": {"embed-v4.0/v4.0-1024": 300},
        },
        "integrity": {
            "v2_without_search_units": 0,
            "legacy_documents_without_v2": 0,
            "ready_without_storage": 0,
            "ready_without_redaction": 0,
        },
        "legacy_models": {"embed-multilingual-v3.0/v3": 163},
    }
    for section, replacement in overrides.items():
        value[section].update(replacement)
    return value


class TestCutoverGate(unittest.TestCase):
    def _evaluate(self, status):
        return evaluate_cutover(
            status,
            expected_source_archives=22,
            minimum_total_documents=78,
            minimum_v2_documents=71,
            embed_model="embed-v4.0",
            embed_version="v4.0-1024",
        )

    def test_ready_allows_safe_visual_fallback_warnings(self):
        report = self._evaluate(_status())

        self.assertTrue(report["ready"])
        self.assertFalse(report["failures"])
        self.assertIn("pending_review", report["warnings"][0])

    def test_partial_reindex_and_mixed_model_fail_cutover(self):
        status = _status(
            documents={"v1": 12, "v2": 66, "processed": 71, "processed_v1": 5},
            search_units={
                "total": 280,
                "models": {
                    "embed-v4.0/v4.0-1024": 270,
                    "embed-multilingual-v3.0/v3": 10,
                },
            },
        )

        report = self._evaluate(status)

        self.assertFalse(report["ready"])
        self.assertTrue(any("v1에 남아" in item for item in report["failures"]))
        self.assertTrue(any("모델 혼합" in item for item in report["failures"]))

    def test_unredacted_ready_asset_fails_cutover(self):
        report = self._evaluate(_status(
            integrity={"ready_without_redaction": 1},
        ))

        self.assertFalse(report["ready"])
        self.assertTrue(any("마스킹 확인" in item for item in report["failures"]))

    def test_legacy_document_identity_must_exist_in_v2(self):
        report = self._evaluate(_status(
            integrity={"legacy_documents_without_v2": 1},
        ))

        self.assertFalse(report["ready"])
        self.assertTrue(any("기존 검색 가능 문서" in item for item in report["failures"]))

    def test_mixed_rollback_models_fail_cutover(self):
        report = self._evaluate(_status(legacy_models={
            "embed-multilingual-v3.0/v3": 160,
            "unknown/unknown": 3,
        }))

        self.assertFalse(report["ready"])
        self.assertTrue(any("롤백 인덱스" in item for item in report["failures"]))


class _ArchiveQuery:
    def __init__(self, rows):
        self.rows = rows
        self.start = 0
        self.end = len(rows)

    def select(self, _columns):
        return self

    def eq(self, key, value):
        self.rows = [row for row in self.rows if row.get(key) == value]
        return self

    def range(self, start, end):
        self.start = start
        self.end = end + 1
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows[self.start:self.end])


class _ArchiveClient:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        if name != "zip_archives":
            raise AssertionError(name)
        return _ArchiveQuery(list(self.rows))


class TestSourceArchivePreflight(unittest.TestCase):
    def test_reports_available_missing_and_traversal_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "ready.zip").write_bytes(b"zip")
            store = SupabaseStore.__new__(SupabaseStore)
            store.c = _ArchiveClient([
                {"filename": "ready.zip", "source_path": "ready.zip"},
                {"filename": "missing.zip", "source_path": "nested/missing.zip"},
                {"filename": "unsafe.zip", "source_path": "../unsafe.zip"},
            ])

            report = store.source_archive_report(str(root))

        self.assertEqual(report["expected"], 3)
        self.assertEqual(report["available"], 1)
        self.assertEqual(report["missing"], ["nested/missing.zip"])
        self.assertEqual(report["unsafe"], ["../unsafe.zip"])


if __name__ == "__main__":
    unittest.main()
