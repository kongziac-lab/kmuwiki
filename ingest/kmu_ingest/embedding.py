"""임베딩 제공자 추상화 (불변식 3·6 / §7.D).

- 차원은 항상 EMBED_DIM(1024).
- 모델/버전을 함께 보고하여 doc_chunks.embed_model/embed_version 에 기록(모델 핀).
- 제공자 교체가 자유롭도록 Protocol 뒤에 둔다(외부 정책 변경 시 로컬 전환 대비).

제공자:
  FakeEmbedder   : 결정적 해시 기반. 모델/네트워크 없이 파이프라인 e2e 검증용.
  BGEM3Embedder  : 로컬/클라우드 양쪽 가능(권장 기본). FlagEmbedding lazy import.
"""

from __future__ import annotations

import base64
import hashlib
import math
import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .config import EMBED_DIM


@dataclass(frozen=True)
class EmbeddingInput:
    """Provider-neutral document input.

    Image bytes are accepted only after ``VisualSanitizer`` produced a redacted
    derivative.  Raw parser bytes must never be placed in this object.
    """

    text: str
    image_bytes: bytes | None = None
    media_type: str | None = None


@runtime_checkable
class EmbeddingProvider(Protocol):
    model: str
    version: str
    supports_images: bool

    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def embed_inputs(self, inputs: list[EmbeddingInput]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class FakeEmbedder:
    """결정적 의사 임베딩(개발/테스트). 같은 입력 → 같은 벡터, L2 정규화."""

    def __init__(self, model: str = "fake-deterministic", version: str = "v1"):
        self.model = model
        self.version = version
        self.supports_images = True

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def embed_inputs(self, inputs: list[EmbeddingInput]) -> list[list[float]]:
        return [self._one(
            value.text + (":" + hashlib.sha256(value.image_bytes).hexdigest()
                          if value.image_bytes else "")
        ) for value in inputs]

    def embed_query(self, text: str) -> list[float]:
        return self._one(text)

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
        self.supports_images = False
        self._m = BGEM3FlagModel(model, use_fp16=True)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = self._m.encode(texts, batch_size=16, max_length=8192)
        return [v.tolist() for v in out["dense_vecs"]]

    def embed_inputs(self, inputs: list[EmbeddingInput]) -> list[list[float]]:
        if any(item.image_bytes for item in inputs):
            raise ValueError("BAAI/bge-m3 does not support multimodal v2 image inputs")
        return self.embed([item.text for item in inputs])

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]


class CohereEmbedder:
    """Cohere Embed v4 (mixed text/image) with pinned output dimension.

    문서/쿼리 input_type을 구분한다(검색 품질에 중요):
      - 문서 적재: search_document
      - 쿼리:      search_query  (retriever가 embed_query 사용)

    Text-only v3 remains readable during the cut-over, but image/mixed inputs
    intentionally require v4 so the pipeline cannot silently pretend that a
    visual index was built.
    """

    def __init__(self, model: str = "embed-v4.0", version: str = "v4.0-1024",
                 api_key: str | None = None, timeout: float | None = None,
                 output_dimension: int = EMBED_DIM):
        import cohere  # lazy

        self.model = model
        self.version = version
        self.output_dimension = output_dimension
        if output_dimension != EMBED_DIM:
            raise ValueError(f"KMU Wiki embedding dimension must be {EMBED_DIM}")
        self.supports_images = model.startswith("embed-v4")
        timeout = timeout or float(os.environ.get("KMU_PROVIDER_TIMEOUT_SECONDS", "120"))
        self._client = cohere.ClientV2(
            api_key or os.environ.get("COHERE_API_KEY"),
            timeout=timeout,
        )

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), 96):  # Cohere 배치 상한 96
            kwargs = {
                "texts": texts[i:i + 96],
                "model": self.model,
                "input_type": input_type,
                "embedding_types": ["float"],
            }
            if self.model.startswith("embed-v4"):
                kwargs["output_dimension"] = self.output_dimension
            resp = self._client.embed(**kwargs)
            out.extend(resp.embeddings.float_)
        return self._validate(out)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "search_document")

    def embed_inputs(self, inputs: list[EmbeddingInput]) -> list[list[float]]:
        if not inputs:
            return []
        if not any(item.image_bytes for item in inputs):
            return self.embed([item.text for item in inputs])
        if not self.supports_images:
            raise ValueError("multimodal v2 requires Cohere embed-v4.0")

        vectors: list[list[float]] = []
        for batch in _multimodal_batches(inputs):
            payload = []
            for item in batch:
                content = []
                if item.text:
                    content.append({"type": "text", "text": item.text})
                if item.image_bytes:
                    media_type = item.media_type or "image/jpeg"
                    encoded = base64.b64encode(item.image_bytes).decode("ascii")
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{encoded}"},
                    })
                payload.append({"content": content})
            response = self._client.embed(
                model=self.model,
                inputs=payload,
                input_type="search_document",
                embedding_types=["float"],
                output_dimension=self.output_dimension,
            )
            vectors.extend(response.embeddings.float_)
        return self._validate(vectors)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "search_query")[0]

    def _validate(self, vectors: list[list[float]]) -> list[list[float]]:
        if any(len(vector) != EMBED_DIM for vector in vectors):
            raise ValueError(f"embedding dimension mismatch; expected {EMBED_DIM}")
        return vectors


def _multimodal_batches(
    inputs: list[EmbeddingInput], *, max_items: int = 96, max_image_bytes: int = 12 * 1024 * 1024,
):
    """Stay below Cohere's 20MB request limit after base64 expansion."""
    batch: list[EmbeddingInput] = []
    image_bytes = 0
    for item in inputs:
        item_bytes = len(item.image_bytes or b"")
        if batch and (len(batch) >= max_items or image_bytes + item_bytes > max_image_bytes):
            yield batch
            batch = []
            image_bytes = 0
        if item_bytes > max_image_bytes:
            raise ValueError("one visual embedding input exceeds the safe request limit")
        batch.append(item)
        image_bytes += item_bytes
    if batch:
        yield batch


def make_embedder(
    provider: str, model: str, version: str, *, output_dimension: int = EMBED_DIM,
) -> EmbeddingProvider:
    if provider == "fake":
        return FakeEmbedder(model, version)
    if provider == "bge-m3":
        return BGEM3Embedder(model or "BAAI/bge-m3", version)
    if provider == "cohere":
        return CohereEmbedder(
            model or "embed-v4.0",
            version or "v4.0-1024",
            output_dimension=output_dimension,
        )
    raise ValueError(f"알 수 없는 임베딩 제공자: {provider}")
