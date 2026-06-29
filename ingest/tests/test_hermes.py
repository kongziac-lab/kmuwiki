import unittest

from kmu_query.hermes import detect_recurring_work, draft_next_year_document, update_report
from kmu_query.retriever import Source


def recurring_sources():
    return [
        Source("d2025", 0, "2025학년도 2학기 해외 파견 교환학생 후보 선발 시험 실시. 담당 010-1111-2222", 0.9,
               filename="2025년도 2학기 해외 파견 교환학생 후보 선발 시험 실시.pdf",
               doc_no="국제교류팀-100", doc_date="2025-02-27", dept="국제교류팀"),
        Source("d2026", 0, "2026학년도 2학기 해외 파견 교환학생 후보 선발 시험 실시. 담당 010-3333-4444", 0.9,
               filename="2026년도 2학기 해외 파견 교환학생 후보 선발 시험 실시.pdf",
               doc_no="국제교류팀-1843", doc_date="2026-02-27", dept="국제교류팀"),
    ]


class TestHermes(unittest.TestCase):
    def test_detects_recurring_work_by_normalized_title(self):
        patterns = detect_recurring_work(recurring_sources())

        self.assertEqual(len(patterns), 1)
        self.assertEqual(patterns[0]["years"], [2025, 2026])
        self.assertIn("{year}년도", patterns[0]["template_title"])

    def test_generated_document_is_draft_and_uses_placeholders_for_pii(self):
        draft = draft_next_year_document(recurring_sources()[-1], target_year=2027)

        self.assertEqual(draft["status"], "draft")
        self.assertIn("2027학년도", draft["body"])
        self.assertIn("{전화번호}", draft["body"])
        self.assertNotIn("010-3333-4444", draft["body"])

    def test_update_report_lists_changed_documents(self):
        report = update_report("교환학생 선발", recurring_sources(), known_document_ids={"d2025"})

        self.assertEqual(report["new_documents"], ["d2026"])
        self.assertIn("교환학생 선발", report["summary"])


if __name__ == "__main__":
    unittest.main()
