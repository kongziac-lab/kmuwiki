import sys
import types
import unittest

from kmu_query import rag
from kmu_query.retriever import Source


def _src():
    return Source("d1", 0, "면접은 3월 23일 동영관에서 진행됩니다.", 0.9,
                  filename="안내.hwp", doc_no="국제교류팀-155", doc_date="2026-03-23", dept="국제교류팀")


class _Delta:
    def __init__(self, c): self.content = c
class _Choice:
    def __init__(self, c): self.delta = _Delta(c)
class _Chunk:
    def __init__(self, c): self.choices = [_Choice(c)]
class _Completions:
    def create(self, **kw):
        _Completions.kw = kw
        return [_Chunk("면접은 "), _Chunk("3월 23일 [1]"), _Chunk("")]  # 빈 델타도 안전 처리돼야
class _Chat:
    def __init__(self): self.completions = _Completions()
class _OpenAI:
    def __init__(self, **kw): _OpenAI.kw = kw; self.chat = _Chat()


class TestNousProvider(unittest.TestCase):
    def setUp(self):
        fake = types.ModuleType("openai")
        fake.OpenAI = _OpenAI
        self._saved = sys.modules.get("openai")
        sys.modules["openai"] = fake

    def tearDown(self):
        if self._saved is not None:
            sys.modules["openai"] = self._saved
        else:
            sys.modules.pop("openai", None)

    def test_streams_and_passes_config(self):
        out = "".join(rag.stream_answer(
            "면접 언제?", [_src()], provider="nous", model="Hermes-4-70B",
            nous_key="sk-test", nous_base_url="https://inference-api.nousresearch.com/v1"))
        self.assertEqual(out, "면접은 3월 23일 [1]")
        # 모델/메시지/스트림 인자가 OpenAI 호환으로 전달됐는지
        self.assertEqual(_Completions.kw["model"], "Hermes-4-70B")
        self.assertTrue(_Completions.kw["stream"])
        self.assertEqual(_Completions.kw["messages"][0]["role"], "system")
        self.assertEqual(_OpenAI.kw["base_url"], "https://inference-api.nousresearch.com/v1")

    def test_no_sources_refuses_without_calling_llm(self):
        out = "".join(rag.stream_answer("x", [], provider="nous", model="Hermes-4-70B", nous_key="sk"))
        self.assertEqual(out, rag.REFUSAL)


if __name__ == "__main__":
    unittest.main()
