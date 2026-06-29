import unittest

from kmu_ingest.cleaning import strip_boilerplate


class TestCleaning(unittest.TestCase):
    def test_strips_inline_mht_header_boilerplate(self):
        text = (
            '"진리와 정의와 사랑의 나라를 위하여" 국제처 수신자 내부결재 (경 유) '
            '제  목 2026년도 2학기 해외 파견 교환학생 후보 선발 시험 실시 '
            '1. 관련: 국제교류팀-1784(2026. 2. 23.) '
            '협조자                               시행 국제교류팀-1843 ( 2026.02.27. ) 접수 ( ) '
            '전화 053-580-6023 전송 [이메일] 부분공개(6)'
        )

        cleaned = strip_boilerplate(text)

        self.assertIn('2026년도 2학기 해외 파견 교환학생 후보 선발 시험 실시', cleaned)
        self.assertIn('1. 관련: 국제교류팀-1784', cleaned)
        self.assertNotIn('진리와 정의와 사랑', cleaned)
        self.assertNotIn('수신자 내부결재', cleaned)
        self.assertNotIn('시행 국제교류팀-1843', cleaned)


if __name__ == "__main__":
    unittest.main()
