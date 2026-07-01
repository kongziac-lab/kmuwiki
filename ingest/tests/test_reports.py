import unittest

from kmu_query.reports import build_wiki_report
from kmu_query.retriever import Source


def report_sources():
    return [
        Source("d1", 0, "2026학년도 공자아카데미 중국어 강좌를 운영하였다.", 0.9,
               filename="2026 공자아카데미 운영 결과.pdf",
               doc_no="국제교류팀-101", doc_date="2026-06-30", dept="국제교류팀"),
        Source("d2", 0, "문화 체험 행사는 2026년 5월 20일 실시하였다.", 0.85,
               filename="문화 체험 행사 결과.hwp",
               doc_no="국제교류팀-122", doc_date="2026-05-20", dept="국제교류팀"),
    ]


class TestReports(unittest.TestCase):
    def test_builds_public_document_style_report(self):
        report = build_wiki_report(
            "공자아카데미 운영",
            report_sources(),
            report_type="result",
            target_year=2026,
            recipient="총장",
            sender="계명대학교 국제처",
            dept="국제교류팀",
        )

        self.assertEqual(report["engine"], "wiki-report-writer")
        self.assertIn("korean-gov-doc", report["skill_chain"])
        self.assertIn("hwpx-autofill-conversion", report["skill_chain"])
        self.assertEqual(report["report_label"], "결과 보고")
        self.assertIn("수 신:  총장", report["body"])
        self.assertIn("제 목:  2026년 공자아카데미 운영 결과 보고", report["body"])
        self.assertIn("붙임  1. Wiki DB 근거 문서 목록 1부.  끝.", report["body"])
        self.assertEqual(report["source_count"], 2)
        self.assertEqual(len(report["sources"]), 2)

    def test_uses_placeholders_when_no_sources_exist(self):
        report = build_wiki_report("없는 업무", [], recipient="", sender="")

        self.assertIn("[수신처]", report["body"])
        self.assertIn("[발신기관명]", report["body"])
        self.assertIn("검색된 근거 문서 없음", report["body"])


if __name__ == "__main__":
    unittest.main()
