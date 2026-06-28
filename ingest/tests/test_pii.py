import unittest

from kmu_ingest.pii.egress_gate import EgressBlocked, assert_clean, scan
from kmu_ingest.pii.masker import Masker
from kmu_ingest.pii.policy import MaskPolicy


class TestDefaultPolicy(unittest.TestCase):
    """내부결재문 기본 정책: 주민/카드/이메일/계좌는 마스킹, 성명·전화·주소는 보존."""

    def setUp(self):
        self.m = Masker(enable_ner=False)  # 기본 정책

    def test_masks_sensitive_keeps_phone(self):
        text = "홍길동 900101-1234567 010-1234-5678 hong@kmu.ac.kr 1234-5678-9012-3456"
        r = self.m.mask(text)
        self.assertIn("[주민등록번호]", r.text)
        self.assertIn("[이메일]", r.text)
        self.assertIn("[카드번호]", r.text)
        # 보존: 이름·전화번호
        self.assertIn("홍길동", r.text)
        self.assertIn("010-1234-5678", r.text)


class TestAllPolicy(unittest.TestCase):
    """전체 정책(예: 민원 문서): 전화번호도 마스킹."""

    def setUp(self):
        self.m = Masker(enable_ner=False, policy=MaskPolicy.all())

    def test_masks_phone(self):
        r = self.m.mask("문의 02-940-1234 / 010-1234-5678")
        self.assertEqual(r.text.count("[전화번호]"), 2)


class TestEgressGate(unittest.TestCase):
    def test_clean_text_passes(self):
        assert_clean("이 문서에는 [주민등록번호] 만 남아있다.")

    def test_residual_rrn_blocks(self):
        with self.assertRaises(EgressBlocked):
            assert_clean("실수로 남은 주민번호 900101-1234567")

    def test_enforce_labels_excludes_phone(self):
        # 정책상 전화번호를 안 가리면, 전화번호가 남아도 게이트는 통과해야 함
        labels = MaskPolicy.internal().enforced_high()
        assert_clean("연락처 010-1234-5678 입니다", enforce_labels=labels)

    def test_scan_reports_redacted_sample(self):
        findings = scan("hong@kmu.ac.kr")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].label, "이메일")
        self.assertNotIn("@kmu.ac.kr", findings[0].sample)


if __name__ == "__main__":
    unittest.main()
