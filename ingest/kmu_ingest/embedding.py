"""임베딩 제공자 추상화 (불변식 3·6 / §7.D).

- 차원은 항상 EMBED_DIM(1024).
- 모델/버전을 함께 보고하여 doc_chunks.embed_model/embed_version 에 기록(모델 핀).
- 제공자 교체가 자유롭도록 Protocol 뒤에 둔다(외부 정책 변경 시 로컬 전환 대비).

제공자:
  FakeEmbedder   : 결정적 해시 기반. 모델/네트워크 없이 파이프라인 e2e 검증용.
  BGEM3Embedder  : 로컬/클라우드 양쪽 가능(권장 기본). FlagEmbedding lazy import.
"""

from __future__ import annotations

import hashlib
import math
import os
from typing import Protocol, runtime_checkable

from .config import EMBED_DIM


@runtime_checkable
class EmbeddingProvider(Protocol):
    model: str
    version: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FakeEmbedder:
    """결정적 의사 임베딩(개발/테스트). 같은 입력 → 같은 벡터, L2 정규화."""

    def __init__(self, model: str = "fake-deterministic", version: str = "v1"):
        self.model = model
        self.version = version

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec: list[float] = []
        i = 0
        while len(vec) < EMBED_DIM:
            h = hashlib.sha256(f"{i}:{text}".encode()).digest()
            for b in h:
                vec.append((b / 255.0) * 2 - 1)
                if len(vec) >= EMBED_DIM:
                    break
            i += 1
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class BGEM3Embedder:
    """BAAI/bge-m3 (1024d, 다국어·한국어 강함). FlagEmbedding 필요."""

    def __init__(self, model: str = "BAAI/bge-m3", version: str = "v1"):
        from FlagEmbedding import BGEM3FlagModel  # lazy

        self.model = model
        self.version = version
        self._m = BGEM3FlagModel(model, use_fp16=True)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = self._m.encode(texts, batch_size=16, max_length=8192)
        return [v.tolist() for v in out["dense_vecs"]]


class CohereEmbedder:
    """Cohere embed-multilingual-v3.0 (1024d, 다국어·한국어 강함).

    v3는 문서/쿼리 input_type을 구분한다(검색 품질에 중요):
      - 문서 적재: search_document
      - 쿼리:      search_query  (retriever가 embed_query 사용)
    """

    def __init__(self, model: str = "embed-multilingual-v3.0", version: str = "v3",
                 api_key: str | None = None):
        import cohere  # lazy

        self.model = model
        self.version = version
        self._client = cohere.ClientV2(api_key or os.environ.get("COHERE_API_KEY"))

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 96):  # Cohere 배치 상한 96
            resp = self._client.embed(
                texts=texts[i:i + 96], model=self.model,
                input_type=input_type, embedding_types=["float"])
            out.extend(resp.embeddings.float_)
        return out

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "search_document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "search_query")[0]


def make_embedder(provider: str, model: str, version: str) -> EmbeddingProvider:
    if provider == "fake":
        return FakeEmbedder(model, version)
    if provider == "bge-m3":
        return BGEM3Embedder(model or "BAAI/bge-m3", version)
    if provider == "cohere":
        return CohereEmbedder(model or "embed-multilingual-v3.0", version or "v3")
    raise ValueError(f"알 수 없는 임베딩 제공자: {provider}")
