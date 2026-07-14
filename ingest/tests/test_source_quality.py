import unittest

from kmu_query.retriever import Source
from kmu_query.source_quality import classify_query, refine_sources


def source(doc_id, filename, content, score=0.1, dept="국제교류팀"):
    return Source(
        document_id=doc_id,
        chunk_index=0,
        content=content,
        score=score,
        filename=filename,
        dept=dept,
    )


class TestSourceQualityHarness(unittest.TestCase):
    def test_visit_count_intent_filters_travel_budget_and_student_count_noise(self):
        sources = [
            source(
                "busan-consul",
                "주부산중국총영사 내방 업무 진행.pdf",
                "주부산중국총영사 일행이 우리 대학교를 내방하는 바, 내방자 명단 4명",
                0.0196,
            ),
            source(
                "changchun-visit",
                "중국 장춘대학교 대표단 내방 일정 진행.pdf",
                "중국 장춘대학교 대표단이 우리 대학교를 내방. 내방 인원: 7명",
                0.0192,
                dept="장춘대학 계명학원 행정팀",
            ),
            source(
                "travel-plan",
                "장춘대학 계명학원 입학설명회 개최 및 업무 협의 국외 출장 진행.pdf",
                "국외 출장을 진행하고자 합니다. 출장자 및 출장 기간 4명",
                0.0189,
                dept="장춘대학 계명학원 행정팀",
            ),
            source(
                "budget",
                "예산상세산출내역서_1.html",
                "예산요약 계정과목 기타행사비. 원인행위품의제목 중국 장춘대학교 대표단 내방 일정 진행",
                0.0179,
                dept="장춘대학 계명학원 행정팀",
            ),
            source(
                "japan-students",
                "일본 소재 대학교와의 교류 및 유학생 유치 활성화 출장 계획 보고.pdf",
                "학교 재학중인 일본인 학생 수? 국외 출장 계획 보고",
                0.0175,
            ),
        ]

        refined = refine_sources("우리 학교 내방한 인원", sources, limit=8)
        filenames = [s.filename for s in refined]

        self.assertIn("주부산중국총영사 내방 업무 진행.pdf", filenames)
        self.assertIn("중국 장춘대학교 대표단 내방 일정 진행.pdf", filenames)
        self.assertNotIn("장춘대학 계명학원 입학설명회 개최 및 업무 협의 국외 출장 진행.pdf", filenames)
        self.assertNotIn("예산상세산출내역서_1.html", filenames)
        self.assertNotIn("일본 소재 대학교와의 교류 및 유학생 유치 활성화 출장 계획 보고.pdf", filenames)

    def test_visit_sources_for_same_person_are_deduplicated(self):
        sources = [
            source(
                "nankai-invite",
                "초청장(안).hwp",
                "남개대학교 철학대학 탄 밍란 교수님을 본교 방문교수 자격으로 초청합니다. 초청명단 1명",
                0.018,
            ),
            source(
                "nankai-visa",
                "중국 남개대학 교수 방문교수 프로그램 비자 업무 진행.pdf",
                "중국 남개대학 탄 밍란 교수 방문교수 프로그램 비자 업무 진행. 초청 대상 1명",
                0.017,
            ),
        ]

        refined = refine_sources("남개대학교 내방 인원", sources, limit=8)

        self.assertEqual(len(refined), 1)
        self.assertIn("탄 밍란", refined[0].content)

    def test_consul_and_vice_consul_visits_remain_distinct(self):
        sources = [
            source(
                "consul",
                "주부산중국총영사 내방 업무 진행.pdf",
                "주부산중국총영사 일행이 우리 대학교를 내방. 내방자 명단 4명",
                0.018,
            ),
            source(
                "vice-consul",
                "주부산중국부총영사 내방 업무 진행.pdf",
                "주부산중국부총영사 일행이 우리 대학교를 내방. 내방자 명단 4명",
                0.017,
            ),
        ]

        refined = refine_sources("우리 학교 내방 인원", sources, limit=8)

        self.assertEqual({s.document_id for s in refined}, {"consul", "vice-consul"})

    def test_consulate_status_query_filters_exchange_student_noise(self):
        sources = [
            source(
                "exchange",
                "2026학년도 2학기 해외 파견 교환학생 후보 선발 시험 실시.pdf",
                "영어권, 중국어, 일본어 교환학생 후보 선발 시험 실시",
                0.9,
            ),
            source(
                "consul",
                "주부산중국총영사 내방 업무 진행.pdf",
                "주부산중국총영사 일행이 우리 대학교를 내방하는 바 내방자 명단 4명",
                0.2,
            ),
            source(
                "vice-consul",
                "주부산중국부총영사 내방 업무 진행.pdf",
                "주부산중국부총영사 일행이 우리 대학교를 내방하는 바 내방자 명단 4명",
                0.1,
            ),
        ]

        refined = refine_sources("주부산중국총영사관 교류 현황", sources, limit=8)

        self.assertEqual({s.document_id for s in refined}, {"consul", "vice-consul"})

    def test_deduplication_prefers_validation_score_over_raw_score(self):
        sources = [
            source(
                "weak",
                "중국 장춘대학교 대표단 내방 일정 진행.pdf",
                "중국 장춘대학교 대표단 관련 자료",
                0.05,
                dept="장춘대학 계명학원 행정팀",
            ),
            source(
                "strong",
                "중국 장춘대학교 대표단 내방 일정 진행.pdf",
                "중국 장춘대학교 대표단이 우리 대학교를 내방. 내방 인원: 7명. 내방자 명단 포함",
                0.02,
                dept="장춘대학 계명학원 행정팀",
            ),
        ]

        refined = refine_sources("우리 학교 내방 인원", sources, limit=8)

        self.assertEqual(len(refined), 1)
        self.assertEqual(refined[0].document_id, "strong")

    def test_travel_queries_filter_visit_noise(self):
        sources = [
            source("travel", "국외 출장 진행.pdf", "국외 출장자 4명", 0.9),
            source("visit", "대표단 내방.pdf", "대표단 내방 7명", 0.8),
        ]

        refined = refine_sources("출장자는 몇 명인가", sources, limit=8)

        self.assertEqual([s.document_id for s in refined], ["travel"])

    def test_general_queries_are_not_over_filtered(self):
        sources = [
            source("travel", "국외 출장 진행.pdf", "국외 출장자 4명", 0.9),
            source("visit", "대표단 내방.pdf", "대표단 내방 7명", 0.8),
        ]

        refined = refine_sources("국제교류 관련 문서", sources, limit=8)

        self.assertEqual([s.document_id for s in refined], ["travel", "visit"])

    def test_travel_count_intent_filters_visit_and_budget_noise(self):
        sources = [
            source("travel", "국외 출장 진행.pdf", "국외 출장자 및 출장 기간. 출장자 4명", 0.02),
            source("visit", "대표단 내방 일정.pdf", "대표단이 우리 대학교를 내방. 내방 인원 7명", 0.08),
            source("budget", "예산상세산출내역서_1.html", "예산요약 계정과목 출장비 4명", 0.07),
        ]

        refined = refine_sources("출장자는 몇 명인가", sources, limit=8)

        self.assertEqual([s.document_id for s in refined], ["travel"])

    def test_visa_intent_keeps_visa_evidence_and_filters_travel_budget(self):
        sources = [
            source("visa", "중국 남개대학 교수 방문교수 프로그램 비자 업무 진행.pdf", "비자 관련 서류. 초청 대상 탄 밍란 교수 1명", 0.02),
            source("travel", "국외 출장 진행.pdf", "국외 출장자 4명. 출장 계획", 0.08),
            source("budget", "예산상세산출내역서_1.html", "예산요약 계정과목 금액", 0.07),
        ]

        refined = refine_sources("비자 대상자는 누구인가", sources, limit=8)

        self.assertEqual([s.document_id for s in refined], ["visa"])

    def test_budget_intent_keeps_budget_evidence_and_filters_people_lists(self):
        sources = [
            source("budget", "예산상세산출내역서_1.html", "예산요약 계정과목 금액. 소요예산 7,220,000원", 0.02),
            source("visit", "대표단 내방 일정.pdf", "내방자 명단 7명", 0.08),
            source("travel", "국외 출장 진행.pdf", "출장자 명단 4명", 0.07),
        ]

        refined = refine_sources("예산 산출 근거는?", sources, limit=8)

        self.assertEqual([s.document_id for s in refined], ["budget"])

    def test_classifies_visit_count_intent(self):
        intent = classify_query("우리 학교 내방한 인원은?")

        self.assertEqual(intent.kind, "visit_count")
        self.assertIn("출장", intent.exclude_terms)

    def test_classifies_operational_intents(self):
        self.assertEqual(classify_query("출장자는 몇 명인가").kind, "travel")
        self.assertEqual(classify_query("비자 대상자는 누구인가").kind, "visa")
        self.assertEqual(classify_query("예산 산출 근거는?").kind, "budget")


if __name__ == "__main__":
    unittest.main()
