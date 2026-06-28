import unittest

from evaluation.evaluate import run_eval
from kmu_ingest.pii.masker import Masker
from kmu_ingest.pii.ner import Entity, KoreanNER
from kmu_ingest.pii.policy import MaskPolicy


def name_extractor(text):
    out = []
    for n in ["홍길동", "최지우"]:
        i = text.find(n)
        if i >= 0:
            out.append(Entity("PER", i, i + len(n)))
    return out


def masker_with_names():
    # 성명까지 마스킹하는 정책(예: 민원 문서)에서의 평가
    return Masker(enable_ner=True, ner=KoreanNER(extractor=name_extractor),
                  policy=MaskPolicy.all())


class TestEvalHarness(unittest.TestCase):
    def test_perfect_recall_and_keep(self):
        items = [{
            "id": "t1",
            "text": "기안자 홍길동, 주민 900101-1234567, 문서 제2025-13호 (2025-03-02)",
            "must_mask": [{"type": "성명", "value": "홍길동"},
                          {"type": "주민등록번호", "value": "900101-1234567"}],
            "must_keep": ["제2025-13호", "2025-03-02"],
        }]
        rep = run_eval(items, masker_with_names())
        self.assertEqual(rep.by_type["주민등록번호"].recall, 1.0)
        self.assertEqual(rep.by_type["성명"].recall, 1.0)
        self.assertEqual(rep.keep_ratio, 1.0)      # 날짜·문서번호 보존
        self.assertTrue(rep.passed)

    def test_detects_leak(self):
        # NER 없이 → 이름이 유출되어야 하고 게이트 실패
        items = [{
            "id": "t2", "text": "기안자 홍길동",
            "must_mask": [{"type": "성명", "value": "홍길동"}], "must_keep": [],
        }]
        rep = run_eval(items, Masker(enable_ner=False))
        self.assertEqual(rep.by_type["성명"].recall, 0.0)
        self.assertEqual(len(rep.by_type["성명"].leaks), 1)
        self.assertFalse(rep.passed)

    def test_detects_overmask(self):
        # 보존돼야 할 값이 사라지면 keep_ratio 하락 + 게이트 실패
        items = [{
            "id": "t3", "text": "행사일 2025-03-02",
            "must_mask": [], "must_keep": ["2025-03-02", "없는값X"],
        }]
        rep = run_eval(items, Masker(enable_ner=False))
        self.assertEqual(rep.keep_total, 2)
        self.assertEqual(rep.keep_ok, 1)           # '없는값X'는 원문에 없음 → over-mask로 집계
        self.assertFalse(rep.passed)

    def test_account_keyword_required(self):
        items = [{
            "id": "t4",
            "text": "환불 계좌 우리은행 1002-345-678901, 회의일 2025-03-02",
            "must_mask": [{"type": "계좌번호", "value": "1002-345-678901"}],
            "must_keep": ["2025-03-02"],
        }]
        rep = run_eval(items, Masker(enable_ner=False))
        self.assertEqual(rep.by_type["계좌번호"].recall, 1.0)  # 키워드 있는 계좌는 마스킹
        self.assertEqual(rep.keep_ratio, 1.0)                # 키워드 없는 날짜는 보존


if __name__ == "__main__":
    unittest.main()
