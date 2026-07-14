import unittest
import sys
import types

from kmu_query.rerank import CohereReranker, rerank_sources
from kmu_query.retriever import Source


class FakeReranker:
    def rerank(self, query, sources, *, top_n):
        return list(reversed(sources))[:top_n]


class BrokenReranker:
    def rerank(self, query, sources, *, top_n):
        raise RuntimeError("network down")


class TestRerank(unittest.TestCase):
    def test_reranks_sources(self):
        sources = [
            Source("a", 0, "alpha", 0.1),
            Source("b", 0, "beta", 0.2),
            Source("c", 0, "gamma", 0.3),
        ]

        result = rerank_sources(
            "query", sources, reranker=FakeReranker(), top_n=2,
            max_candidates=3, provider="cohere")

        self.assertTrue(result.applied)
        self.assertEqual([s.document_id for s in result.sources], ["c", "b"])
        self.assertEqual(result.provider, "cohere")

    def test_falls_back_when_rerank_fails(self):
        sources = [
            Source("a", 0, "alpha", 0.1),
            Source("b", 0, "beta", 0.2),
        ]

        result = rerank_sources(
            "query", sources, reranker=BrokenReranker(), top_n=1,
            max_candidates=3, provider="cohere")

        self.assertFalse(result.applied)
        self.assertEqual([s.document_id for s in result.sources], ["a"])
        self.assertIn("RuntimeError", result.error)

    def test_cohere_v4_fast_uses_client_v2_and_visual_surrogate(self):
        captured = {}

        class Client:
            def __init__(self, key, timeout=None):
                captured["init"] = (key, timeout)

            def rerank(self, **kwargs):
                captured["call"] = kwargs
                return types.SimpleNamespace(results=[
                    types.SimpleNamespace(index=0, relevance_score=0.91),
                ])

        original = sys.modules.get("cohere")
        sys.modules["cohere"] = types.SimpleNamespace(ClientV2=Client)
        try:
            reranker = CohereReranker("secret", timeout=7)
            source = Source(
                "doc", 4, "표 합계 120", 0.1,
                filename="예산.pdf", modality="mixed", asset_type="table", page_no=2,
            )
            result = reranker.rerank("합계", [source], top_n=1)
        finally:
            if original is None:
                sys.modules.pop("cohere", None)
            else:
                sys.modules["cohere"] = original

        self.assertEqual(captured["call"]["model"], "rerank-v4.0-fast")
        self.assertIn("modality: mixed", captured["call"]["documents"][0])
        self.assertIn("page: 2", captured["call"]["documents"][0])
        self.assertEqual(result[0].score, 0.91)


if __name__ == "__main__":
    unittest.main()
