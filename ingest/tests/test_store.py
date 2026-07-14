import unittest
from types import SimpleNamespace

from kmu_ingest.config import Settings
from kmu_ingest.metadata import build_file_meta
from kmu_ingest.models import AssetStatus, Chunk, DocumentAsset, SearchUnit
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


class _Query:
    def __init__(self, client, data=None):
        self.client = client
        self.data = [] if data is None else data

    def select(self, *_args, **_kwargs): return self
    def eq(self, *_args, **_kwargs): return self
    def execute(self): return SimpleNamespace(data=self.data)


class _Client:
    def __init__(self):
        self.rpc_call = None

    def table(self, _name): return _Query(self)

    def rpc(self, name, params):
        self.rpc_call = (name, params)
        return _Query(self)


class _Bucket:
    def __init__(self):
        self.uploaded = []
        self.removed = []

    def upload(self, *, path, file, file_options):
        self.uploaded.append((path, file, file_options))

    def remove(self, paths):
        self.removed.extend(paths)


class _Storage:
    def __init__(self, bucket):
        self.bucket = bucket

    def from_(self, _name):
        return self.bucket


class _FailingRPCQuery(_Query):
    def execute(self):
        raise RuntimeError("database transaction failed")


class _FailingRPCClient(_Client):
    def __init__(self):
        super().__init__()
        self.bucket = _Bucket()
        self.storage = _Storage(self.bucket)

    def rpc(self, name, params):
        self.rpc_call = (name, params)
        return _FailingRPCQuery(self)


class TestAtomicV2Store(unittest.TestCase):
    def test_v2_and_rollback_chunks_share_one_rpc_transaction(self):
        store = SupabaseStore.__new__(SupabaseStore)
        store.c = _Client()
        store.settings = Settings(write_legacy_index=True)
        vector = [0.0] * 1024

        store.replace_index_v2(
            "doc-id",
            [],
            [SearchUnit(0, "검색 본문")],
            [vector],
            "embed-v4.0",
            "v4.0-1024",
            visual_status="ready",
            legacy_chunks=[Chunk(0, "검색 본문")],
            legacy_embeddings=[vector],
        )

        name, params = store.c.rpc_call
        self.assertEqual(name, "replace_document_index_v2")
        self.assertEqual(params["legacy_rows"][0]["embed_model"], "embed-v4.0")
        self.assertEqual(len(params["legacy_rows"][0]["embedding"]), 1024)

    def test_new_derivative_is_removed_when_atomic_rpc_fails(self):
        store = SupabaseStore.__new__(SupabaseStore)
        store.c = _FailingRPCClient()
        store.settings = Settings(write_legacy_index=False)
        asset = DocumentAsset(
            asset_index=0,
            asset_type="page",
            image_bytes=b"redacted-only",
            media_type="image/jpeg",
            status=AssetStatus.READY,
            redaction_applied=True,
        )

        with self.assertRaisesRegex(RuntimeError, "database transaction failed"):
            store.replace_index_v2(
                "doc-id", [asset], [SearchUnit(0, "검색 본문")],
                [[0.0] * 1024], "embed-v4.0", "v4.0-1024",
                visual_status="ready",
            )

        self.assertEqual(len(store.c.bucket.uploaded), 1)
        self.assertEqual(store.c.bucket.removed, [asset.storage_path])


if __name__ == "__main__":
    unittest.main()
