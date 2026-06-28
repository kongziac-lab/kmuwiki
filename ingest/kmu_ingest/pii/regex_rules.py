"""정형 PII 정규식 규칙 (§7.A L1).

tier:
  - "high"    : 이그레스 게이트가 강제하는 고신뢰 패턴(주민번호·전화·이메일·카드).
                마스킹 후 이 패턴이 남아 있으면 전송 차단(quarantine).
  - "context" : 마스킹은 하되 게이트는 강제하지 않는 패턴(오탐 가능성↑인 계좌·여권 등).

stdlib re 만 사용 → 모델/네트워크 없이 결정적으로 동작·테스트 가능.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    label: str          # 마스킹 토큰명 (예: 주민등록번호)
    pattern: re.Pattern[str]
    tier: str           # "high" | "context"
    repl: str | None = None  # 치환 템플릿(백레퍼런스 가능). None이면 "[label]" 전체 치환.


# 주의: 한국어 PII. 마스킹 측은 재현율 우선(놓치면 유출이므로 다소 공격적).
RULES: list[Rule] = [
    # 주민등록번호 / 외국인등록번호: 6자리 - [1-8] + 6자리
    Rule("주민등록번호",
         re.compile(r"(?<!\d)\d{6}[-\s]?[1-8]\d{6}(?!\d)"),
         "high"),
    # 신용/체크카드: 4-4-4-4
    Rule("카드번호",
         re.compile(r"(?<!\d)\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}(?!\d)"),
         "high"),
    # 휴대전화
    Rule("전화번호",
         re.compile(r"(?<!\d)01[016789][-\s]?\d{3,4}[-\s]?\d{4}(?!\d)"),
         "high"),
    # 일반전화(지역번호 02 / 0XX)
    Rule("전화번호",
         re.compile(r"(?<!\d)0(?:2|[3-6]\d)[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)"),
         "high"),
    # 이메일
    Rule("이메일",
         re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
         "high"),
    # 계좌번호: 은행별 형식이 제각각이라 '숫자 패턴'만으로는 날짜·문서번호와 충돌한다.
    # → 은행/계좌 키워드가 인접한 경우에만 마스킹(키워드는 보존). (eval 하네스로 검증된 결정)
    Rule("계좌번호",
         re.compile(
             r"(?P<kw>계좌번호|계좌|입금|예금주|은행)"
             r"(?P<gap>[^\d\n]{0,10})"
             r"(?P<num>\d{2,6}[-\s]\d{2,6}(?:[-\s]\d{1,6}){0,2})"
         ),
         "context",
         repl=r"\g<kw>\g<gap>[계좌번호]"),
    # 여권번호: 영문 1~2 + 숫자 7~8
    Rule("여권번호",
         re.compile(r"\b[A-Z]{1,2}\d{7,8}\b"),
         "context"),
    # 운전면허번호
    Rule("운전면허번호",
         re.compile(r"(?<!\d)\d{2}-?\d{2}-?\d{6}-?\d{2}(?!\d)"),
         "context"),
]

HIGH_RULES: list[Rule] = [r for r in RULES if r.tier == "high"]
