import unittest

from kmu_query.insights import (
    build_report_workflow,
    build_calendar_drafts,
    build_mermaid_timeline,
    classify_source,
    draft_report,
    group_work_items,
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


def duplicate_business_sources():
    return [
        Source("d1-pdf", 0, "2026학년도 2학기 해외 파견 교환학생 후보 선발 시험을 실시한다.", 0.92,
               filename="2026년도 2학기 해외 파견 교환학생 후보 선발 시험 실시.pdf",
               doc_no="국제교류팀-1843", doc_date="2026-02-27", dept="국제교류팀"),
        Source("d1-mht", 0, "2026학년도 2학기 해외 파견 교환학생 후보 선발 시험을 실시한다.", 0.91,
               filename="2026년도 2학기 해외 파견 교환학생 후보 선발 시험 실시.mht",
               doc_no="국제교류팀-1843", doc_date="2026-02-27", dept="국제교류팀"),
        Source("d2", 0, "2026학년도 2학기 해외 파견 교환학생 후보 선발 시험 추가 모집을 실시한다.", 0.88,
               filename="2026학년도 2학기 해외 파견 교환학생 후보 선발 시험 추가 모집 실시.pdf",
               doc_no="국제교류팀-124", doc_date="2026-03-18", dept="국제교류팀"),
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

    def test_groups_same_business_instead_of_each_document(self):
        groups = group_work_items(duplicate_business_sources())

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["work_title"], "2026학년도 2학기 해외 파견 교환학생 후보 선발")
        self.assertEqual(groups[0]["task_category"], "교환학생 선발")
        self.assertEqual(groups[0]["document_count"], 3)
        self.assertEqual(set(groups[0]["document_types"]), {"시험"})

    def test_mermaid_timeline_collapses_duplicate_renderings(self):
        mermaid = build_mermaid_timeline(duplicate_business_sources())

        self.assertEqual(mermaid.count("국제교류팀-1843"), 1)
        self.assertIn("2개 문서", mermaid)

    def test_builds_calendar_drafts_from_dated_content(self):
        drafts = build_calendar_drafts(sources())

        interview = next(draft for draft in drafts if draft["date"] == "2026-03-23")
        self.assertIn("면접전형", interview["title"])
        self.assertEqual(interview["status"], "draft")

    def test_calendar_drafts_deduplicate_same_date_and_event(self):
        drafts = build_calendar_drafts(duplicate_business_sources()[:2])

        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["date"], "2026-02-27")
        self.assertEqual(drafts[0]["source_document_ids"], ["d1-pdf", "d1-mht"])

    def test_uses_doc_date_when_content_has_no_explicit_date(self):
        source = Source("d3", 0, "면접전형 실시 계획", 0.9,
                        filename="면접전형 실시 계획.xlsx",
                        doc_no="국제교류팀-155", doc_date="2026-03-23", dept="국제교류팀")

        drafts = build_calendar_drafts([source])

        self.assertEqual(drafts[0]["date"], "2026-03-23")

    def test_draft_report_keeps_citations(self):
        report = draft_report("면접전형 일정", sources())

        self.assertIn("# 면접전형 일정", report)
        self.assertIn("[1]", report)
        self.assertIn("출처", report)

    def test_report_workflow_uses_markdown_as_source_for_report_templates(self):
        workflow = build_report_workflow("파견교환학생", "# 파견교환학생\n\n## 요약")

        self.assertEqual(workflow["source_format"], "markdown")
        self.assertIn("기안보고", [template["name"] for template in workflow["templates"]])
        self.assertIn("양식 선택", workflow["steps"][1])


if __name__ == "__main__":
    unittest.main()
