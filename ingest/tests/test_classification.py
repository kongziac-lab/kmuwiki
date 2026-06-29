import unittest

from kmu_ingest.classification import classify_document


class TestDocumentClassification(unittest.TestCase):
    def test_classifies_dispatch_exchange_documents(self):
        result = classify_document(
            filename="2026학년도 파견교환학생 선발 계획.txt",
            path_in_zip="기안/2026학년도 파견교환학생 선발 계획.txt",
            text="제 목 2026학년도 파견교환학생 선발 계획\n면접전형 및 추천 절차 안내",
        )

        self.assertEqual(result.task_category, "파견교환학생")
        self.assertGreaterEqual(result.confidence, 0.9)
        self.assertFalse(result.review_required)

    def test_unknown_documents_require_review(self):
        result = classify_document(
            filename="기타 보고.txt",
            path_in_zip="기타 보고.txt",
            text="제 목 내부 업무 참고 자료",
        )

        self.assertEqual(result.task_category, "미분류")
        self.assertEqual(result.confidence, 0.0)
        self.assertTrue(result.review_required)
