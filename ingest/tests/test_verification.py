import unittest

from kmu_query import rag
from kmu_query.retriever import Source
from kmu_query.verification import (
    build_verification_memo,
    classify_question,
    focus_sources,
    needs_full_zip_context,
)


class TestVerificationMode(unittest.TestCase):
    def test_classifies_date_question(self):
        self.assertEqual(classify_question("공자아카데미 이사회는 언제 개최되었나?"), "date")

    def test_verification_sensitive_questions_use_full_zip_context(self):
        self.assertTrue(needs_full_zip_context("이사회는 언제 개최되었나?"))
        self.assertTrue(needs_full_zip_context("행사 소요 예산은 얼마인가?"))
        self.assertTrue(needs_full_zip_context("참석 인원은 몇 명인가?"))
        self.assertFalse(needs_full_zip_context("공자아카데미 사업을 요약해줘"))

    def test_date_question_does_not_treat_doc_date_as_event_date(self):
        sources = [
            Source(
                "doc1",
                0,
                "제20회 계명공자아카데미 이사회를 다음과 같이 개최하고자 합니다. "
                "가. 개최형식: 서면결의 나. 안건 1) 2025년도 사업실적 보고 및 결산(안) 승인 "
                "끝. 06/23 06/24 06/24 06/26 대결 전결 담당자 팀장 원장 처장",
                0.9,
                filename="제20회 계명공자아카데미 이사회 개최.pdf",
                doc_no="국제교류팀-680",
                doc_date="2026-06-26",
                dept="국제교류팀",
            )
        ]

        memo = build_verification_memo("공자아카데미 이사회는 언제 개최되었나?", sources)

        self.assertEqual(memo.query_type, "date")
        self.assertIn("별도의 개최일시", memo.deterministic_answer or "")
        self.assertIn("문서일자", memo.deterministic_answer or "")
        self.assertIn("단정할 수 없습니다", memo.deterministic_answer or "")

    def test_rag_uses_deterministic_verification_answer_for_uncertain_dates(self):
        sources = [
            Source(
                "doc1",
                0,
                "제20회 계명공자아카데미 이사회를 다음과 같이 개최하고자 합니다. "
                "가. 개최형식: 서면결의 끝. 06/23 06/24 06/24 06/26 전결 담당자 팀장 처장",
                0.9,
                filename="제20회 계명공자아카데미 이사회 개최.pdf",
                doc_no="국제교류팀-680",
                doc_date="2026-06-26",
                dept="국제교류팀",
            )
        ]

        answer = "".join(rag.stream_answer(
            "공자아카데미 이사회는 언제 개최되었나?",
            sources,
            provider="anthropic",
            model="unused",
        ))

        self.assertIn("서면결의", answer)
        self.assertIn("2026-06-26", answer)
        self.assertIn("단정할 수 없습니다", answer)

    def test_date_question_uses_explicit_event_date_when_present(self):
        sources = [
            Source(
                "doc1",
                0,
                "행사 개요 가. 일시: 2026. 7. 15. 14:00 나. 장소: 동영관",
                0.9,
                filename="행사 개최.pdf",
                doc_no="국제교류팀-1",
                doc_date="2026-07-01",
                dept="국제교류팀",
            )
        ]

        memo = build_verification_memo("행사는 언제 개최되나?", sources)

        self.assertIn("## 한눈에 보기", memo.deterministic_answer or "")
        self.assertIn("| 구분 | 근거 문서 | 확인 내용 | 근거 |", memo.deterministic_answer or "")
        self.assertIn("일시: 2026. 7. 15", memo.deterministic_answer or "")
        self.assertNotIn("단정할 수 없습니다", memo.deterministic_answer or "")

    def test_date_question_ignores_event_date_from_different_subject(self):
        sources = [
            Source(
                "doc1",
                0,
                "제20회 계명공자아카데미 이사회를 다음과 같이 개최하고자 합니다. "
                "가. 개최형식: 서면결의",
                0.9,
                filename="제20회 계명공자아카데미 이사회 개최.pdf",
                doc_no="국제교류팀-680",
                doc_date="2026-06-26",
                dept="국제교류팀",
            ),
            Source(
                "doc2",
                0,
                "행사 개요 - 행사명: 2026년 춘계학술대회 - 일시: 2026년 5월 30일(토) "
                "- 주관: 계명대학교 공자아카데미",
                0.8,
                filename="공자아카데미 예산서.pdf",
                doc_no="국제교류팀-981",
                doc_date="2025-09-03",
                dept="국제교류팀",
            ),
        ]

        memo = build_verification_memo("공자아카데미 이사회는 언제 개최되었나?", sources)

        self.assertIn("단정할 수 없습니다", memo.deterministic_answer or "")
        self.assertNotIn("2026년 5월 30일", memo.deterministic_answer or "")

    def test_focus_sources_prefers_question_subject_before_zip_expansion(self):
        sources = [
            Source("a", 0, "공자아카데미 춘계학술대회 일시: 2026년 5월 30일", 0.9,
                   filename="공자아카데미 예산서.pdf"),
            Source("b", 0, "제20회 계명공자아카데미 이사회 개최. 개최형식: 서면결의", 0.8,
                   filename="제20회 계명공자아카데미 이사회 개최.pdf"),
        ]

        focused = focus_sources("공자아카데미 이사회는 언제 개최되었나?", sources)

        self.assertEqual([s.document_id for s in focused], ["b"])

    def test_focus_sources_expands_consulate_to_consul_and_vice_consul(self):
        sources = [
            Source("changchun", 0, "중국 장춘대학교 대표단 내방 일정", 0.9,
                   filename="중국 장춘대학교 대표단 내방 일정 진행.pdf"),
            Source("consul", 0, "주부산중국총영사 일행 내방일시: 2026. 5. 30.", 0.8,
                   filename="주부산중국총영사 내방 업무 진행.pdf"),
            Source("vice", 0, "주부산중국부총영사 내방일시: 2026. 3. 24.", 0.7,
                   filename="일정계획(안).hwp"),
        ]

        focused = focus_sources("주부산중국총영사관 관련 일정은 어떻게 되나", sources)

        self.assertEqual([s.document_id for s in focused], ["consul", "vice"])

    def test_schedule_question_reports_multiple_focused_dates(self):
        sources = [
            Source("consul", 0, "주부산중국총영사 내방일시: 2026. 5. 30.(토) 11:30~14:00", 0.8,
                   filename="주부산중국총영사 내방 업무 진행.pdf"),
            Source("vice", 0, "주부산중국부총영사 내방일시: 2026. 3. 24.(화) 10:30~13:20", 0.7,
                   filename="주부산중국부총영사 내방 업무 진행.pdf"),
        ]

        memo = build_verification_memo("주부산중국총영사관 관련 일정은 어떻게 되나", sources)

        self.assertEqual(memo.query_type, "date")
        self.assertIn("## 확인된 내용", memo.deterministic_answer or "")
        self.assertIn("| 구분 | 근거 문서 | 확인 내용 | 근거 |", memo.deterministic_answer or "")
        self.assertIn("2026. 5. 30", memo.deterministic_answer or "")
        self.assertIn("2026. 3. 24", memo.deterministic_answer or "")


if __name__ == "__main__":
    unittest.main()
