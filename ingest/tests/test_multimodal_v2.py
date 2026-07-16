import io
import sys
import types
import unittest
from unittest.mock import patch

from PIL import Image

from kmu_ingest.config import EMBED_DIM, Settings
from kmu_ingest.embedding import (
    CohereEmbedder, EmbeddingInput, FakeEmbedder, _multimodal_batches,
)
from kmu_ingest.hashing import sha256_bytes
from kmu_ingest.layout import LayoutAnalysis, LayoutAnalyzer
from kmu_ingest.models import AssetStatus, DocStatus, ParsedAsset
from kmu_ingest.ocr import OCRAnalysis, OCRSpan, OCREngine, _paddle_v3_analysis
from kmu_ingest.pii.masker import Masker
from kmu_ingest.pii.policy import MaskPolicy
from kmu_ingest.pipeline import Deps, WorkItem, _enrich_layout_assets, process
from kmu_ingest.store import DryRunStore
from kmu_ingest.visual import SanitizedVisual, VisualSanitizer
from kmu_query.rag import build_context, citations
from kmu_query.retriever import Source
from kmu_query.visual_assets import load_visual_inputs


def _png_bytes() -> bytes:
    image = Image.new("RGB", (320, 120), "white")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _item(data: bytes) -> WorkItem:
    return WorkItem(
        zip_sha256="ziphash",
        zip_id="zip-id",
        path_in_zip="scan.png",
        filename="scan.png",
        data=data,
        zip_entry_encrypted=False,
    )


class _SafeVisualSanitizer:
    def __init__(self):
        self.called = 0

    def sanitize(self, _image, *, masker):
        self.called += 1
        return SanitizedVisual(
            True,
            image_bytes=b"redacted-derivative",
            media_type="image/jpeg",
            width=320,
            height=120,
            masked_ocr_text="표 제목과 합계",
            redaction_applied=True,
        )


class _CapturingMultimodalEmbedder(FakeEmbedder):
    def __init__(self):
        super().__init__("fake-multimodal", "v2")
        self.inputs = []

    def embed_inputs(self, inputs):
        self.inputs = list(inputs)
        return super().embed_inputs(inputs)


class TestMultimodalPipeline(unittest.TestCase):
    def test_text_document_is_written_to_v2_search_units(self):
        settings = Settings(dry_run=True, embed_provider="fake", ocr_backend="none")
        store = DryRunStore()
        deps = Deps(
            settings=settings,
            store=store,
            masker=Masker(enable_ner=False),
            ocr=OCREngine("none"),
            embedder=FakeEmbedder(),
        )

        status = process(WorkItem(
            zip_sha256="ziphash", zip_id="zip-id", path_in_zip="a.txt",
            filename="a.txt", data="검색 가능한 본문".encode(), zip_entry_encrypted=False,
        ), deps)

        self.assertEqual(status, DocStatus.PROCESSED)
        self.assertTrue(store.search_units)
        self.assertTrue(all(unit.modality == "text" for unit in store.search_units))

    def test_unreviewed_visual_never_reaches_sanitizer_or_embedder(self):
        payload = _png_bytes()
        settings = Settings(dry_run=True, embed_provider="fake", ocr_backend="none")
        store = DryRunStore()  # security_level remains deny-by-default None
        sanitizer = _SafeVisualSanitizer()
        embedder = _CapturingMultimodalEmbedder()
        ocr = OCREngine("none")
        ocr.available = True
        ocr.image_to_text = lambda _data: "스캔 표 본문"
        deps = Deps(
            settings=settings,
            store=store,
            masker=Masker(enable_ner=False),
            ocr=ocr,
            embedder=embedder,
            visual_masker=Masker(enable_ner=False),
            visual_sanitizer=sanitizer,
        )

        status = process(_item(payload), deps)

        self.assertEqual(status, DocStatus.PROCESSED)
        self.assertEqual(sanitizer.called, 0)
        self.assertEqual(store.assets[0].status, AssetStatus.PENDING_REVIEW)
        self.assertTrue(all(value.image_bytes is None for value in embedder.inputs))

    def test_reviewed_redacted_visual_is_embedded_as_mixed_input(self):
        payload = _png_bytes()
        settings = Settings(dry_run=True, embed_provider="fake", ocr_backend="none")
        store = DryRunStore()
        store._security_levels[sha256_bytes(payload)] = "일반"
        sanitizer = _SafeVisualSanitizer()
        embedder = _CapturingMultimodalEmbedder()
        ocr = OCREngine("none")
        ocr.available = True
        ocr.image_to_text = lambda _data: "스캔 표 본문"
        deps = Deps(
            settings=settings,
            store=store,
            masker=Masker(enable_ner=False),
            ocr=ocr,
            embedder=embedder,
            visual_masker=Masker(enable_ner=False),
            visual_sanitizer=sanitizer,
        )

        status = process(_item(payload), deps)

        self.assertEqual(status, DocStatus.PROCESSED)
        self.assertEqual(sanitizer.called, 1)
        self.assertEqual(store.assets[0].status, AssetStatus.READY)
        self.assertTrue(any(unit.modality == "mixed" for unit in store.search_units))
        self.assertTrue(any(value.image_bytes == b"redacted-derivative" for value in embedder.inputs))

    def test_visual_text_is_quarantined_when_all_pii_ner_is_unavailable(self):
        payload = _png_bytes()
        settings = Settings(dry_run=True, embed_provider="fake", ocr_backend="none")
        store = DryRunStore()
        store._security_levels[sha256_bytes(payload)] = "일반"
        ocr = OCREngine("none")
        ocr.available = True
        ocr.image_to_text = lambda _data: "김민수 담당자 표"
        deps = Deps(
            settings=settings,
            store=store,
            masker=Masker(enable_ner=False),
            ocr=ocr,
            embedder=_CapturingMultimodalEmbedder(),
            visual_masker=Masker(
                enable_ner=False, policy=MaskPolicy.all()),
            visual_sanitizer=_SafeVisualSanitizer(),
        )

        status = process(_item(payload), deps)

        self.assertEqual(status, DocStatus.QUARANTINE)


class _FakeLayoutAnalyzer:
    available = True

    def analyze(self, _payload, *, page_no=None):
        return LayoutAnalysis(
            markdown="## 표\n| 항목 | 값 |\n|---|---|\n| 예산 | 10 |",
            assets=[ParsedAsset(
                asset_type="table",
                page_no=page_no,
                structured_content="| 항목 | 값 |\n|---|---|\n| 예산 | 10 |",
                image_bytes=b"local-table-crop",
                media_type="image/png",
                extraction_model="PP-StructureV3",
                extraction_version="v3",
            )],
        )


class TestLayoutExtraction(unittest.TestCase):
    def test_ppstructure_disables_mkldnn(self):
        calls = []

        class _Pipeline:
            def __init__(self, **kwargs):
                calls.append(kwargs)

        module = types.SimpleNamespace(PPStructureV3=_Pipeline)
        with patch.dict(sys.modules, {"paddleocr": module}):
            analyzer = LayoutAnalyzer("ppstructure")
            analyzer._ensure()

        self.assertEqual(calls, [{
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "use_table_recognition": False,
            "use_formula_recognition": False,
            "use_chart_recognition": False,
            "use_seal_recognition": False,
            "enable_mkldnn": False,
        }])

    def test_layout_markdown_and_regions_are_attached_to_page(self):
        assets = [ParsedAsset(
            asset_type="page", page_no=2, image_bytes=_png_bytes(), media_type="image/png",
        )]

        text = _enrich_layout_assets(assets, _FakeLayoutAnalyzer())

        self.assertIn("예산", text)
        self.assertIn("예산", assets[0].structured_content)
        self.assertEqual(assets[1].asset_type, "table")
        self.assertEqual(assets[1].page_no, 2)

    def test_ppstructure_result_normalizes_markdown_and_crops(self):
        class _Result:
            markdown = {"markdown_texts": "# 문서\n표 설명"}
            json = {"res": {"parsing_res_list": [{
                "block_label": "table",
                "block_bbox": [10, 10, 120, 80],
                "block_content": "| A | B |",
            }]}}

        class _Pipeline:
            def predict(self, _image):
                return [_Result()]

        analyzer = LayoutAnalyzer("ppstructure")
        analyzer._pipeline = _Pipeline()
        analysis = analyzer.analyze(_png_bytes(), page_no=3)

        self.assertTrue(analysis.succeeded)
        self.assertIn("표 설명", analysis.markdown)
        self.assertEqual(analysis.assets[0].page_no, 3)
        self.assertGreater(len(analysis.assets[0].image_bytes or b""), 10)


class _NER:
    def mask(self, text):
        return text, {}


class _SequenceOCR:
    def __init__(self, analyses):
        self.analyses = list(analyses)

    def analyze(self, _payload):
        return self.analyses.pop(0)


class TestVisualSanitizer(unittest.TestCase):
    def test_paddle_ocr_disables_mkldnn(self):
        calls = []

        class _Reader:
            def __init__(self, **kwargs):
                calls.append(kwargs)

        module = types.SimpleNamespace(PaddleOCR=_Reader)
        with patch.dict(sys.modules, {"paddleocr": module}):
            ocr = OCREngine("paddle")
            ocr._ensure()

        self.assertFalse(calls[0]["enable_mkldnn"])

    def test_redacts_and_rechecks_policy_matched_pixels(self):
        first = OCRAnalysis(spans=[OCRSpan(
            "900101-1234567", (10, 10, 180, 45), 0.99,
        )])
        second = OCRAnalysis(spans=[])
        masker = Masker(enable_ner=True, ner=_NER(), policy=MaskPolicy.all())
        sanitizer = VisualSanitizer(
            _SequenceOCR([first, second]),
            verify_after_redaction=True,
        )

        result = sanitizer.sanitize(_png_bytes(), masker=masker)

        self.assertTrue(result.safe)
        self.assertTrue(result.redaction_applied)
        self.assertIn("[주민등록번호]", result.masked_ocr_text)
        self.assertNotEqual(result.image_bytes, _png_bytes())

    def test_clean_visual_records_completed_redaction_verification(self):
        first = OCRAnalysis(spans=[OCRSpan("회의실", (10, 10, 80, 45), 0.99)])
        second = OCRAnalysis(spans=[OCRSpan("회의실", (10, 10, 80, 45), 0.99)])
        sanitizer = VisualSanitizer(
            _SequenceOCR([first, second]),
            verify_after_redaction=True,
        )

        result = sanitizer.sanitize(_png_bytes(), masker=Masker(policy=MaskPolicy.all()))

        self.assertTrue(result.safe)
        self.assertTrue(result.redaction_applied)

    def test_fails_closed_without_local_ocr(self):
        masker = Masker(enable_ner=True, ner=_NER(), policy=MaskPolicy.all())
        sanitizer = VisualSanitizer(
            _SequenceOCR([OCRAnalysis(succeeded=False, error="OCR unavailable")])
        )
        result = sanitizer.sanitize(_png_bytes(), masker=masker)
        self.assertFalse(result.safe)
        self.assertIn("OCR", result.error)

    def test_paddle_v3_result_keeps_recognition_boxes(self):
        class Result:
            json = {"res": {
                "rec_texts": ["국민대학교"],
                "rec_scores": [0.98],
                "rec_polys": [[[5, 6], [100, 6], [100, 30], [5, 30]]],
            }}

        class Reader:
            def predict(self, _image):
                return [Result()]

        analysis = _paddle_v3_analysis(Reader(), _png_bytes())
        self.assertEqual(analysis.text, "국민대학교")
        self.assertEqual(analysis.spans[0].bbox, (5.0, 6.0, 100.0, 30.0))
        self.assertAlmostEqual(analysis.spans[0].confidence, 0.98)


class _Embeddings:
    def __init__(self, count):
        self.float_ = [[0.0] * EMBED_DIM for _ in range(count)]


class _CohereResponse:
    def __init__(self, count):
        self.embeddings = _Embeddings(count)


class _CohereClient:
    calls = []

    def __init__(self, *_args, **_kwargs):
        pass

    def embed(self, **kwargs):
        type(self).calls.append(kwargs)
        count = len(kwargs.get("inputs") or kwargs.get("texts") or [])
        return _CohereResponse(count)


class TestCohereEmbedV4(unittest.TestCase):
    def setUp(self):
        self.original = sys.modules.get("cohere")
        sys.modules["cohere"] = types.SimpleNamespace(ClientV2=_CohereClient)
        _CohereClient.calls = []

    def tearDown(self):
        if self.original is None:
            sys.modules.pop("cohere", None)
        else:
            sys.modules["cohere"] = self.original

    def test_mixed_input_uses_v4_inputs_and_pins_1024_dimensions(self):
        embedder = CohereEmbedder("embed-v4.0", "v4.0-1024", api_key="test")
        vectors = embedder.embed_inputs([EmbeddingInput(
            text="표 제목", image_bytes=b"redacted", media_type="image/jpeg",
        )])

        call = _CohereClient.calls[0]
        self.assertEqual(call["output_dimension"], 1024)
        self.assertEqual(call["input_type"], "search_document")
        self.assertEqual(call["inputs"][0]["content"][1]["type"], "image_url")
        self.assertEqual(len(vectors[0]), 1024)

    def test_v3_cannot_silently_build_visual_index(self):
        embedder = CohereEmbedder("embed-multilingual-v3.0", "v3", api_key="test")
        with self.assertRaises(ValueError):
            embedder.embed_inputs([EmbeddingInput("x", b"redacted", "image/jpeg")])

    def test_visual_batches_leave_room_for_base64_expansion(self):
        items = [
            EmbeddingInput("a", b"x" * (7 * 1024 * 1024), "image/jpeg"),
            EmbeddingInput("b", b"y" * (7 * 1024 * 1024), "image/jpeg"),
        ]
        batches = list(_multimodal_batches(items))
        self.assertEqual([len(batch) for batch in batches], [1, 1])


class _ImageHeaders:
    def get_content_type(self):
        return "image/jpeg"


class _ImageResponse:
    headers = _ImageHeaders()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size):
        return b"safe-redacted-image"


class TestAuthorizedVisualRetrieval(unittest.TestCase):
    def _source(self, path="doc-1/0-deadbeef.jpg"):
        return Source(
            document_id="doc-1",
            chunk_index=2,
            content="마스킹된 표 설명",
            score=0.9,
            filename="보고서.pdf",
            search_unit_id="unit-1",
            asset_id="asset-1",
            modality="mixed",
            asset_type="table",
            page_no=3,
            bbox=[10, 20, 200, 300],
            storage_path=path,
        )

    @patch("kmu_query.visual_assets.urllib.request.urlopen", return_value=_ImageResponse())
    def test_downloads_redacted_derivative_with_user_jwt(self, urlopen):
        visuals = load_visual_inputs(
            [self._source()],
            supabase_url="https://example.supabase.co",
            anon_key="anon",
            user_jwt="user-jwt",
            bucket="kmuwiki-assets",
        )

        self.assertEqual(len(visuals), 1)
        self.assertEqual(visuals[0].data, b"safe-redacted-image")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.headers["Authorization"], "Bearer user-jwt")
        self.assertIn("/object/authenticated/kmuwiki-assets/doc-1/", request.full_url)

    @patch("kmu_query.visual_assets.urllib.request.urlopen")
    def test_rejects_cross_document_or_traversal_path_before_network(self, urlopen):
        visuals = load_visual_inputs(
            [self._source("other/secret.jpg"), self._source("doc-1/../secret.jpg")],
            supabase_url="https://example.supabase.co",
            anon_key="anon",
            user_jwt="user-jwt",
            bucket="kmuwiki-assets",
        )
        self.assertEqual(visuals, [])
        urlopen.assert_not_called()

    def test_context_and_citation_keep_visual_locator(self):
        source = self._source()
        context = build_context([source])
        citation = citations([source])[0]
        self.assertIn("p.3", context)
        self.assertIn("table", context)
        self.assertEqual(citation["asset_id"], "asset-1")
        self.assertEqual(citation["bbox"], [10, 20, 200, 300])


if __name__ == "__main__":
    unittest.main()
