"""메타데이터 추출 (§7.B / Phase 1 작업 4).

⚠️ 샘플 ZIP 구조 확정 전까지는 파일명/경로 기반 휴리스틱만 사용한다.
   확정되면 전자결재 index/헤더 파서를 여기에 추가하고, 열람권·보안등급을 매핑한다.

deny-by-default(불변식 8): dept/security_level 을 신뢰도 있게 못 채우면 None 으로 둔다.
None 이면 RLS·검색에서 일반 노출되지 않고 관리자 전용으로 격리된다.
"""

from __future__ import annotations

import re
from datetime import date

from .models import FileMeta

# YYYY-MM-DD / YYYYMMDD / YYYY.MM.DD
_DATE = re.compile(r"(20\d{2})[.\-_]?(0[1-9]|1[0-2])[.\-_]?(0[1-9]|[12]\d|3[01])")
# 전자결재 문서번호 예: 제2025-13호 / 제 2025-0013 호
_DOCNO = re.compile(r"제\s*(\d{4}-\d{1,5})\s*호")


def extract_meta(path_in_zip: str, filename: str, text: str | None) -> FileMeta:
    meta = FileMeta(filename=filename, path_in_zip=path_in_zip)

    # 날짜: 파일명 → 경로 → 본문 앞부분 순으로 탐색
    for source in (filename, path_in_zip, (text or "")[:500]):
        m = _DATE.search(source)
        if m:
            try:
                meta.doc_date = date(int(m[1]), int(m[2]), int(m[3]))
                break
            except ValueError:
                continue

    # 문서번호
    for source in (filename, (text or "")[:1000]):
        m = _DOCNO.search(source)
        if m:
            meta.doc_no = f"제{m[1]}호"
            break

    # 부서: ZIP 내 최상위 폴더명을 잠정 후보로(샘플 확정 후 매핑 테이블로 교체).
    #   신뢰도가 낮으므로 '확정 매핑'이 생기기 전에는 dept=None 유지가 더 안전할 수 있다.
    #   여기서는 후보만 담아두고, 실제 부여 여부는 매핑 도입 시 결정한다.
    parts = path_in_zip.replace("\\", "/").split("/")
    if len(parts) > 1 and parts[0]:
        meta.dept = None  # TODO(sample): 부서 매핑 테이블 도입 전까지 deny-by-default

    # 보안등급: 샘플 메타 확정 전까지 미상 → None(관리자 전용 격리)
    meta.security_level = None
    return meta
