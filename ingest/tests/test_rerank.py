import unittest

from kmu_query.rerank import rerank_sources
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


if __name__ == "__main__":
    unittest.main()
