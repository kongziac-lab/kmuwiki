"""마스킹 (§7.A) — 정책(MaskPolicy)에 따라 무엇을 가릴지 결정.

레이어:
  L1 정규식  : 정책에 포함된 라벨만 치환(주민번호/카드/계좌/이메일 등).
  L2 NER     : 정책이 성명/주소/기관을 가리도록 설정된 경우에만 동작.
               내부결재문 기본 정책은 성명·주소를 보존하므로 NER 불필요(비활성).

마스킹 토큰은 [라벨] 형태(예: [주민등록번호]).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .policy import MaskPolicy, load_policy
from .regex_rules import RULES


@dataclass
class MaskResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)
    ner_available: bool = False


class Masker:
    def __init__(
        self,
        enable_ner: bool = True,
        high_risk: bool = False,
        ner=None,
        ner_model: str | None = None,
        policy: MaskPolicy | None = None,
    ):
        """policy: 무엇을 PII로 보고 가릴지. None이면 환경설정(내부결재문 기본).

        ner: 미리 만든 KoreanNER 주입(테스트/대체 백엔드).
        NER은 policy가 성명/주소/기관을 가리도록 설정된 경우에만 실제로 동작한다.
        """
        self.high_risk = high_risk
        self._ner_model = ner_model
        self.policy = policy or load_policy()

        ner_labels = self.policy.ner_labels
        if not enable_ner or not ner_labels:
            self._ner = None                       # 정책상 NER 불필요 → 비활성
        elif ner is not None:
            ner.mask_labels = ner_labels
            self._ner = ner
        else:
            self._ner = self._load_ner(ner_labels)

    def mask(self, text: str) -> MaskResult:
        counts: dict[str, int] = {}

        # L1 정규식 (정책 포함 라벨만)
        for rule in RULES:
            if not self.policy.masks(rule.label):
                continue
            text, n = rule.pattern.subn(rule.repl or f"[{rule.label}]", text)
            if n:
                counts[rule.label] = counts.get(rule.label, 0) + n

        # L2 NER (정책이 요구할 때만)
        ner_available = self._ner is not None
        if self._ner is not None:
            text, ner_counts = self._ner.mask(text)
            for k, v in ner_counts.items():
                counts[k] = counts.get(k, 0) + v

        return MaskResult(text=text, counts=counts, ner_available=ner_available)

    def high_risk_copy(self) -> "Masker":
        """OCR 등 고위험 본문용: 정형 PII 전체를 마스킹한다."""
        return Masker(
            enable_ner=self._ner is not None,
            high_risk=True,
            ner=self._ner,
            ner_model=self._ner_model,
            policy=MaskPolicy.all(),
        )

    # ── NER 백엔드 (lazy, optional) ────────────────────────────────
    def _load_ner(self, ner_labels: set[str]):
        """한국어 NER 백엔드 로드. 백엔드/모델이 없으면 None(비활성).

        ensure()가 False면 None 을 반환해 ner_available=False 로 드러낸다
        (이름 마스킹 미작동을 조용히 숨기지 않는다).
        """
        from .ner import KoreanNER

        ner = KoreanNER(model=self._ner_model, mask_org=("ORG" in ner_labels))
        ner.mask_labels = ner_labels
        return ner if ner.ensure() else None
