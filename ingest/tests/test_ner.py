import unittest

from kmu_ingest.pii.masker import Masker
from kmu_ingest.pii.ner import Entity, KoreanNER, _normalize_label
from kmu_ingest.pii.policy import MaskPolicy


def fake_extractor(text: str) -> list[Entity]:
    """주입 추출기: '홍길동'(PER), '서울시 강남구'(LOC), '계명대학교'(ORG) 를 찾는다."""
    ents = []
    for needle, label in [("홍길동", "PER"), ("서울시 강남구", "LOC"), ("계명대학교", "ORG")]:
        i = text.find(needle)
        if i >= 0:
            ents.append(Entity(label, i, i + len(needle)))
    return ents


class TestLabelNormalize(unittest.TestCase):
    def test_variants(self):
        self.assertEqual(_normalize_label("PS"), "PER")
        self.assertEqual(_normalize_label("LC"), "LOC")
        self.assertEqual(_normalize_label("OG"), "ORG")
        self.assertEqual(_normalize_label("PERSON"), "PER")
        self.assertIsNone(_normalize_label("DT"))


class TestKoreanNER(unittest.TestCase):
    def test_masks_person_and_location_not_org_by_default(self):
        ner = KoreanNER(extractor=fake_extractor)
        self.assertTrue(ner.ensure())
        out, counts = ner.mask("홍길동 서울시 강남구 계명대학교")
        self.assertIn("[성명]", out)
        self.assertIn("[주소]", out)
        self.assertIn("계명대학교", out)        # ORG 기본 유지
        self.assertNotIn("홍길동", out)
        self.assertEqual(counts.get("성명"), 1)

    def test_mask_org_opt_in(self):
        ner = KoreanNER(extractor=fake_extractor, mask_org=True)
        out, _ = ner.mask("계명대학교 행사")
        self.assertIn("[기관]", out)
        self.assertNotIn("계명대학교", out)

    def test_span_replacement_keeps_indices(self):
        # 두 엔티티가 같이 있어도 뒤에서부터 치환되어 깨지지 않음
        ner = KoreanNER(extractor=fake_extractor)
        out, _ = ner.mask("담당 홍길동, 거주지 서울시 강남구 입니다")
        self.assertEqual(out, "담당 [성명], 거주지 [주소] 입니다")


class TestMaskerIntegration(unittest.TestCase):
    def test_regex_and_ner_combined(self):
        # 전체 정책에서: 주입된 NER 로 이름/주소 + 정규식으로 주민번호/전화
        ner = KoreanNER(extractor=fake_extractor)
        m = Masker(enable_ner=True, ner=ner, policy=MaskPolicy.all())
        r = m.mask("홍길동 900101-1234567 서울시 강남구 010-1234-5678")
        self.assertTrue(r.ner_available)
        for token in ["[성명]", "[주민등록번호]", "[주소]", "[전화번호]"]:
            self.assertIn(token, r.text)
        self.assertNotIn("홍길동", r.text)
        self.assertNotIn("900101-1234567", r.text)

    def test_ner_unavailable_is_reported(self):
        # ensure 실패를 흉내내는 추출기 없는 비활성 케이스
        m = Masker(enable_ner=False)
        r = m.mask("홍길동 입니다")
        self.assertFalse(r.ner_available)
        self.assertIn("홍길동", r.text)   # NER 없으면 이름은 남음(정규식 범위 밖)


if __name__ == "__main__":
    unittest.main()
