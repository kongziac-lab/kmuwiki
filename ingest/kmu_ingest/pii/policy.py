"""마스킹 정책 — '무엇을 PII로 보고 가릴지'의 단일 기준.

마스커(무엇을 가릴지)와 이그레스 게이트(무엇이 남으면 차단할지)가 같은 정책을 공유한다.
정책이 어긋나면(예: 가리지 않는데 게이트가 차단) 모든 문서가 격리되므로 한 곳에서 관리.

내부결재문 기본 정책(decision):
  직원이 업무상 등장하는 성명·전화번호·주소는 식별 메타데이터로 보고 '보존'한다.
  (업무흐름도·담당자 조회 등 활용을 위해 필요)
  반면 주민등록번호·계좌·카드·여권/면허·이메일은 유출 위험이 커 계속 마스킹한다.

  ⚠️ 민원·학생 등 '제3자' 정보가 섞인 문서 카테고리는 성명/주소를 다시 켜야 한다
     (KMU_MASK_LABELS 로 재정의). 이 정책은 그 전환을 위한 토글이다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .regex_rules import HIGH_RULES

ALL_LABELS = frozenset({
    "주민등록번호", "카드번호", "전화번호", "이메일", "계좌번호",
    "여권번호", "운전면허번호", "성명", "주소", "기관",
})

# 내부결재문 기본: 성명·전화번호·주소·기관 제외
DEFAULT_INTERNAL_LABELS = ALL_LABELS - frozenset({"성명", "전화번호", "주소", "기관"})

# NER 토큰 ↔ 정책 라벨 매핑
_NER_MAP = {"성명": "PER", "주소": "LOC", "기관": "ORG"}


@dataclass(frozen=True)
class MaskPolicy:
    labels: frozenset[str]

    @classmethod
    def internal(cls) -> "MaskPolicy":
        return cls(DEFAULT_INTERNAL_LABELS)

    @classmethod
    def all(cls) -> "MaskPolicy":
        return cls(ALL_LABELS)

    def masks(self, label: str) -> bool:
        return label in self.labels

    @property
    def ner_labels(self) -> set[str]:
        """이 정책이 NER로 가려야 하는 엔티티(PER/LOC/ORG). 비면 NER 불필요."""
        return {_NER_MAP[l] for l in ("성명", "주소", "기관") if l in self.labels}

    def enforced_high(self) -> set[str]:
        """이그레스 게이트가 강제할 고신뢰 라벨(정책 ∩ high-tier)."""
        return {r.label for r in HIGH_RULES if r.label in self.labels}


def load_policy() -> MaskPolicy:
    """KMU_MASK_LABELS 로 재정의. 비어있으면 내부결재문 기본. 'all'이면 전체.

    예: KMU_MASK_LABELS="주민등록번호,계좌번호,이메일,성명,주소"  (민원 문서용)
    """
    raw = os.environ.get("KMU_MASK_LABELS", "").strip()
    if not raw:
        return MaskPolicy.internal()
    if raw.lower() == "all":
        return MaskPolicy.all()
    return MaskPolicy(frozenset(x.strip() for x in raw.split(",") if x.strip()))
