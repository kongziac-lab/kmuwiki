"""HWPX export helpers for Hermes drafts."""

from __future__ import annotations

import io
import re
import zipfile
from xml.sax.saxutils import escape


HWPX_MIME = "application/hwp+zip"


def build_approval_hwpx(
    *,
    title: str,
    body: str,
    source_label: str = "",
    approval_form_plan: list[str] | None = None,
) -> bytes:
    clean_title = _strip_hwpx_extension(safe_hwpx_filename(title))
    plan = approval_form_plan or []
    body_lines = _body_lines(body)
    preview_lines = [
        "전자결재 문서 초안",
        clean_title,
        f"원문근거: {source_label or '검토 필요'}",
        "",
        *body_lines,
        "",
        "생성 기준",
        *(plan or ["사람 검토 필요"]),
    ]

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("mimetype", HWPX_MIME, compress_type=zipfile.ZIP_STORED)
        zf.writestr("version.xml", _version_xml())
        zf.writestr("META-INF/container.xml", _container_xml())
        zf.writestr("Contents/content.hpf", _content_hpf(clean_title))
        zf.writestr("Contents/header.xml", _header_xml())
        zf.writestr(
            "Contents/section0.xml",
            _section_xml(
                title=clean_title,
                body_lines=body_lines,
                source_label=source_label or "검토 필요",
                approval_form_plan=plan,
            ),
        )
        zf.writestr("Preview/PrvText.txt", "\n".join(preview_lines))
    return out.getvalue()


def safe_hwpx_filename(title: str) -> str:
    filename = title.strip().split("/")[-1].split("\\")[-1]
    filename = re.sub(r"[\\/:*?\"<>|]+", "", filename).strip()
    filename = re.sub(r"\.[^.]+$", "", filename)
    filename = filename.strip(". ") or "draft"
    return f"{filename}.hwpx"


def _version_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<hv:version xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" version="1.0"/>
"""


def _container_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>
  </rootfiles>
</container>
"""


def _content_hpf(title: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<hpf:package xmlns:hpf="http://www.hancom.co.kr/hwpml/2011/hpf" version="1.0">
  <hpf:metadata>
    <hpf:title>{_xml(title)}</hpf:title>
    <hpf:creator>KMU Wiki</hpf:creator>
    <hpf:subject>전자결재 문서 초안</hpf:subject>
  </hpf:metadata>
  <hpf:manifest>
    <hpf:item id="header" href="header.xml" media-type="application/xml"/>
    <hpf:item id="section0" href="section0.xml" media-type="application/xml"/>
  </hpf:manifest>
  <hpf:spine>
    <hpf:itemref idref="section0"/>
  </hpf:spine>
</hpf:package>
"""


def _header_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" version="1.0">
  <hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>
  <hh:refList>
    <hh:fontfaces itemCnt="1">
      <hh:fontface lang="HANGUL" fontCnt="1">
        <hh:font id="0" face="맑은 고딕" type="TTF"/>
      </hh:fontface>
    </hh:fontfaces>
    <hh:charProperties itemCnt="3">
      <hh:charPr id="0" height="1050" textColor="#000000"/>
      <hh:charPr id="1" height="1600" textColor="#000000" bold="1"/>
      <hh:charPr id="2" height="1200" textColor="#000000" bold="1"/>
    </hh:charProperties>
    <hh:paraProperties itemCnt="3">
      <hh:paraPr id="0" align="LEFT" lineSpacing="160"/>
      <hh:paraPr id="1" align="CENTER" lineSpacing="180"/>
      <hh:paraPr id="2" align="LEFT" lineSpacing="150"/>
    </hh:paraProperties>
    <hh:styles itemCnt="1">
      <hh:style id="0" type="PARA" name="바탕글" engName="Normal" paraPrIDRef="0" charPrIDRef="0" nextStyleIDRef="0"/>
    </hh:styles>
  </hh:refList>
</hh:head>
"""


def _section_xml(
    *,
    title: str,
    body_lines: list[str],
    source_label: str,
    approval_form_plan: list[str],
) -> str:
    paragraphs = [
        _paragraph("전자결재 문서 초안", para_pr_id=1, char_pr_id=1),
        _paragraph(title, para_pr_id=1, char_pr_id=2),
        _paragraph(f"문서제목: {title}"),
        _paragraph(f"원문근거: {source_label}"),
        _paragraph("생성상태: draft / 사람 검토 필요"),
        _paragraph("출력형식: HWPX 전자결재 결재문 형식"),
        _paragraph("본문", char_pr_id=2),
        *(_paragraph(line) for line in body_lines),
    ]
    if approval_form_plan:
        paragraphs.append(_paragraph("생성 기준", char_pr_id=2))
        paragraphs.extend(_paragraph(f"- {item}") for item in approval_form_plan)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<hp:sec xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  {''.join(paragraphs)}
</hp:sec>
"""


def _paragraph(text: str, para_pr_id: int = 0, char_pr_id: int = 0) -> str:
    return (
        f'<hp:p paraPrIDRef="{para_pr_id}" styleIDRef="0">'
        f'<hp:run charPrIDRef="{char_pr_id}"><hp:t>{_xml(text)}</hp:t></hp:run>'
        "</hp:p>"
    )


def _body_lines(body: str) -> list[str]:
    lines = [line.strip() for line in body.splitlines()]
    return [line for line in lines if line] or ["본문 초안 없음"]


def _strip_hwpx_extension(filename: str) -> str:
    return re.sub(r"\.hwpx$", "", filename, flags=re.IGNORECASE)


def _xml(text: str) -> str:
    return escape(text, {'"': "&quot;"})
