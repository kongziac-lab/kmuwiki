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

    def test_exchange_student_schedule_cleans_table_rows(self):
        sources = [
            Source(
                "exam1",
                0,
                "2026년도 2학기 해외 파견 교환학생 후보 선발 시험 실시. "
                "형 가. 일시 1) 1차(영어권 TOEFL/IELTS, 영어권 기초전형 A그룹, "
                "영어권 일반전형 TOEIC, 일본어, 스페인어, 러시아어, 독일어): "
                "2026. 3. 23.(월) 09:00~ 2) 2차(영어권 면접): 2026. 3. 24.(화) 10:00~",
                0.9,
                filename="2026년도 2학기 해외 파견 교환학생 후보 선발 시험 실시.pdf",
                doc_no="국제교류팀-124",
                dept="국제교류팀",
            ),
            Source(
                "exam2",
                0,
                "영관 강의실 3) 언어권별 면접전형 계획: 붙임 3. 면접전형 실시 계획(안) 참고 "
                "다. 최종 선발자 대상 수학 희망 대학 및 수학 기간 선정 계획 "
                "1) 일자: 2026. 3. 26.(목) 2) 장소: 동영관 강의실",
                0.8,
                filename="2026년도 2학기 해외 파견 교환학생 후보 선발 시험 실시.pdf",
                doc_no="국제교류팀-124",
                dept="국제교류팀",
            ),
            Source(
                "period",
                0,
                "2026-2027학년도 해외 파견 교환학생 후보 선발 시험 실시. "
                "기간: 2026학년도 2학기(한학기 또는 1년) 3) 선발 일정(세부사항은 붙임)",
                0.7,
                filename="2026-2027학년도 해외 파견 교환학생 후보 선발 시험 실시.pdf",
                dept="국제교류팀",
            ),
        ]

        memo = build_verification_memo("교환학생 면접 일정에 대해 알려줘", sources)
        answer = memo.deterministic_answer or ""

        self.assertIn("2차(영어권 면접): 2026. 3. 24", answer)
        self.assertNotIn("1차(영어권 TOEFL/IELTS", answer)
        self.assertNotIn("일자: 2026. 3. 26", answer)
        self.assertNotIn("형 가. 일시", answer)
        self.assertNotIn("2026-2027학년도", answer)
        self.assertNotIn("기간: 2026학년도 2학기", answer)

    def test_chinese_exchange_interview_schedule_requires_language_and_interview(self):
        sources = [
            Source(
                "doc-history-1",
                0,
                "국제교류팀-1784(2026. 2. 23.) 2026-2027학년도 해외 파견 교환학생 후보 선발 시험 실시",
                0.9,
                filename="2026학년도 2학기 해외 파견 교환학생 후보 선발 시험 추가 모집 실시.pdf",
                dept="국제교류팀",
            ),
            Source(
                "doc-history-2",
                0,
                "국제교류팀-1843(2026. 2. 27.) 2026년도 2학기 해외 파견 교환학생 후보 선발 시험 실시",
                0.8,
                filename="2026학년도 2학기 해외 파견 교환학생 후보 선발 시험 추가 모집 실시.pdf",
                dept="국제교류팀",
            ),
            Source(
                "chinese",
                0,
                "중국어 및 언어권 가) 서류 접수- 2026. 3. 20.(금) 15:00까지 "
                "나) 면접 전형: 2026. 3. 23.(월) "
                "다) 수학 희망 대학 선정: 2026. 3. 26.(목)",
                0.7,
                filename="2026학년도 2학기 해외 파견 교환학생 후보 선발 시험 추가 모집 실시.pdf",
                dept="국제교류팀",
            ),
            Source(
                "approval",
                0,
                "03/16 03/16 03/16 담당자 이현지 팀장 조현욱 부처장 김종근 처장 민경모",
                0.6,
                filename="2026학년도 2학기 해외 파견 교환학생 후보 선발 시험 추가 모집 실시.pdf",
                dept="국제교류팀",
            ),
        ]

        memo = build_verification_memo("중국어 교환학생 면접 일정에 대해 알려줘", sources)
        answer = memo.deterministic_answer or ""

        self.assertIn("면접 전형: 2026. 3. 23", answer)
        self.assertNotIn("국제교류팀-1784", answer)
        self.assertNotIn("국제교류팀-1843", answer)
        self.assertNotIn("서류 접수", answer)
        self.assertNotIn("수학 희망 대학 선정", answer)
        self.assertNotIn("03/16", answer)

    # 실제 전자결재 원문 구조: 언어권별 블록이 괄호 마커 (1)(2)(3) 항목을 가진다.
    SELECTION_BODY = (
        "3. 시행 내용 가. 선발 일정 "
        "가) 중국어 외 언어권 (1) 서류 전형: 2026. 3. 10.(화) 까지 "
        "(2) 면접 전형: 2026. 3. 16.(월) (3) 수학 희망 대학 선정: 2026. 3. 20.(금) "
        "나) 중국어권 (1) 서류 전형: 2026. 3. 10.(화) 까지 (2) 필기 시험: 2026. 3. 12.(목) "
        "(3) 면접 전형: 2026. 3. 18.(수) (4) 수학 희망 대학 선정: 2026. 3. 24.(화)"
    )

    def _selection_sources(self):
        return [Source(
            "exam", 0, self.SELECTION_BODY, 0.9,
            filename="2026년도 2학기 해외 파견 교환학생 후보 선발 시험 실시.pdf",
            dept="국제교류팀",
        )]

    def test_chinese_track_interview_excludes_non_chinese_track(self):
        memo = build_verification_memo(
            "중국어권 파견교환학생 면접 일정에 대해 알려줘", self._selection_sources())
        answer = memo.deterministic_answer or ""

        # 중국어권 면접(3.18)이 언어권 라벨과 함께 잡히고,
        self.assertIn("2026. 3. 18", answer)
        self.assertIn("중국어권 · 면접 전형", answer)
        # 정반대인 "중국어 외 언어권" 면접(3.16)은 배제된다.
        self.assertNotIn("2026. 3. 16", answer)

    def test_non_chinese_track_question_flips_the_filter(self):
        memo = build_verification_memo(
            "중국어 외 언어권 면접 일정 알려줘", self._selection_sources())
        answer = memo.deterministic_answer or ""

        self.assertIn("2026. 3. 16", answer)
        self.assertNotIn("2026. 3. 18", answer)

    def test_general_interview_question_lists_both_tracks_without_table_dumps(self):
        dump = (
            "일자 언어권 배정 구분 시작 시간 고사실 인원(명) 비고 "
            "1 한천우 교육학과 ㅇㅇ 9/12(금) 오전 특수언어권(러시아어, 스페인어), "
            "영어권(TOEFL) - 일반면접 일반면접 09:00"
        )
        letter = "[International Affairs Team] Request for Participation as Interviewer 9/17"
        sources = self._selection_sources() + [
            Source("assign", 0, dump, 0.8,
                   filename="붙임 3. 면접전형 실시 계획(안).pdf", dept="국제교류팀"),
            Source("letter", 0, letter, 0.7,
                   filename="붙임 4. 면접위원 참여 요청.pdf", dept="국제교류팀"),
        ]

        memo = build_verification_memo("파견교환학생 면접 진행 일정에 대해 알려줘", sources)
        answer = memo.deterministic_answer or ""

        # 언어권 미지정 질문: 두 언어권의 면접 일정이 모두 나온다.
        self.assertIn("중국어권 · 면접 전형: 2026. 3. 18", answer)
        self.assertIn("중국어 외 언어권 · 면접 전형: 2026. 3. 16", answer)
        # 붙임 배정표(개인별 행)와 영문 서신 조각은 일정 표에 오르지 않는다.
        self.assertNotIn("한천우", answer)
        self.assertNotIn("고사실", answer)
        self.assertNotIn("International Affairs", answer)

    def test_date_terms_cover_common_korean_phrasings(self):
        self.assertEqual(classify_question("중국어권 면접 며칠이야"), "date")
        self.assertEqual(classify_question("면접이 몇일인지 알려줘"), "date")

    def test_pattern_questions_share_noise_filters_by_type(self):
        approval_money = Source(
            "appr", 0,
            "03/16 03/16 03/16 전결 담당자 이현지 팀장 조현욱 소요 예산 300,000원",
            0.9, filename="결재.pdf", dept="국제교류팀",
        )
        head_count_table = Source(
            "table", 0,
            "면접 배정 고사실 인원(명) 비고 15명 시작 시간 09:00",
            0.8, filename="붙임 배정표.pdf", dept="국제교류팀",
        )

        # 금액 질문: 결재라인 창은 근거에서 제외된다.
        money = build_verification_memo("면접 소요 예산 금액 알려줘", [approval_money])
        self.assertFalse(any("전결" in line for line in money.confirmed))

        # 인원 질문: 표가 곧 근거이므로 표 조각을 걸러내지 않는다.
        count = build_verification_memo("면접 인원 몇 명이야", [head_count_table])
        self.assertTrue(any("15명" in line for line in count.confirmed))

    def test_contact_boilerplate_and_month_only_dates_are_not_schedules(self):
        sources = [
            Source(
                "boiler", 0,
                "면접 전형 문의 사항: 국제교류팀 이현지(053-580-6023 / [이메일]) "
                "부분공개 2026. 3. 국 제 처 장 대기실 국327",
                0.9,
                filename="2026년도 2학기 해외 파견 교환학생 후보 선발 시험 실시.pdf",
                dept="국제교류팀",
            ),
        ]

        memo = build_verification_memo("교환학생 면접 일정 알려줘", sources)
        answer = memo.deterministic_answer or ""

        # 연락처·연월-only 조각은 일정 표에 오르지 않는다 → 행사일시 미확인 답변.
        self.assertNotIn("053-580-6023", answer)
        self.assertIn("행사일시는 확인되지 않습니다", answer)


if __name__ == "__main__":
    unittest.main()
