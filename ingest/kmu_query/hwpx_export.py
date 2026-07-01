"""HWPX export helpers for Hermes drafts."""

from __future__ import annotations

import io
import re
import zipfile
from base64 import b64decode
from xml.sax.saxutils import escape


HWPX_MIME = "application/hwp+zip"
_TEXT_NODE_RE = re.compile(r"(<hp:t\b[^>]*>)(.*?)(</hp:t>)", re.DOTALL)


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


def fill_template_hwpx(
    *,
    template_data: bytes,
    title: str,
    body: str,
) -> bytes:
    """Fill an uploaded HWPX template while preserving package metadata.

    Version 1 intentionally performs conservative text-node replacement: it
    keeps all XML structure, styles, tables, and ZIP entry metadata, and only
    rewrites existing ``<hp:t>`` text nodes in section XML files.
    """

    lines = _template_lines(title=title, body=body)
    source = io.BytesIO(template_data)
    out = io.BytesIO()
    with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(out, "w") as zout:
        section_names = _section_names(zin)
        remaining = list(lines)
        for original_info in zin.infolist():
            data = zin.read(original_info.filename)
            if original_info.filename in section_names:
                text = data.decode("utf-8")
                text, remaining = _replace_text_nodes(text, remaining)
                data = text.encode("utf-8")
            elif original_info.filename == "Preview/PrvText.txt":
                data = "\n".join(lines).encode("utf-8")
            elif original_info.filename == "Contents/content.hpf":
                data = _replace_package_title(data, title)
            zout.writestr(_copy_zip_info(original_info), data)
    return out.getvalue()


def fill_template_hwpx_from_base64(
    *,
    template_base64: str,
    title: str,
    body: str,
) -> bytes:
    return fill_template_hwpx(
        template_data=b64decode(template_base64),
        title=title,
        body=body,
    )


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


def _template_lines(*, title: str, body: str) -> list[str]:
    return [_strip_hwpx_extension(safe_hwpx_filename(title)), *_body_lines(body)]


def _section_names(zf: zipfile.ZipFile) -> set[str]:
    return {
        name
        for name in zf.namelist()
        if name.startswith("Contents/section") and name.endswith(".xml")
    }


def _replace_text_nodes(section_xml: str, lines: list[str]) -> tuple[str, list[str]]:
    cursor = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal cursor
        replacement = lines[cursor] if cursor < len(lines) else ""
        cursor += 1
        return f"{match.group(1)}{_xml(replacement)}{match.group(3)}"

    return _TEXT_NODE_RE.sub(repl, section_xml), lines[cursor:]


def _replace_package_title(data: bytes, title: str) -> bytes:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    title_text = _strip_hwpx_extension(safe_hwpx_filename(title))
    text = re.sub(
        r"(<hpf:title\b[^>]*>)(.*?)(</hpf:title>)",
        lambda match: f"{match.group(1)}{_xml(title_text)}{match.group(3)}",
        text,
        count=1,
        flags=re.DOTALL,
    )
    return text.encode("utf-8")


def _copy_zip_info(original: zipfile.ZipInfo) -> zipfile.ZipInfo:
    copied = zipfile.ZipInfo(original.filename, date_time=original.date_time)
    copied.compress_type = original.compress_type
    copied.comment = original.comment
    copied.extra = original.extra
    copied.internal_attr = original.internal_attr
    copied.external_attr = original.external_attr
    copied.create_system = original.create_system
    copied.flag_bits = original.flag_bits
    return copied


def _strip_hwpx_extension(filename: str) -> str:
    return re.sub(r"\.hwpx$", "", filename, flags=re.IGNORECASE)


def _xml(text: str) -> str:
    return escape(text, {'"': "&quot;"})
