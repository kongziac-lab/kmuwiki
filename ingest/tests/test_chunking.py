import unittest

from kmu_ingest.chunking import chunk_text


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


if __name__ == "__main__":
    unittest.main()
