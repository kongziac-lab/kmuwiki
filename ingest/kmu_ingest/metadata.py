"""메타데이터 추출 (§7.B).

실제 전자결재 기안문(PDF) 텍스트 구조에서 추출:
  - 제목   : "제 목 <...>"
  - 시행부서/문서번호 : "시행 <부서명>-<번호> ( YYYY.MM.DD. )"   ← 권한의 권위 있는 출처
  - 시행일 : 위 괄호 안 날짜

ZIP=결재 1건이므로, 본문 기안문에서 한 번 추출해 같은 ZIP의 모든 파일에 상속한다.

deny-by-default(불변식 8): dept는 '시행 부서-번호'가 있을 때만 채운다.
본문이 참조한 다른 문서의 부서(예: 관련: ○○팀-123)는 이 문서의 기안 부서가 아닐 수 있어
권한 산정에 쓰지 않는다(과다 노출 방지). 없으면 dept=None → 관리자 전용.
"""

from __future__ import annotations

import re
from datetime import date

from .models import FileMeta

RE_TITLE = re.compile(r"제\s*목\s+(.+)")
# 시행 <부서>-<번호> : 부서는 팀/처/과/부/원/실/단/관/위원회 등으로 끝남
RE_SIHAENG_NO = re.compile(r"시행\s+([가-힣A-Za-z0-9]+(?:팀|처|과|부|원|실|단|관|위원회))-(\d+)")
RE_SIHAENG_DATE = re.compile(r"시행[^()]*\(\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*\)")
RE_ANYDATE = re.compile(r"(20\d{2})[.\-]\s?(0?[1-9]|1[0-2])[.\-]\s?(0?[1-9]|[12]\d|3[01])")


def extract_doc_fields(text: str | None) -> dict:
    """기안문 텍스트 → {title, dept, doc_no, doc_date}. ZIP 단위로 1회 호출."""
    fields: dict = {"title": None, "dept": None, "doc_no": None, "doc_date": None}
    if not text:
        return fields

    m = RE_TITLE.search(text)
    if m:
        fields["title"] = m.group(1).strip()[:200]

    # 권위 있는 부서·문서번호: 시행 부서-번호 (없으면 null → deny-by-default)
    m = RE_SIHAENG_NO.search(text)
    if m:
        fields["dept"] = m.group(1)
        fields["doc_no"] = f"{m.group(1)}-{m.group(2)}"

    # 시행일자 (없으면 본문 첫 날짜로 약한 fallback)
    m = RE_SIHAENG_DATE.search(text) or RE_ANYDATE.search(text)
    if m:
        try:
            fields["doc_date"] = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return fields


def build_file_meta(filename: str, path_in_zip: str, mime: str | None,
                    zip_fields: dict | None) -> FileMeta:
    """ZIP 단위 메타(zip_fields)를 파일 메타로 상속. security_level은 항상 None(미상=관리자 전용)."""
    zf = zip_fields or {}
    return FileMeta(
        filename=filename,
        path_in_zip=path_in_zip,
        mime_type=mime,
        dept=zf.get("dept"),            # 시행 부서-번호 있을 때만 채워짐
        security_level=None,            # 보안등급 메타 부재 → deny-by-default
        doc_no=zf.get("doc_no"),
        doc_date=zf.get("doc_date"),
    )
