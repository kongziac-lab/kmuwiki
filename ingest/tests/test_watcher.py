import tempfile
import unittest
import zipfile
from pathlib import Path

from kmu_ingest.watcher import iter_work, iter_zip_files


class CaptureZipStore:
    def __init__(self):
        self.registered = []

    def zip_seen(self, sha256):
        return False

    def register_zip(self, filename, sha256, file_count, *, source_path=None):
        self.registered.append({
            "filename": filename,
            "sha256": sha256,
            "file_count": file_count,
            "source_path": source_path,
        })
        return "zip-id"


class TestWatcherSourcePaths(unittest.TestCase):
    def test_iter_zip_files_recurses_from_single_drop_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "flat.zip").touch()
            nested = root / "국제교류" / "2026" / "파견교환학생"
            nested.mkdir(parents=True)
            (nested / "nested.zip").touch()

            found = [p.relative_to(root).as_posix() for p in iter_zip_files(str(root))]

        self.assertEqual(found, [
            "flat.zip",
            "국제교류/2026/파견교환학생/nested.zip",
        ])

    def test_iter_work_registers_relative_source_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "incoming" / "2026"
            nested.mkdir(parents=True)
            zip_path = nested / "download.zip"
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("기안문.txt", "제 목 파견교환학생 선발 계획")

            store = CaptureZipStore()
            items = list(iter_work(zip_path, store, zip_root=root))

        self.assertEqual(len(items), 1)
        self.assertEqual(store.registered[0]["filename"], "download.zip")
        self.assertEqual(store.registered[0]["source_path"], "incoming/2026/download.zip")


if __name__ == "__main__":
    unittest.main()
