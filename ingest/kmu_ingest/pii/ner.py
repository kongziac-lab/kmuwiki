"""한국어 NER 마스킹 (§7.A L2).

정규식(L1)이 잡지 못하는 비정형 PII — 이름(PER)·주소(LOC) — 를 마스킹한다.
기관/부서(ORG)는 위키 검색에 필요한 신호라 기본 비마스킹(mask_org 로 옵트인).

백엔드는 HuggingFace token-classification 파이프라인(lazy). 모델/엔티티 라벨이
제각각이라 라벨을 PER/LOC/ORG 로 정규화한다. 테스트·대체 구현을 위해
extractor(callable[str]->list[Entity]) 를 주입할 수 있다.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

# 라벨 → 마스킹 토큰
LABEL_TOKEN = {"PER": "성명", "LOC": "주소", "ORG": "기관"}

DEFAULT_MODEL = os.environ.get("KMU_NER_MODEL", "Leo97/KoELECTRA-small-v3-modu-ner")


@dataclass
class Entity:
    label: str   # PER | LOC | ORG (정규화된 값)
    start: int
    end: int


def _normalize_label(raw: str) -> str | None:
    u = raw.upper()
    if u.startswith(("PER", "PS", "PERSON")):
        return "PER"
    if u.startswith(("LOC", "LC", "LOCATION")):
        return "LOC"
    if u.startswith(("ORG", "OG", "ORGANIZATION")):
        return "ORG"
    return None


class KoreanNER:
    def __init__(
        self,
        model: str | None = None,
        mask_org: bool = False,
        extractor: Callable[[str], list[Entity]] | None = None,
    ):
        self.model = model or DEFAULT_MODEL
        self.mask_labels = {"PER", "LOC"} | ({"ORG"} if mask_org else set())
        self._extractor = extractor
        self._pipe = None

    def ensure(self) -> bool:
        """백엔드 가용성 확보. 주입 추출기가 있으면 모델 없이 True.

        운영에서 transformers/모델 로드 실패 시 False → 호출측은 NER 비활성으로 처리.
        (실패를 숨기지 않는다: 이름 마스킹 미작동을 ner_available=False 로 드러낸다.)
        """
        if self._extractor is not None:
            return True
        if self._pipe is not None:
            return True
        try:
            from transformers import pipeline  # lazy, heavy
        except ImportError:
            return False
        try:
            self._pipe = pipeline(
                "token-classification",
                model=self.model,
                aggregation_strategy="simple",
            )
            return True
        except Exception:
            return False

    def mask(self, text: str) -> tuple[str, dict[str, int]]:
        ents = [e for e in self._extract(text) if e.label in self.mask_labels]
        # 스팬 겹침 제거 + 뒤에서부터 치환(인덱스 보존)
        ents = _dedupe_spans(ents)
        counts: dict[str, int] = {}
        for e in sorted(ents, key=lambda x: x.start, reverse=True):
            token = LABEL_TOKEN[e.label]
            text = text[: e.start] + f"[{token}]" + text[e.end :]
            counts[token] = counts.get(token, 0) + 1
        return text, counts

    def _extract(self, text: str) -> list[Entity]:
        if self._extractor is not None:
            return self._extractor(text)
        if self._pipe is None:
            return []
        out: list[Entity] = []
        for r in self._pipe(text):
            label = _normalize_label(str(r.get("entity_group", "")))
            start, end = r.get("start"), r.get("end")
            if label and start is not None and end is not None and end > start:
                out.append(Entity(label, int(start), int(end)))
        return out


def _dedupe_spans(ents: list[Entity]) -> list[Entity]:
    """겹치는 스팬은 더 긴 것 하나만 남긴다."""
    chosen: list[Entity] = []
    for e in sorted(ents, key=lambda x: (x.start, -(x.end - x.start))):
        if any(not (e.end <= c.start or e.start >= c.end) for c in chosen):
            continue
        chosen.append(e)
    return chosen
