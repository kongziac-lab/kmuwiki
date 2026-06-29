import unittest

from kmu_query.insights import (
    build_calendar_drafts,
    build_mermaid_timeline,
    classify_source,
    draft_report,
)
from kmu_query.retriever import Source


def sources():
    return [
        Source("d2", 0, "면접전형은 2026년 3월 23일 동영관에서 실시한다.", 0.9,
               filename="붙임 3. 면접전형 실시 계획(안).xlsx",
               doc_no="국제교류팀-155", doc_date="2026-03-23", dept="국제교류팀"),
        Source("d1", 0, "2026학년도 2학기 해외 파견 교환학생 후보 선발 시험을 실시한다.", 0.8,
               filename="2026년도 2학기 해외 파견 교환학생 후보 선발 시험 실시.pdf",
               doc_no="국제교류팀-1843", doc_date="2026-02-27", dept="국제교류팀"),
    ]


class TestInsights(unittest.TestCase):
    def test_classifies_exchange_interview_documents(self):
        label = classify_source(sources()[0])

        self.assertEqual(label["task_category"], "교환학생 선발")
        self.assertEqual(label["document_type"], "면접")
        self.assertEqual(label["year"], 2026)

    def test_builds_mermaid_timeline_in_document_date_order(self):
        mermaid = build_mermaid_timeline(sources())

        self.assertTrue(mermaid.startswith("timeline"))
        self.assertLess(mermaid.index("국제교류팀-1843"), mermaid.index("국제교류팀-155"))

    def test_builds_calendar_drafts_from_dated_content(self):
        drafts = build_calendar_drafts(sources())

        self.assertEqual(drafts[0]["date"], "2026-03-23")
        self.assertIn("면접전형", drafts[0]["title"])
        self.assertEqual(drafts[0]["status"], "draft")

    def test_draft_report_keeps_citations(self):
        report = draft_report("면접전형 일정", sources())

        self.assertIn("# 면접전형 일정", report)
        self.assertIn("[1]", report)
        self.assertIn("출처", report)


if __name__ == "__main__":
    unittest.main()
