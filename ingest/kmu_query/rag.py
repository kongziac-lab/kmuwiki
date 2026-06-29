"""RAG — 검색된 출처만 근거로 Claude가 인용과 함께 답한다.

핵심 규칙(트러스트 바운더리):
  - 답변은 '제공된 출처'에만 근거한다(환각 억제).
  - 각 근거에 [n] 인용을 단다.
  - 출처가 없으면 LLM을 호출하지 않고 '모름'으로 답한다(불필요 호출·환각 차단).
  - 컨텍스트의 마스킹 토큰([주민등록번호] 등)은 그대로 둔다.
"""

from __future__ import annotations

from .retriever import Source

REFUSAL = "제공된 자료에서 관련 내용을 찾지 못했습니다. 질문을 더 구체화하거나 권한 범위를 확인해 주세요."

SYSTEM_PROMPT = (
    "당신은 대학 행정 문서 위키의 비서입니다. 반드시 아래 '자료'에 있는 내용만 근거로 "
    "한국어로 간결히 답하세요. 각 근거 문장 끝에 [번호] 형식으로 출처를 표기하세요. "
    "자료에 없는 내용은 추측하지 말고 모른다고 답하세요. "
    "마스킹 토큰([주민등록번호] 등)은 그대로 두고 복원하려 하지 마세요."
)


def build_context(sources: list[Source]) -> str:
    """검색 결과를 번호 매긴 컨텍스트 블록으로."""
    blocks = []
    for i, s in enumerate(sources, start=1):
        blocks.append(f"[{i}] ({s.label()})\n{s.content.strip()}")
    return "\n\n".join(blocks)


def build_user_prompt(query: str, sources: list[Source]) -> str:
    return f"자료:\n{build_context(sources)}\n\n질문: {query}"


def citations(sources: list[Source]) -> list[dict]:
    """UI 표시용 출처 목록(번호 → 문서)."""
    return [{
        "n": i,
        "document_id": s.document_id,
        "label": s.label(),
        "filename": s.filename,
        "doc_no": s.doc_no,
        "doc_date": s.doc_date,
    } for i, s in enumerate(sources, start=1)]


def answer(query: str, sources: list[Source], client=None,
           model: str = "claude-opus-4-8") -> dict:
    """비스트리밍 답변. 출처 없으면 LLM 호출 없이 거절."""
    if not sources:
        return {"answer": REFUSAL, "citations": []}

    client = client or _default_client()
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(query, sources)}],
    )
    text = "".join(block.text for block in resp.content if block.type == "text")
    return {"answer": text, "citations": citations(sources)}


def _default_client():
    import anthropic  # lazy
    return anthropic.Anthropic()


def stream_answer(query: str, sources: list[Source], *, provider: str, model: str,
                  anthropic_key: str | None = None, cohere_key: str | None = None):
    """답변 토큰 스트리밍(제공자 무관). 출처 없으면 LLM 호출 없이 거절 1회.

    provider: "anthropic"(Claude) | "cohere"(command-r). 둘 다 동일 RAG 프롬프트 사용.
    """
    if not sources:
        yield REFUSAL
        return
    prompt = build_user_prompt(query, sources)

    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key or None)
        with client.messages.stream(
            model=model, max_tokens=1024, system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            yield from stream.text_stream

    elif provider == "cohere":
        import cohere
        client = cohere.ClientV2(cohere_key)
        for ev in client.chat_stream(model=model, messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]):
            if ev.type == "content-delta":
                yield ev.delta.message.content.text

    else:
        raise ValueError(f"알 수 없는 LLM provider: {provider}")
