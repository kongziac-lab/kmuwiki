import unittest

from kmu_query import rag
from kmu_query.retriever import Retriever, Source


# ── 가짜 Supabase 클라이언트/응답 ────────────────────────────────
class FakeResp:
    def __init__(self, data):
        self.data = data


class FakeRPC:
    def __init__(self, store, name, params):
        store["name"] = name
        store["params"] = params
        self._store = store

    def execute(self):
        return FakeResp(self._store["rows"])


class FakeClient:
    def __init__(self, rows):
        self.captured = {"rows": rows}

    def rpc(self, name, params):
        return FakeRPC(self.captured, name, params)


class FakeEmbedder:
    model = "fake"
    version = "v1"

    def embed(self, texts):
        return [[0.1] * 1024 for _ in texts]


def sample_sources():
    return [
        Source("d1", 0, "연간 행사는 3월에 시작한다.", 0.9,
               filename="기안.txt", doc_no="제2025-13호", doc_date="2025-03-02", dept="기획처"),
        Source("d2", 1, "예산은 총무처가 집행한다.", 0.5, dept="총무처"),
    ]


class TestRetriever(unittest.TestCase):
    def test_passes_dept_and_embedding(self):
        client = FakeClient(rows=[{
            "document_id": "d1", "chunk_index": 0, "content": "내용", "score": 0.9,
            "filename": "f.txt", "doc_no": "제2025-1호", "doc_date": "2025-01-01", "dept": "기획처",
        }])
        r = Retriever(client, FakeEmbedder())
        out = r.retrieve("행사 일정", k=5, dept="기획처")
        self.assertEqual(client.captured["name"], "hybrid_search")
        self.assertEqual(client.captured["params"]["filter_dept"], "기획처")
        self.assertEqual(client.captured["params"]["match_count"], 5)
        self.assertEqual(len(client.captured["params"]["query_embedding"]), 1024)
        self.assertEqual(out[0].doc_no, "제2025-1호")

    def test_empty_query_short_circuits(self):
        r = Retriever(FakeClient(rows=[]), FakeEmbedder())
        self.assertEqual(r.retrieve("   "), [])


class TestRagAssembly(unittest.TestCase):
    def test_build_context_numbered_with_labels(self):
        ctx = rag.build_context(sample_sources())
        self.assertIn("[1] (기획처 · 제2025-13호 · 2025-03-02 · 기안.txt)", ctx)
        self.assertIn("[2] (총무처)", ctx)
        self.assertIn("연간 행사는 3월", ctx)

    def test_citations_numbering(self):
        cites = rag.citations(sample_sources())
        self.assertEqual([c["n"] for c in cites], [1, 2])
        self.assertEqual(cites[0]["doc_no"], "제2025-13호")


class TestRagAnswer(unittest.TestCase):
    def test_no_sources_refuses_without_llm(self):
        # 출처가 없으면 LLM(client) 없이도 거절 메시지를 반환해야 함
        out = rag.answer("아무거나", [], client=None)
        self.assertEqual(out["answer"], rag.REFUSAL)
        self.assertEqual(out["citations"], [])

    def test_answer_uses_injected_client(self):
        captured = {}

        class Block:
            type = "text"
            text = "행사는 3월에 시작합니다 [1]."

        class Msg:
            content = [Block()]

        class FakeMessages:
            def create(self, **kw):
                captured.update(kw)
                return Msg()

        class FakeLLM:
            messages = FakeMessages()

        out = rag.answer("행사 언제?", sample_sources(), client=FakeLLM())
        self.assertIn("[1]", out["answer"])
        self.assertEqual(len(out["citations"]), 2)
        # 시스템 프롬프트와 컨텍스트가 전달됐는지
        self.assertIn("자료", captured["messages"][0]["content"])
        self.assertEqual(captured["system"], rag.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
