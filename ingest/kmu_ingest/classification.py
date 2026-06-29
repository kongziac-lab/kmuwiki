"""Knowledge-base organization helpers.

원본 ZIP 파일 위치와 무관하게 문서 본문/파일명에서 업무 카테고리를 보수적으로 추정한다.
확신도가 낮으면 `review_required`를 남겨 운영자가 나중에 고칠 수 있게 한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Classification:
    task_category: str
    confidence: float
    review_required: bool


_SPACE = re.compile(r"\s+")


def _compact(text: str) -> str:
    return _SPACE.sub("", text.lower())


def classify_document(filename: str, path_in_zip: str, text: str | None) -> Classification:
    """문서를 업무 카테고리로 분류한다.

    지금은 비용 없는 규칙 기반 분류다. 임베딩은 검색/유사도 정리에 계속 사용하고,
    이 값은 목록 필터와 운영 검토 큐를 위한 1차 라벨로 저장한다.
    """
    blob = "\n".join([filename or "", path_in_zip or "", text or ""])
    compact = _compact(blob)

    if "초청교환학생" in compact or ("초청" in compact and "교환학생" in compact):
        return Classification("초청교환학생", 0.95, False)
    if "파견교환학생" in compact or ("파견" in compact and "교환학생" in compact):
        return Classification("파견교환학생", 0.95, False)
    if "교환학생선발" in compact or ("교환학생" in compact and "선발" in compact):
        return Classification("파견교환학생", 0.9, False)
    if "비자" in compact or "사증" in compact:
        return Classification("비자", 0.9, False)
    if "장학" in compact:
        return Classification("장학", 0.85, False)
    if "협정" in compact or "mou" in compact:
        return Classification("협정", 0.85, False)
    if "국외출장" in compact or "출장" in compact:
        return Classification("국외출장", 0.85, False)

    return Classification("미분류", 0.0, True)
