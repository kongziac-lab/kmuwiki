import unittest

from kmu_query import rag, studio
from kmu_query.retriever import Source


def sources():
    return [
        Source("d1", 0, "2026학년도 2학기 해외 파견 교환학생 후보 선발 면접전형을 3월 23일 실시한다.", 0.9,
               filename="붙임 1. 면접전형 계획(안).pdf",
               doc_no="국제교류팀-155", doc_date="2026-03-02", dept="국제교류팀"),
        Source("d2", 0, "해외 파견 교환학생 서류전형 결과를 안내한다.", 0.8,
               filename="서류전형 결과.pdf",
               doc_no="국제교류팀-124", doc_date="2026-02-10", dept="국제교류팀"),
        Source("d3", 0, "국외 출장 계획을 보고한다.", 0.7,
               filename="출장 계획.pdf",
               doc_no="총무처-88", doc_date="2026-05-01", dept="총무처"),
    ]


class TestStudioMetrics(unittest.TestCase):
    def test_counts_unique_documents_and_categories(self):
        m = studio.studio_metrics("교환학생", sources())
        self.assertEqual(m["document_count"], 3)
        self.assertGreaterEqual(m["category_count"], 2)
        self.assertEqual(m["period_start"], "2026-02-10")
        self.assertEqual(m["period_end"], "2026-05-01")
        labels = [c["label"] for c in m["categories"]]
        self.assertIn("교환학생 선발", labels)
        # 카테고리는 문서 수 내림차순
        self.assertEqual(m["categories"][0]["count"], max(c["count"] for c in m["categories"]))

    def test_duplicate_document_ids_counted_once(self):
        dup = sources() + [sources()[0]]
        self.assertEqual(studio.studio_metrics("q", dup)["document_count"], 3)

    def test_empty_sources_safe(self):
        m = studio.studio_metrics("q", [])
        self.assertEqual(m["document_count"], 0)
        self.assertEqual(m["categories"], [])
        self.assertIsNone(m["period_start"])


class TestMindmap(unittest.TestCase):
    def test_starts_with_mindmap_and_root(self):
        mm = studio.build_mindmap_mermaid("교환학생 선발", sources())
        lines = mm.splitlines()
        self.assertEqual(lines[0], "mindmap")
        self.assertTrue(lines[1].strip().startswith("root(("))
        self.assertIn("교환학생 선발", mm)

    def test_sanitizes_unsafe_characters(self):
        s = [Source("d1", 0, "내용", 0.9, filename="붙임 1. 면접(계획)[안].pdf",
                    doc_no="국제교류팀-155", doc_date="2026-03-02", dept="국제교류팀")]
        mm = studio.build_mindmap_mermaid("괄호(test)", s)
        # 루트/노드 라인에는 셰이프를 여는 괄호 외의 원시 괄호가 없어야 한다.
        for line in mm.splitlines()[1:]:
            body = line.strip()
            if body.startswith("root(("):
                continue
            self.assertNotIn("(", body)
            self.assertNotIn("[", body)

    def test_empty_sources_reports_no_evidence(self):
        mm = studio.build_mindmap_mermaid("q", [])
        self.assertIn("근거 문서 없음", mm)


class TestMindmapSemanticGrouping(unittest.TestCase):
    def _work_ids(self):
        from kmu_query.insights import group_work_items
        return [w["work_id"] for w in group_work_items(sources())]

    def test_groups_param_overrides_rule_based_labels(self):
        wids = self._work_ids()
        groups = {wid: "테마 A" for wid in wids}
        mm = studio.build_mindmap_mermaid("q", sources(), groups=groups)
        self.assertIn("테마 A", mm)
        # 규칙기반 분류 라벨(교환학생 선발)은 그룹 라벨로 대체되어야 한다.
        self.assertNotIn("    교환학생 선발", mm)

    def test_parse_cluster_response_keeps_valid_ids_and_fallbacks(self):
        from kmu_query.insights import group_work_items
        work_items = group_work_items(sources())
        wids = [w["work_id"] for w in work_items]
        text = ('{"groups": [{"label": "학생 선발", "work_ids": ["%s"]}]}' % wids[0])
        mapping = studio.parse_cluster_response(text, work_items)
        # 매핑된 id는 LLM 라벨, 나머지는 규칙기반 폴백(모든 id 포함).
        self.assertEqual(mapping[wids[0]], "학생 선발")
        self.assertEqual(set(mapping.keys()), set(wids))
        for wid in wids[1:]:
            self.assertTrue(mapping[wid])

    def test_parse_cluster_response_ignores_hallucinated_ids(self):
        from kmu_query.insights import group_work_items
        work_items = group_work_items(sources())
        text = '{"groups": [{"label": "가짜", "work_ids": ["does-not-exist"]}]}'
        mapping = studio.parse_cluster_response(text, work_items)
        self.assertNotIn("does-not-exist", mapping)
        self.assertNotIn("가짜", mapping.values())

    def test_parse_cluster_response_survives_malformed_json(self):
        from kmu_query.insights import group_work_items
        work_items = group_work_items(sources())
        mapping = studio.parse_cluster_response("이건 JSON이 아닙니다", work_items)
        self.assertEqual(set(mapping.keys()), {w["work_id"] for w in work_items})

    def test_cluster_prompt_lists_work_ids(self):
        from kmu_query.insights import group_work_items
        work_items = group_work_items(sources())
        prompt = studio.build_cluster_prompt("교환학생", work_items)
        for w in work_items:
            self.assertIn(w["work_id"], prompt)

    def test_cluster_work_items_falls_back_on_generate_error(self):
        def boom(system, prompt):
            raise RuntimeError("llm down")
        mapping = studio.cluster_work_items("q", sources(), boom)
        # 규칙기반 task_category 로 완전 폴백.
        self.assertTrue(all(v for v in mapping.values()))

    def test_cluster_work_items_skips_llm_for_single_work(self):
        calls = []
        def gen(system, prompt):
            calls.append(1)
            return "{}"
        one = [sources()[0]]
        studio.cluster_work_items("q", one, gen)
        self.assertEqual(calls, [])  # 업무 1개면 LLM 호출 안 함


class TestSlides(unittest.TestCase):
    def test_marp_frontmatter_and_sections(self):
        md = studio.build_slides_marp("교환학생 선발", sources())
        self.assertTrue(md.startswith("---\nmarp: true"))
        self.assertIn("## 개요", md)
        self.assertIn("## 출처", md)
        # 슬라이드 구분자가 여러 개 있어야 한다.
        self.assertGreaterEqual(md.count("\n---\n"), 2)

    def test_empty_sources_safe(self):
        md = studio.build_slides_marp("q", [])
        self.assertIn("marp: true", md)
        self.assertIn("근거 문서", md)


class TestInfographic(unittest.TestCase):
    def test_returns_valid_svg(self):
        svg = studio.build_infographic_svg("교환학생 선발", sources())
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(svg.rstrip().endswith("</svg>"))
        self.assertIn("viewBox", svg)

    def test_escapes_text(self):
        s = [Source("d1", 0, "내용", 0.9, filename="a<b>&c.pdf",
                    doc_no="x-1", doc_date="2026-01-01", dept="A<B>")]
        svg = studio.build_infographic_svg("<script>", s)
        self.assertNotIn("<script>", svg)
        self.assertIn("&lt;script&gt;", svg)

    def test_empty_sources_safe(self):
        svg = studio.build_infographic_svg("q", [])
        self.assertTrue(svg.startswith("<svg"))
        self.assertIn("근거 문서", svg)


class TestSummaryStream(unittest.TestCase):
    def test_no_sources_refuses_without_llm(self):
        out = "".join(rag.stream_summary("q", [], provider="anthropic", model="m"))
        self.assertEqual(out, rag.REFUSAL)

    def test_summary_prompt_uses_summary_format_and_context(self):
        prompt = rag.build_summary_prompt("교환학생", sources())
        self.assertIn("자료:", prompt)
        self.assertIn("[1]", prompt)
        self.assertIn("교환학생", prompt)

    def test_stream_summary_uses_summary_system_prompt(self):
        captured = {}

        class FakeStream:
            text_stream = ["## 한눈에 보기\n요약입니다 [1]"]

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        class FakeMessages:
            def stream(self, **kw):
                captured.update(kw)
                return FakeStream()

        class FakeClient:
            messages = FakeMessages()

        import kmu_query.rag as ragmod
        orig = ragmod.anthropic if hasattr(ragmod, "anthropic") else None
        # anthropic 모듈을 주입해 실제 SDK 없이 스트리밍 경로를 검증한다.
        import sys
        import types as pytypes
        fake_anthropic = pytypes.ModuleType("anthropic")
        fake_anthropic.Anthropic = lambda **kw: FakeClient()
        saved = sys.modules.get("anthropic")
        sys.modules["anthropic"] = fake_anthropic
        try:
            out = "".join(rag.stream_summary(
                "교환학생", sources(), provider="anthropic", model="claude-x", anthropic_key="k"))
        finally:
            if saved is not None:
                sys.modules["anthropic"] = saved
            else:
                sys.modules.pop("anthropic", None)

        self.assertIn("한눈에 보기", out)
        self.assertEqual(captured["system"], rag.SUMMARY_SYSTEM_PROMPT)
        self.assertEqual(captured["max_tokens"], 2048)


if __name__ == "__main__":
    unittest.main()
