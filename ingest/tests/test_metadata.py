import unittest
from datetime import date

from kmu_ingest.metadata import build_file_meta, extract_doc_fields

# 합성 기안문(실제 PII 없음) — 실제 구조를 모사
DOC_WITH_DEPT = """제 목 해외 파견 교환학생 지원 기준 변경 시행(안) 보고
본문 내용 ...
협조자 정철우 03/17 경영부총장 윤우석 03/17
시행 국제교류팀-123 ( 2026.03.18. ) 접수 ( )
"""

DOC_NO_DEPT = """제 목 장춘대학 계명학원 입학설명회 개최 및 업무 협의 국외 출장 진행
1. 관련: 행정팀-99(2023. 7. 18.) 다른 문서 참조
시행 ( 2026.02.26. ) 접수 ( )
"""


class TestMetadata(unittest.TestCase):
    def test_full_fields_from_sihaeng_line(self):
        f = extract_doc_fields(DOC_WITH_DEPT)
        self.assertEqual(f["dept"], "국제교류팀")
        self.assertEqual(f["doc_no"], "국제교류팀-123")
        self.assertEqual(f["doc_date"], date(2026, 3, 18))
        self.assertIn("교환학생", f["title"])

    def test_deny_by_default_when_no_sihaeng_dept(self):
        # 시행 부서-번호가 없으면 dept/doc_no는 None (본문 참조 부서로 추측하지 않음)
        f = extract_doc_fields(DOC_NO_DEPT)
        self.assertIsNone(f["dept"])
        self.assertIsNone(f["doc_no"])
        self.assertEqual(f["doc_date"], date(2026, 2, 26))  # 시행일은 추출

    def test_empty(self):
        f = extract_doc_fields("")
        self.assertEqual(f, {"title": None, "dept": None, "doc_no": None, "doc_date": None})

    def test_build_file_meta_inherits_zip_fields(self):
        zf = {"dept": "국제교류팀", "doc_no": "국제교류팀-123",
              "doc_date": date(2026, 3, 18), "title": "제목"}
        meta = build_file_meta("붙임.hwp", "폴더/붙임.hwp", "application/hwp", zf)
        self.assertEqual(meta.dept, "국제교류팀")
        self.assertEqual(meta.doc_no, "국제교류팀-123")
        self.assertIsNone(meta.security_level)  # 항상 deny-by-default


if __name__ == "__main__":
    unittest.main()
