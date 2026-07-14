import unittest
from types import SimpleNamespace

from kmu_query import rag
from kmu_query.retriever import Retriever, Source


def load_service_module():
    try:
        from kmu_query import service
    except ModuleNotFoundError as exc:
        if exc.name == "fastapi":
            raise unittest.SkipTest("fastapi is not installed in this Python environment")
        raise
    return service


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


class FakeMultiRPC:
    def __init__(self, client, name, params):
        self.client = client
        self.name = name
        self.params = params

    def execute(self):
        self.client.calls.append((self.name, self.params))
        return FakeResp(self.client.rows_by_query.get(self.params["query_text"], []))


class FakeMultiClient:
    def __init__(self, rows_by_query, documents=None):
        self.rows_by_query = rows_by_query
        self.documents = documents or []
        self.calls = []

    def rpc(self, name, params):
        return FakeMultiRPC(self, name, params)

    def table(self, name):
        if name != "documents":
            raise AssertionError(name)
        return FakeMetadataQuery(self.documents)


class FakeMetadataQuery:
    def __init__(self, rows):
        self.rows = rows
        self.eq_filters = []
        self.ilike_filter = None
        self.gte_filter = None
        self.lt_filter = None
        self.limit_count = None

    def select(self, _fields):
        return self

    def eq(self, field, value):
        self.eq_filters.append((field, value))
        return self

    def ilike(self, field, pattern):
        self.ilike_filter = (field, pattern.strip("%"))
        return self

    def gte(self, field, value):
        self.gte_filter = (field, value)
        return self

    def lt(self, field, value):
        self.lt_filter = (field, value)
        return self

    def limit(self, count):
        self.limit_count = count
        return self

    def execute(self):
        rows = list(self.rows)
        for field, value in self.eq_filters:
            rows = [row for row in rows if row.get(field) == value]
        if self.ilike_filter:
            field, term = self.ilike_filter
            rows = [row for row in rows if term.lower() in str(row.get(field) or "").lower()]
        if self.gte_filter:
            field, value = self.gte_filter
            rows = [row for row in rows if str(row.get(field) or "") >= value]
        if self.lt_filter:
            field, value = self.lt_filter
            rows = [row for row in rows if str(row.get(field) or "") < value]
        if self.limit_count is not None:
            rows = rows[:self.limit_count]
        return FakeResp(rows)


class FakeTableQuery:
    def __init__(self, rows):
        self.rows = rows
        self.ids = None
        self.zip_ids = None

    def select(self, _fields):
        return self

    def in_(self, field, values):
        if field == "id":
            self.ids = {str(value) for value in values}
        if field == "zip_id":
            self.zip_ids = {str(value) for value in values}
        return self

    def eq(self, _field, _value):
        return self

    def execute(self):
        rows = self.rows
        if self.ids is not None:
            rows = [row for row in rows if str(row.get("id")) in self.ids]
        if self.zip_ids is not None:
            rows = [row for row in rows if str(row.get("zip_id")) in self.zip_ids]
        return FakeResp(rows)


class FakeCitationClient(FakeClient):
    def __init__(self, rows, documents):
        super().__init__(rows)
        self.documents = documents

    def table(self, name):
        self.captured["table"] = name
        self.assert_name = name
        return FakeTableQuery(self.documents)


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
    def test_passes_year_filter_to_hybrid_search(self):
        client = FakeClient(rows=[{
            "document_id": "d1",
            "chunk_index": 0,
            "content": "content",
            "score": 0.9,
            "filename": "f.txt",
            "doc_no": "DOC-1",
            "doc_date": "2026-01-01",
            "dept": "Planning",
        }])
        out = Retriever(client, FakeEmbedder()).retrieve(
            "event schedule",
            k=5,
            dept="Planning",
            year=2026,
        )

        self.assertEqual(client.captured["name"], "hybrid_search")
        self.assertEqual(client.captured["params"]["filter_dept"], "Planning")
        self.assertEqual(client.captured["params"]["filter_year"], 2026)
        self.assertEqual(client.captured["params"]["match_count"], 5)
        self.assertEqual(len(client.captured["params"]["query_embedding"]), 1024)
        self.assertEqual(out[0].doc_no, "DOC-1")

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

    def test_expands_busan_china_consulate_query_for_retrieval(self):
        client = FakeMultiClient(rows_by_query={
            "주부산중국총영사관 교류 현황": [{
                "document_id": "exchange",
                "chunk_index": 0,
                "content": "교환학생 선발 시험",
                "score": 0.9,
                "filename": "교환학생.pdf",
            }],
            "주부산중국총영사": [{
                "document_id": "consul",
                "chunk_index": 0,
                "content": "주부산중국총영사 일행이 우리 대학교를 내방",
                "score": 0.7,
                "filename": "주부산중국총영사 내방 업무 진행.pdf",
            }],
            "주부산중국부총영사": [{
                "document_id": "vice-consul",
                "chunk_index": 0,
                "content": "주부산중국부총영사 일행이 우리 대학교를 내방",
                "score": 0.6,
                "filename": "주부산중국부총영사 내방 업무 진행.pdf",
            }],
        })

        out = Retriever(client, FakeEmbedder()).retrieve("주부산중국총영사관 교류 현황", k=8)
        query_texts = [params["query_text"] for _name, params in client.calls]

        self.assertIn("주부산중국총영사", query_texts)
        self.assertIn("주부산중국부총영사", query_texts)
        self.assertIn("consul", {source.document_id for source in out})
        self.assertIn("vice-consul", {source.document_id for source in out})

    def test_consulate_query_uses_filename_fallback_when_hybrid_misses(self):
        client = FakeMultiClient(
            rows_by_query={},
            documents=[{
                "id": "consul-doc",
                "status": "processed",
                "filename": "주부산중국총영사 내방 업무 진행.pdf",
                "doc_no": "국제교류팀-100",
                "doc_date": "2026-04-01",
                "dept": "국제교류팀",
                "doc_chunks": [{
                    "chunk_index": 0,
                    "content": "주부산중국총영사 일행이 우리 대학교를 내방하는 업무 진행",
                }],
            }],
        )

        out = Retriever(client, FakeEmbedder()).retrieve("주부산중국총영사관 교류 현황", k=8)

        self.assertEqual(out[0].document_id, "consul-doc")
        self.assertEqual(out[0].filename, "주부산중국총영사 내방 업무 진행.pdf")

    def test_uses_zip_named_pdf_as_citation_source(self):
        client = FakeCitationClient(
            rows=[{
                "document_id": "attach1", "chunk_index": 0, "content": "첨부 세부 내용", "score": 0.9,
                "filename": "붙임 1. 세부일정(안).hwp", "doc_no": None, "doc_date": None, "dept": None,
            }],
            documents=[
                {"id": "attach1", "zip_id": "zip1"},
                {
                    "id": "main1", "zip_id": "zip1",
                    "filename": "출장 계획 보고.pdf",
                    "doc_no": "국제교류팀-777",
                    "doc_date": "2026-06-30",
                    "dept": "국제교류팀",
                    "zip_archives": {
                        "filename": "출장 계획 보고.zip",
                        "source_path": "incoming/2026/출장 계획 보고.zip",
                    },
                },
                {
                    "id": "paper1", "zip_id": "zip1",
                    "filename": "종이결재 스캔.pdf",
                    "doc_no": "국제교류팀-888",
                    "doc_date": "2026-06-29",
                    "dept": "국제교류팀",
                    "zip_archives": {
                        "filename": "출장 계획 보고.zip",
                        "source_path": "incoming/2026/출장 계획 보고.zip",
                    },
                },
            ],
        )

        out = Retriever(client, FakeEmbedder()).retrieve("출장 일정")

        self.assertEqual(out[0].filename, "붙임 1. 세부일정(안).hwp")
        self.assertEqual(out[0].citation_filename, "출장 계획 보고.pdf")
        self.assertEqual(out[0].citation_doc_no, "국제교류팀-777")
        self.assertEqual(
            out[0].label(),
            "국제교류팀-777 · 2026-06-30 · 출장 계획 보고.pdf",
        )

    def test_falls_back_to_zip_named_pdf_when_representative_pdf_missing(self):
        client = FakeCitationClient(
            rows=[{
                "document_id": "attach1", "chunk_index": 0, "content": "첨부 내용", "score": 0.9,
                "filename": "일정계획(안).hwp", "doc_no": None, "doc_date": None, "dept": None,
            }],
            documents=[
                {
                    "id": "attach1", "zip_id": "zip1",
                    "filename": "일정계획(안).hwp",
                    "doc_no": None,
                    "doc_date": None,
                    "dept": None,
                    "zip_archives": {
                        "filename": "주부산중국부총영사 내방 업무 진행.zip",
                        "source_path": "2026/김동하/주부산중국부총영사 내방 업무 진행.zip",
                    },
                },
            ],
        )

        out = Retriever(client, FakeEmbedder()).retrieve("부총영사 내방")

        self.assertEqual(out[0].citation_filename, "주부산중국부총영사 내방 업무 진행.pdf")
        self.assertEqual(out[0].label(), "주부산중국부총영사 내방 업무 진행.pdf")

    def test_label_omits_dept_when_doc_no_already_contains_dept(self):
        source = Source(
            "d1", 0, "내용", 0.9,
            filename="문서.pdf",
            doc_no="국제교류팀-499",
            doc_date="2026-05-22",
            dept="국제교류팀",
        )

        self.assertEqual(source.label(), "국제교류팀-499 · 2026-05-22 · 문서.pdf")

    def test_expands_same_zip_documents_for_verification_context(self):
        client = FakeCitationClient(
            rows=[],
            documents=[
                {"id": "attach1", "zip_id": "zip1"},
                {
                    "id": "main1", "zip_id": "zip1",
                    "filename": "이사회 개최.pdf",
                    "doc_no": "국제교류팀-680",
                    "doc_date": "2026-06-26",
                    "dept": "국제교류팀",
                    "doc_chunks": [{"chunk_index": 0, "content": "개최형식: 서면결의"}],
                    "zip_archives": {"filename": "이사회 개최.zip"},
                },
                {
                    "id": "attach1", "zip_id": "zip1",
                    "filename": "붙임 1. 이사회 자료.hwp",
                    "doc_no": "국제교류팀-680",
                    "doc_date": "2026-06-26",
                    "dept": "국제교류팀",
                    "doc_chunks": [{"chunk_index": 0, "content": "제20회 이사회 회의자료"}],
                    "zip_archives": {"filename": "이사회 개최.zip"},
                },
            ],
        )
        source = Source("attach1", 0, "제20회 이사회 회의자료", 0.9,
                        filename="붙임 1. 이사회 자료.hwp")

        expanded = Retriever(client, FakeEmbedder()).expand_zip_context([source])

        self.assertGreaterEqual(len(expanded), 2)
        self.assertTrue(any(s.filename == "이사회 개최.pdf" for s in expanded))
        self.assertTrue(any("서면결의" in s.content for s in expanded))

    def test_full_zip_expansion_respects_char_budget(self):
        client = FakeCitationClient(
            rows=[],
            documents=[
                {"id": "attach1", "zip_id": "zip1"},
                {
                    "id": "main1", "zip_id": "zip1",
                    "filename": "이사회 개최.pdf",
                    "doc_no": "국제교류팀-680",
                    "doc_date": "2026-06-26",
                    "dept": "국제교류팀",
                    "doc_chunks": [
                        {"chunk_index": i, "content": "가" * 100} for i in range(5)
                    ],
                    "zip_archives": {"filename": "이사회 개최.zip"},
                },
                {
                    "id": "attach1", "zip_id": "zip1",
                    "filename": "붙임 1. 이사회 자료.hwp",
                    "doc_no": None,
                    "doc_date": None,
                    "dept": None,
                    "doc_chunks": [
                        {"chunk_index": i, "content": "나" * 100} for i in range(5)
                    ],
                    "zip_archives": {"filename": "이사회 개최.zip"},
                },
            ],
        )
        source = Source("attach1", 3, "질의에 걸린 첨부 청크", 0.9,
                        filename="붙임 1. 이사회 자료.hwp")

        expanded = Retriever(client, FakeEmbedder()).expand_zip_context(
            [source], limit_per_zip=None, char_budget=250)

        # 예산 250자 → 결재 PDF 청크(100자)가 첨부보다 먼저 2개까지만 확장된다.
        expansion = [s for s in expanded if (s.document_id, s.chunk_index) != ("attach1", 3)]
        self.assertEqual(len(expansion), 2)
        self.assertTrue(all(s.document_id == "main1" for s in expansion))
        # 검색으로 이미 잡힌 원본 소스는 예산과 무관하게 항상 유지된다.
        self.assertTrue(any(
            (s.document_id, s.chunk_index) == ("attach1", 3) for s in expanded))


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

    def test_context_and_citations_group_multiple_chunks_from_same_document(self):
        sources = [
            Source("d1", 0, "1절. 면접 일시는 3월 23일이다.", 0.9,
                   filename="면접.pdf", doc_no="국제교류팀-155", dept="국제교류팀"),
            Source("d1", 1, "2절. 장소는 동영관이다.", 0.8,
                   filename="면접.pdf", doc_no="국제교류팀-155", dept="국제교류팀"),
            Source("d2", 0, "추가 모집은 별도 공지한다.", 0.7,
                   filename="모집.pdf", doc_no="국제교류팀-124", dept="국제교류팀"),
        ]

        ctx = rag.build_context(sources)
        cites = rag.citations(sources)

        self.assertIn("1절. 면접 일시는", ctx)
        self.assertIn("2절. 장소는", ctx)
        self.assertNotIn("[3]", ctx)
        self.assertEqual([c["n"] for c in cites], [1, 2])
        self.assertEqual(cites[0]["document_id"], "d1")
        self.assertEqual(cites[1]["document_id"], "d2")


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

        out = rag.answer("행사 내용?", sample_sources(), client=FakeLLM())
        self.assertIn("[1]", out["answer"])
        self.assertEqual(len(out["citations"]), 2)
        # 시스템 프롬프트와 컨텍스트가 전달됐는지
        self.assertIn("자료", captured["messages"][0]["content"])
        self.assertEqual(captured["system"], rag.SYSTEM_PROMPT)


class TestApiSecretGate(unittest.TestCase):
    def test_k_limit_is_bounded_by_server_settings(self):
        service = load_service_module()
        original = service.settings
        service.settings = SimpleNamespace(api_default_k=8, api_max_k=20)
        try:
            self.assertEqual(service._bounded_k({"k": 999}), 20)
            self.assertEqual(service._bounded_k({"k": 0}), 1)
            self.assertEqual(service._bounded_k({"k": "bad"}), 8)
            self.assertEqual(service._bounded_k({}, default=12), 12)
        finally:
            service.settings = original

    def test_candidate_count_decouples_pool_from_user_k(self):
        service = load_service_module()
        s = SimpleNamespace(rerank_max_candidates=50)
        # 결과 상한(k)과 무관하게 후보를 rerank_max_candidates 까지 가져온다.
        self.assertEqual(service._candidate_count(8, s), 50)
        self.assertEqual(service._candidate_count(12, s), 50)
        # SQL 클램프(60) 를 넘지 않는다.
        self.assertEqual(service._candidate_count(8, SimpleNamespace(rerank_max_candidates=200)), 60)
        # k 가 후보 상한보다 크면 k 를 존중한다.
        self.assertEqual(service._candidate_count(55, SimpleNamespace(rerank_max_candidates=50)), 55)

    def test_target_year_accepts_only_reasonable_years(self):
        service = load_service_module()
        self.assertEqual(service._target_year({"target_year": "2026"}), 2026)
        self.assertEqual(service._target_year({"year": 2025}), 2025)
        self.assertIsNone(service._target_year({"target_year": "1999"}))
        self.assertIsNone(service._target_year({"target_year": "bad"}))

    def test_source_year_can_differ_from_target_year_for_hermes_workflows(self):
        service = load_service_module()

        self.assertEqual(
            service._source_year({"source_year": 2026, "target_year": 2027}),
            2026,
        )
        self.assertEqual(service._source_year({"year": 2025, "target_year": 2027}), 2025)
        self.assertEqual(service._source_year({"target_year": 2027}), 2027)
        self.assertIsNone(service._source_year({"source_year": "bad", "target_year": "1999"}))

    def test_missing_secret_configuration_allows_local_development(self):
        service = load_service_module()
        settings = SimpleNamespace(api_shared_secret="")
        service.require_api_secret(None, settings)

    def test_matching_secret_is_required_when_configured(self):
        service = load_service_module()
        settings = SimpleNamespace(api_shared_secret="secret-value")

        with self.assertRaises(Exception) as missing:
            service.require_api_secret(None, settings)
        self.assertEqual(getattr(missing.exception, "status_code", None), 401)

        with self.assertRaises(Exception) as wrong:
            service.require_api_secret("wrong", settings)
        self.assertEqual(getattr(wrong.exception, "status_code", None), 401)

        service.require_api_secret("secret-value", settings)


if __name__ == "__main__":
    unittest.main()
