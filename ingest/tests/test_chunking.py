import unittest

from kmu_ingest.chunking import chunk_prefix, chunk_text


class TestChunking(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(chunk_text(""), [])

    def test_single_short(self):
        chunks = chunk_text("짧은 문서입니다.", target_chars=1200)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chunk_index, 0)

    def test_splits_long_text_with_prefix(self):
        para = "가" * 500
        text = "\n\n".join([para] * 6)  # ~3000자
        chunks = chunk_text(text, target_chars=1000, overlap_chars=100,
                            prefix="[기획처 제2025-13호]")
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c.content.startswith("[기획처 제2025-13호]") for c in chunks))
        # 인덱스 연속성
        self.assertEqual([c.chunk_index for c in chunks], list(range(len(chunks))))

    def test_prefix_includes_metadata_and_section_type(self):
        prefix = chunk_prefix(
            title="공자아카데미 운영 결과 보고",
            dept="국제교류팀",
            doc_no="국제교류팀-680",
            doc_date="2026-06-26",
            document_kind="result_report",
            attachment_names=["붙임 1. 이사회 자료.hwp"],
        )
        chunks = chunk_text("붙임 1. 이사회 자료\n\n1. 추진 결과", target_chars=80, prefix=prefix)

        self.assertIn("제목: 공자아카데미 운영 결과 보고", chunks[0].content)
        self.assertIn("문서번호: 국제교류팀-680", chunks[0].content)
        self.assertIn("붙임:", chunks[0].content)
        self.assertEqual(chunks[0].section_type, "attachment")


if __name__ == "__main__":
    unittest.main()
