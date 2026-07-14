"""이그레스 게이트 (§7.A L3 / 불변식 7).

클라우드(임베딩/LLM)로 텍스트를 보내기 '직전'에 호출한다.
마스킹을 신뢰하지 않고, 고신뢰 PII 패턴으로 재스캔하여 1건이라도 남아 있으면
전송을 차단한다. 차단된 문서는 status=quarantine 으로 격리된다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .regex_rules import HIGH_RULES


class EgressBlocked(Exception):
    """마스킹 후에도 고신뢰 PII가 남아 전송이 차단됨."""

    def __init__(self, findings: list["Finding"] | None = None, *, reason: str | None = None):
        self.findings = findings or []
        if reason:
            super().__init__(f"egress blocked: {reason}")
            return
        labels = ", ".join(sorted({f.label for f in self.findings}))
        super().__init__(f"egress blocked: PII 잔존 ({labels}), {len(self.findings)}건")


@dataclass
class Finding:
    label: str
    span: tuple[int, int]
    sample: str   # 로그용 일부(전체 노출 금지)


def scan(text: str, enforce_labels: set[str] | None = None) -> list[Finding]:
    """고신뢰 PII 잔존 검출. 빈 리스트면 전송 허용.

    enforce_labels: 강제할 라벨 집합(마스킹 정책과 일치시킨다). None이면 전체 high-tier.
    정책상 가리지 않는 라벨(예: 내부결재문의 전화번호)은 차단 대상에서 제외해야
    문서 전체가 격리되는 것을 막는다.
    """
    rules = (HIGH_RULES if enforce_labels is None
             else [r for r in HIGH_RULES if r.label in enforce_labels])
    findings: list[Finding] = []
    for rule in rules:
        for m in rule.pattern.finditer(text):
            s = m.group(0)
            redacted = (s[:2] + "***") if len(s) > 2 else "***"
            findings.append(Finding(rule.label, m.span(), redacted))
    return findings


def assert_clean(text: str, enforce_labels: set[str] | None = None) -> None:
    """PII가 남아 있으면 EgressBlocked 예외. 통과하면 None."""
    findings = scan(text, enforce_labels)
    if findings:
        raise EgressBlocked(findings)
