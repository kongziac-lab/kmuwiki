"""기안문 보일러플레이트 제거 (검색 품질 개선).

모든 전자결재 기안문에 공통으로 들어가는 행정 상용구(학교 표어·수신/경유·협조자·시행·접수
footer)는 문서 간 거의 동일해서, 임베딩에 포함되면 일반 질의에 대해 노이즈로 작용한다.
→ 임베딩·검색용 본문에서 제거한다(메타데이터 추출은 raw 텍스트로 이미 끝난 뒤 호출).

주의: 제목·본문은 절대 건드리지 않는다. 명백한 상용구 패턴만 행 단위로 제거.
"""

from __future__ import annotations

import re

_DROP = [
    # 학교 표어(모든 기안문 첫 줄)
    re.compile(r'^["“”\']?\s*진리와\s*정의와\s*사랑의\s*나라를\s*위하여\s*["“”\']?$'),
    re.compile(r'^수신자?\b'),            # 수신자 내부결재
    re.compile(r'^\(\s*경\s*유\s*\)'),    # (경 유)
    re.compile(r'^협조자\b'),             # 협조자 ○○팀장 …
    re.compile(r'^시행\b'),               # 시행 ○○팀-번호 ( 날짜 ) 접수 ( )
    re.compile(r'^접수\s*\(\s*\)\s*$'),
]


def strip_boilerplate(text: str | None) -> str:
    if not text:
        return text or ""
    kept = [ln for ln in text.splitlines()
            if not any(p.match(ln.strip()) for p in _DROP)]
    return "\n".join(kept).strip()
