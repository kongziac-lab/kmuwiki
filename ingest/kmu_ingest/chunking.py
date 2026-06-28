"""청킹 전략 (§7.C).

구조 인식: 문단(빈 줄) 경계를 우선 보존하고, 목표 길이로 누적하며 중첩을 둔다.
길이는 문자 수 기준(한국어 근사). 토큰 정밀 산정은 임베딩 단계에서 보정 가능.
각 청크에는 문서 메타 프리픽스를 붙여 검색 정확도를 높인다(선택).
"""

from __future__ import annotations

import re

from .models import Chunk

_PARA = re.compile(r"\n\s*\n")


def chunk_text(
    text: str,
    target_chars: int = 1200,
    overlap_chars: int = 200,
    prefix: str | None = None,
) -> list[Chunk]:
    """문단 인식 청킹.

    target_chars: 청크 목표 길이(문자). 1200자 ≈ 한국어 400~500 토큰.
    overlap_chars: 인접 청크 간 중첩(문맥 보존).
    prefix: 각 청크 앞에 붙일 메타(예: "[기획처 2025-03-02 제2025-13호]").
    """
    text = (text or "").strip()
    if not text:
        return []

    paras = [p.strip() for p in _PARA.split(text) if p.strip()]
    pieces: list[str] = []
    buf = ""
    for para in paras:
        if not buf:
            buf = para
        elif len(buf) + 1 + len(para) <= target_chars:
            buf += "\n" + para
        else:
            pieces.append(buf)
            buf = para
        # 한 문단이 목표보다 길면 강제 분할
        while len(buf) > target_chars:
            pieces.append(buf[:target_chars])
            buf = buf[target_chars - overlap_chars:]
    if buf:
        pieces.append(buf)

    # 중첩 적용(문단 단위로 못 만든 경계에 한해 앞 꼬리를 덧붙임)
    chunks: list[Chunk] = []
    for i, piece in enumerate(pieces):
        body = piece
        if i > 0 and overlap_chars > 0:
            tail = pieces[i - 1][-overlap_chars:]
            if tail and not body.startswith(tail):
                body = tail + "\n" + body
        content = f"{prefix}\n{body}" if prefix else body
        chunks.append(Chunk(chunk_index=i, content=content, token_count=len(content)))
    return chunks
