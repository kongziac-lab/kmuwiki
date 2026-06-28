import unittest

from kmu_ingest.config import EMBED_DIM, Settings
from kmu_ingest.embedding import make_embedder
from kmu_ingest.models import DocStatus
from kmu_ingest.ocr import OCREngine
from kmu_ingest.pii.masker import MaskResult, Masker
from kmu_ingest.pii.policy import MaskPolicy
from kmu_ingest.pipeline import Deps, WorkItem, process
from kmu_ingest.store import DryRunStore


def make_deps(masker=None):
    s = Settings(dry_run=True, embed_provider="fake")
    return Deps(
        settings=s,
        store=DryRunStore(),
        masker=masker or Masker(enable_ner=False),
        ocr=OCREngine("none"),
        embedder=make_embedder("fake", "fake-deterministic", "v1"),
    )


def item(filename, data, zip_enc=False, path=None):
    return WorkItem(zip_sha256="ziphash", zip_id="zid",
                    path_in_zip=path or filename, filename=filename,
                    data=data, zip_entry_encrypted=zip_enc)


class TestPipeline(unittest.TestCase):
    def test_text_doc_processed_and_embedded(self):
        deps = make_deps()
        data = "기안 내용. 담당자 900101-1234567 010-1234-5678".encode()
        st = process(item("기안문.txt", data), deps)
        self.assertEqual(st, DocStatus.PROCESSED)
        # 임베딩 차원 고정 검증
        vecs = deps.embedder.embed(["x"])
        self.assertEqual(len(vecs[0]), EMBED_DIM)

    def test_zip_locked_entry_is_pending_password_without_body(self):
        deps = make_deps()
        st = process(item("secret.pdf", b"", zip_enc=True), deps)
        self.assertEqual(st, DocStatus.PENDING_PASSWORD)

    def test_pdf_file_level_encrypt_is_pending_password(self):
        deps = make_deps()
        data = b"%PDF-1.7\n ... /Encrypt 5 0 R ... "
        st = process(item("scan.pdf", data), deps)
        self.assertEqual(st, DocStatus.PENDING_PASSWORD)

    def test_locked_entries_get_distinct_ids(self):
        deps = make_deps()
        process(item("a.pdf", b"", zip_enc=True, path="dir/a.pdf"), deps)
        process(item("b.pdf", b"", zip_enc=True, path="dir/b.pdf"), deps)
        # 서로 다른 경로 → 서로 다른 해시 → 둘 다 기록(충돌 없음)
        self.assertEqual(len(deps.store._docs), 2)

    def test_idempotent_second_run_skips(self):
        deps = make_deps()
        wi = item("기안문.txt", "내용 hello world".encode())
        first = process(wi, deps)
        second = process(wi, deps)  # 동일 해시 → 재처리 안 함
        self.assertEqual(first, DocStatus.PROCESSED)
        self.assertEqual(second, DocStatus.PROCESSED)

    def test_egress_gate_quarantines_when_masking_fails(self):
        # 마스킹이 PII를 놓친 상황 시뮬레이션(원문 그대로 반환)
        class NoMask:
            policy = MaskPolicy.internal()

            def mask(self, text):
                return MaskResult(text=text, counts={}, ner_available=False)

        deps = make_deps(masker=NoMask())
        data = "남은 주민번호 900101-1234567".encode()
        st = process(item("기안문.txt", data), deps)
        self.assertEqual(st, DocStatus.QUARANTINE)

    def test_empty_text_is_failed(self):
        deps = make_deps()
        st = process(item("빈문서.txt", b"   "), deps)
        self.assertEqual(st, DocStatus.FAILED)

    def test_unparsable_image_without_ocr_is_pending_ocr(self):
        deps = make_deps()  # ocr backend none
        st = process(item("scan.png", b"\x89PNG\r\n\x1a\n fake"), deps)
        self.assertEqual(st, DocStatus.PENDING_OCR)


if __name__ == "__main__":
    unittest.main()
