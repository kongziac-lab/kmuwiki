import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from kmu_ingest.staging import StageLimits, stage_inbox, validate_zip

OLD = time.time() - 3600  # min_age(300s)를 확실히 지난 시각


def _make_zip(path: Path, names=("doc.txt",), content=b"hello", mtime=OLD,
              compression=zipfile.ZIP_STORED) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=compression) as zf:
        for name in names:
            zf.writestr(name, content)
    os.utime(path, (mtime, mtime))


def _write(path: Path, data: bytes, mtime=OLD) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    os.utime(path, (mtime, mtime))


class TestStageInbox(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._td.name)
        self.inbox = root / "00_inbox"
        self.raw = root / "01_raw"
        self.rejected = root / "99_rejected"

    def tearDown(self):
        # 반입본은 0444 — Windows 정리 오류 방지를 위해 쓰기 권한 복원
        for p in self.raw.rglob("*") if self.raw.exists() else []:
            if p.is_file():
                os.chmod(p, 0o666)
        self._td.cleanup()

    def stage(self, **limits_kw):
        return stage_inbox(self.inbox, self.raw, self.rejected,
                           limits=StageLimits(**limits_kw) if limits_kw else None)

    def test_valid_zip_is_staged_preserving_relative_path(self):
        _make_zip(self.inbox / "2026" / "a.zip")

        report = self.stage()

        self.assertEqual(report.staged, ["2026/a.zip"])
        self.assertTrue((self.raw / "2026" / "a.zip").exists())
        self.assertFalse((self.inbox / "2026" / "a.zip").exists())

    def test_recent_file_is_skipped_for_next_run(self):
        _make_zip(self.inbox / "fresh.zip", mtime=time.time())

        report = self.stage()

        self.assertEqual(report.skipped, [("fresh.zip", "recent")])
        self.assertTrue((self.inbox / "fresh.zip").exists())  # 그대로 남아 재시도

    def test_invalid_zip_is_rejected_with_reason_log(self):
        _write(self.inbox / "broken.zip", b"not a zip at all")

        report = self.stage()

        self.assertEqual(report.rejected, [("broken.zip", "invalid-zip")])
        self.assertTrue((self.rejected / "broken.zip").exists())
        log = (self.rejected / "reasons.log").read_text(encoding="utf-8")
        self.assertIn("broken.zip\tinvalid-zip", log)

    def test_non_zip_and_empty_files_are_rejected(self):
        _write(self.inbox / "memo.txt", b"hi")
        _write(self.inbox / "empty.zip", b"")

        report = self.stage()

        reasons = dict(report.rejected)
        self.assertEqual(reasons["memo.txt"], "not-zip")
        self.assertEqual(reasons["empty.zip"], "empty")

    def test_zip_bomb_limits_reject(self):
        _make_zip(self.inbox / "many.zip", names=[f"f{i}.txt" for i in range(30)])
        report = self.stage(min_age_seconds=300, max_entries=10)
        self.assertEqual(report.rejected, [("many.zip", "too-many-entries")])

        _make_zip(self.inbox / "fat.zip", content=b"x" * 5000)
        report = self.stage(min_age_seconds=300, max_uncompressed_bytes=1000)
        self.assertEqual(report.rejected, [("fat.zip", "uncompressed-too-large")])

    def test_single_entry_and_compression_ratio_limits_reject(self):
        _make_zip(self.inbox / "entry.zip", content=b"12345")
        report = self.stage(min_age_seconds=300, max_entry_bytes=4)
        self.assertEqual(report.rejected, [("entry.zip", "entry-too-large")])

        _make_zip(
            self.inbox / "ratio.zip",
            content=b"0" * 10_000,
            compression=zipfile.ZIP_DEFLATED,
        )
        report = self.stage(min_age_seconds=300, max_compression_ratio=2)
        self.assertEqual(report.rejected, [("ratio.zip", "suspicious-compression-ratio")])

    def test_identical_duplicate_is_dropped(self):
        _make_zip(self.raw / "a.zip", content=b"same")
        _make_zip(self.inbox / "a.zip", content=b"same")

        report = self.stage()

        self.assertEqual(report.duplicates, ["a.zip"])
        self.assertFalse((self.inbox / "a.zip").exists())
        self.assertEqual(len(list(self.raw.rglob("*.zip"))), 1)

    def test_same_name_different_content_kept_side_by_side(self):
        _make_zip(self.raw / "a.zip", content=b"old")
        _make_zip(self.inbox / "a.zip", content=b"new")

        report = self.stage()

        self.assertEqual(len(report.staged), 1)
        self.assertTrue(report.staged[0].startswith("a-"))  # a-<sha8>.zip
        self.assertTrue((self.raw / "a.zip").exists())      # 기존 원본 불변
        self.assertEqual(len(list(self.raw.rglob("*.zip"))), 2)

    def test_validate_zip_passes_normal_archive(self):
        p = Path(self._td.name) / "ok.zip"
        _make_zip(p)
        self.assertIsNone(validate_zip(p, StageLimits()))


if __name__ == "__main__":
    unittest.main()
