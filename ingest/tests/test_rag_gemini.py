import sys
import types as py_types
import unittest

from kmu_ingest.config import Settings
from kmu_query import rag
from kmu_query.retriever import Source


def _src():
    return Source("d1", 0, "면접은 3월 23일 동영관에서 진행됩니다.", 0.9,
                  filename="안내.hwp", doc_no="국제교류팀-155", doc_date="2026-03-23", dept="국제교류팀")


class _Chunk:
    def __init__(self, text):
        self.text = text


class _GenerateContentConfig:
    def __init__(self, **kw):
        _GenerateContentConfig.kw = kw


class _Models:
    def generate_content_stream(self, **kw):
        _Models.kw = kw
        return [_Chunk("면접은 "), _Chunk("3월 23일 [1]"), _Chunk("")]


class _Client:
    closed = False

    def __init__(self, **kw):
        _Client.kw = kw
        self.models = _Models()

    def close(self):
        _Client.closed = True


class TestGeminiProvider(unittest.TestCase):
    def setUp(self):
        _Client.closed = False
        fake_google = py_types.ModuleType("google")
        fake_genai = py_types.ModuleType("google.genai")
        fake_types = py_types.ModuleType("google.genai.types")
        fake_genai.Client = _Client
        fake_types.GenerateContentConfig = _GenerateContentConfig
        fake_genai.types = fake_types
        fake_google.genai = fake_genai
        self._saved_google = sys.modules.get("google")
        self._saved_genai = sys.modules.get("google.genai")
        self._saved_types = sys.modules.get("google.genai.types")
        sys.modules["google"] = fake_google
        sys.modules["google.genai"] = fake_genai
        sys.modules["google.genai.types"] = fake_types

    def tearDown(self):
        for key, saved in (
            ("google", self._saved_google),
            ("google.genai", self._saved_genai),
            ("google.genai.types", self._saved_types),
        ):
            if saved is not None:
                sys.modules[key] = saved
            else:
                sys.modules.pop(key, None)

    def test_streams_with_developer_api_key_and_system_instruction(self):
        out = "".join(rag.stream_answer(
            "면접 안내", [_src()], provider="gemini", model="gemini-2.5-pro",
            gemini_key="gemini-key"))

        self.assertEqual(out, "면접은 3월 23일 [1]")
        self.assertEqual(_Client.kw["api_key"], "gemini-key")
        self.assertEqual(_Models.kw["model"], "gemini-2.5-pro")
        self.assertIn("자료:", _Models.kw["contents"])
        self.assertEqual(_GenerateContentConfig.kw["system_instruction"], rag.SYSTEM_PROMPT)
        self.assertEqual(_GenerateContentConfig.kw["max_output_tokens"], rag.GEMINI_MAX_OUTPUT_TOKENS)
        self.assertTrue(_Client.closed)

    def test_streams_with_vertex_region_when_configured(self):
        out = "".join(rag.stream_answer(
            "면접 안내", [_src()], provider="gemini", model="gemini-2.5-pro",
            gemini_use_vertex=True, gemini_project="kmu-project", gemini_location="asia-northeast3"))

        self.assertEqual(out, "면접은 3월 23일 [1]")
        self.assertEqual(_Client.kw["vertexai"], True)
        self.assertEqual(_Client.kw["project"], "kmu-project")
        self.assertEqual(_Client.kw["location"], "asia-northeast3")

    def test_no_sources_refuses_without_calling_gemini(self):
        out = "".join(rag.stream_answer("x", [], provider="gemini", model="gemini-2.5-pro", gemini_key="sk"))
        self.assertEqual(out, rag.REFUSAL)


class TestGeminiSettings(unittest.TestCase):
    def test_gemini_is_explicit_only_and_uses_seoul_vertex_default(self):
        settings = Settings(
            anthropic_api_key="",
            cohere_api_key="cohere",
            gemini_api_key="gemini",
            llm_provider="",
        )
        self.assertEqual(settings.resolve_llm(), ("cohere", settings.cohere_chat_model))

        settings = Settings(llm_provider="gemini", gemini_model="gemini-2.5-pro")
        self.assertEqual(settings.resolve_llm(), ("gemini", "gemini-2.5-pro"))
        self.assertEqual(settings.gemini_location, "asia-northeast3")


if __name__ == "__main__":
    unittest.main()
