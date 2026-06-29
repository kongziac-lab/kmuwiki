"""메타데이터 추출 (§7.B).

실제 전자결재 기안문(PDF) 텍스트/좌표 구조에서 추출:
  - 제목   : "제 목 <...>"
  - 시행 부서/문서번호 : "시행 <부서명>-<번호> ( YYYY.MM.DD. )"  ← 권한의 권위 있는 출처
  - 시행일 : 위 괄호 안 날짜

중요(실데이터 교훈): 부서명은 공백을 포함할 수 있고(예: "장춘대학 계명학원 행정팀"),
긴 부서명은 표 셀에서 줄바꿈되어 번호가 다음 줄로 내려간다. 따라서 PDF는 단어 좌표로
시행란을 복원해 번호를 안정적으로 추출한다(_docno_from_words).

ZIP=결재 1건이므로 본문 기안문에서 한 번 추출해 같은 ZIP의 모든 파일에 상속한다.
deny-by-default(불변식 8): 추출 실패 시 dept=None → 관리자 전용.
"""

from __future__ import annotations

import re
from datetime import date

from .models import FileMeta

RE_TITLE = re.compile(r"제\s*목\s+(.+)")
# 다단어 부서명 허용(공백 포함). 텍스트가 인접한 경우용(비-PDF/단순 케이스).
RE_SIHAENG_NO = re.compile(
    r"시행\s+([가-힣][가-힣A-Za-z0-9 ]*?(?:팀|처|과|부|원|실|단|관|위원회))\s*-\s*(\d+)")
RE_SIHAENG_DATE = re.compile(r"시행[^()]*\(\s*(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*\)")
RE_ANYDATE = re.compile(r"(20\d{2})[.\-]\s?(0?[1-9]|1[0-2])[.\-]\s?(0?[1-9]|[12]\d|3[01])")
# 부서-번호(줄바꿈 분리 가능). 단어 좌표 복원 후 적용.
_DOCNO = re.compile(r"([가-힣][가-힣A-Za-z0-9 ]*?(?:팀|처|과|부|원|실|단|관|위원회))\s*-\s*(\d+)")


def _docno_from_words(words: list[dict]) -> tuple[str, str] | None:
    """PDF 단어 좌표로 시행란의 부서-번호를 복원.

    words: pdfplumber extract_words() 결과(각 {'text','x0','x1','top'}).
    '시행' 단어 오른쪽 ~ 날짜 '(' 왼쪽, 같은 y밴드의 단어들을 모아 부서-번호를 잇는다
    (셀 줄바꿈으로 번호가 아래로 내려간 경우 포함).
    """
    si = [w for w in words if w["text"] == "시행"]
    if not si:
        return None
    si = si[-1]
    date_x = None
    for w in sorted(words, key=lambda w: w["x0"]):
        if w["x0"] > si["x1"] and abs(w["top"] - si["top"]) < 8 and w["text"].startswith("("):
            date_x = w["x0"]
            break
    band = [w for w in words
            if w["x0"] > si["x1"] - 2
            and (date_x is None or w["x0"] < date_x - 2)
            and -18 < (w["top"] - si["top"]) < 30
            and w["text"] not in ("접수", "(", ")")]
    band.sort(key=lambda w: (round(w["top"]), w["x0"]))
    m = _DOCNO.search(" ".join(w["text"] for w in band))
    return (m.group(1).strip(), m.group(2)) if m else None


def extract_pdf_fields(pdf_bytes: bytes) -> dict:
    """기안문 PDF → {title, dept, doc_no, doc_date}. 번호는 좌표 기반 복원."""
    import io

    import pdfplumber

    fields: dict = {"title": None, "dept": None, "doc_no": None, "doc_date": None}
    texts: list[str] = []
    docno = None
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            texts.append(page.extract_text() or "")
            docno = _docno_from_words(page.extract_words()) or docno
    text = "\n".join(texts)

    m = RE_TITLE.search(text)
    if m:
        fields["title"] = m.group(1).strip()[:200]
    if docno:
        fields["dept"] = docno[0]
        fields["doc_no"] = f"{docno[0]}-{docno[1]}"
    m = RE_SIHAENG_DATE.search(text) or RE_ANYDATE.search(text)
    if m:
        try:
            fields["doc_date"] = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return fields


def extract_doc_fields(text: str | None) -> dict:
    """텍스트 기반 추출(비-PDF/단순 케이스 fallback). 줄바꿈 분리 번호는 못 잡을 수 있음."""
    fields: dict = {"title": None, "dept": None, "doc_no": None, "doc_date": None}
    if not text:
        return fields
    m = RE_TITLE.search(text)
    if m:
        fields["title"] = m.group(1).strip()[:200]
    m = RE_SIHAENG_NO.search(text)
    if m:
        fields["dept"] = m.group(1).strip()
        fields["doc_no"] = f"{m.group(1).strip()}-{m.group(2)}"
    m = RE_SIHAENG_DATE.search(text) or RE_ANYDATE.search(text)
    if m:
        try:
            fields["doc_date"] = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return fields


_ATTACH = re.compile(r"^\[?\s*붙임")


def _is_attachment(filename: str) -> bool:
    """'붙임 N.' / '[붙임 N]' 으로 시작하면 첨부 → 본문 기안문 번호를 상속."""
    base = filename.replace("\\", "/").split("/")[-1]
    return _ATTACH.match(base) is not None


def resolve_file_fields(filename: str, data: bytes, text: str | None,
                        zip_fields: dict | None) -> dict:
    """파일별 시행번호 해석(§7.B 개선).

    - 붙임(attachment): 본문 기안문 번호를 상속(zip_fields).
    - 그 외 PDF: 자기 좌표 기반 시행번호가 있으면 그걸 사용(참조 문서가 호스트 번호를
      잘못 상속받는 문제 해결).
    - 그 외 비-PDF(mht/hwp 등): 추출 텍스트에 시행번호가 인라인으로 있으면 자기 번호 사용.
    - 어느 것도 없으면 상속.
    """
    if _is_attachment(filename):
        return zip_fields or {}

    own: dict | None = None
    if data and filename.lower().endswith(".pdf"):
        try:
            own = extract_pdf_fields(data)
        except Exception:
            own = None
    if not (own and own.get("doc_no")) and text:
        t = extract_doc_fields(text)
        if t.get("doc_no"):
            own = t

    if own and own.get("doc_no"):
        return own
    return zip_fields or {}


def build_file_meta(filename: str, path_in_zip: str, mime: str | None,
                    zip_fields: dict | None) -> FileMeta:
    """ZIP 단위 메타(zip_fields)를 파일 메타로 상속. security_level은 항상 None(미상=관리자 전용)."""
    zf = zip_fields or {}
    return FileMeta(
        filename=filename,
        path_in_zip=path_in_zip,
        mime_type=mime,
        dept=zf.get("dept"),
        security_level=None,
        doc_no=zf.get("doc_no"),
        doc_date=zf.get("doc_date"),
    )
