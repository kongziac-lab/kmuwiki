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

    section_xml = _section_xml(
        title=clean_title,
        body_lines=body_lines,
        source_label=source_label or "검토 필요",
        approval_form_plan=plan,
    )

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        _write_stored(zf, "mimetype", HWPX_MIME.encode("utf-8"))
        _write_stored(zf, "version.xml", _version_xml().encode("utf-8"))
        _write_stored(zf, "Contents/header.xml", _header_xml().encode("utf-8"))
        _write_stored(zf, "Contents/section0.xml", section_xml.encode("utf-8"))
        _write_stored(zf, "Preview/PrvText.txt", "\n".join(preview_lines).encode("utf-8"))
        _write_stored(zf, "settings.xml", _settings_xml().encode("utf-8"))
        _write_deflated(zf, "META-INF/container.rdf", _container_rdf().encode("utf-8"))
        _write_deflated(zf, "Contents/content.hpf", _content_hpf(clean_title).encode("utf-8"))
        _write_deflated(zf, "META-INF/container.xml", _container_xml().encode("utf-8"))
        _write_deflated(zf, "META-INF/manifest.xml", _manifest_xml().encode("utf-8"))
    return out.getvalue()


def safe_hwpx_filename(title: str) -> str:
    filename = title.strip().split("/")[-1].split("\\")[-1]
    filename = re.sub(r"[\\/:*?\"<>|]+", "", filename).strip()
    filename = re.sub(r"\.[^.]+$", "", filename)
    filename = filename.strip(". ") or "draft"
    return f"{filename}.hwpx"


# 업로드 HWPX 템플릿 방어 한도(zip 폭탄·과대 입력 차단). 실제 템플릿은 수 MB 이하.
_MAX_TEMPLATE_BYTES = 20 * 1024 * 1024        # 압축(입력) 상한 20MB
_MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024   # 전체 해제 상한 100MB
_MAX_ENTRIES = 2000                            # zip 항목 수 상한
_MAX_ENTRY_BYTES = 20 * 1024 * 1024            # 단일 항목 메모리 상한
_MAX_COMPRESSION_RATIO = 200
_READ_CHUNK_BYTES = 1024 * 1024


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
    if len(template_data) > _MAX_TEMPLATE_BYTES:
        raise ValueError(f"HWPX 템플릿이 너무 큽니다(> {_MAX_TEMPLATE_BYTES} bytes)")

    lines = _template_lines(title=title, body=body)
    source = io.BytesIO(template_data)
    out = io.BytesIO()
    with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(out, "w") as zout:
        infos = zin.infolist()
        if len(infos) > _MAX_ENTRIES:
            raise ValueError(f"HWPX 템플릿 항목 수 초과(> {_MAX_ENTRIES})")
        if sum(i.file_size for i in infos) > _MAX_UNCOMPRESSED_BYTES:
            raise ValueError("HWPX 템플릿 해제 크기 초과(zip 폭탄 의심)")
        if any(i.file_size > _MAX_ENTRY_BYTES for i in infos):
            raise ValueError("HWPX 템플릿 단일 항목 크기 초과")
        if any(
            i.file_size > 0
            and i.file_size / max(1, i.compress_size) > _MAX_COMPRESSION_RATIO
            for i in infos
        ):
            raise ValueError("HWPX 템플릿 압축률 초과(zip 폭탄 의심)")
        section_names = _section_names(zin)
        remaining = list(lines)
        for original_info in infos:
            data = _read_template_entry(zin, original_info)
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


def _read_template_entry(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    output = bytearray()
    with zf.open(info) as stream:
        while chunk := stream.read(_READ_CHUNK_BYTES):
            output.extend(chunk)
            if len(output) > _MAX_ENTRY_BYTES:
                raise ValueError("HWPX 템플릿 단일 항목 크기 초과")
    return bytes(output)


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


def _write_stored(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
    zf.writestr(name, data, compress_type=zipfile.ZIP_STORED)


def _write_deflated(zf: zipfile.ZipFile, name: str, data: bytes) -> None:
    zf.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)


def _version_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="1" buildNumber="0" os="1" xmlVersion="1.5" application="Hancom Office Hangul"/>
"""


def _settings_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<ha:settings xmlns:ha="http://www.hancom.co.kr/hwpml/2011/app">
  <ha:caretPosition listIDRef="0" paraIDRef="0" pos="0"/>
</ha:settings>
"""


def _container_rdf() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:pkg="http://www.idpf.org/2007/opf"
         xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:container">
  <rdf:Description rdf:about="Contents/content.hpf">
    <pkg:hasRootfile rdf:resource="Contents/content.hpf"/>
  </rdf:Description>
</rdf:RDF>
"""


def _container_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles>
    <rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>
  </rootfiles>
</container>
"""


def _manifest_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest" manifest:version="1.2">
  <manifest:file-entry manifest:full-path="/" manifest:media-type="{HWPX_MIME}"/>
  <manifest:file-entry manifest:full-path="mimetype" manifest:media-type="text/plain"/>
  <manifest:file-entry manifest:full-path="version.xml" manifest:media-type="application/xml"/>
  <manifest:file-entry manifest:full-path="settings.xml" manifest:media-type="application/xml"/>
  <manifest:file-entry manifest:full-path="Contents/content.hpf" manifest:media-type="application/hwpml-package+xml"/>
  <manifest:file-entry manifest:full-path="Contents/header.xml" manifest:media-type="application/xml"/>
  <manifest:file-entry manifest:full-path="Contents/section0.xml" manifest:media-type="application/xml"/>
  <manifest:file-entry manifest:full-path="Preview/PrvText.txt" manifest:media-type="text/plain"/>
  <manifest:file-entry manifest:full-path="META-INF/container.xml" manifest:media-type="application/xml"/>
  <manifest:file-entry manifest:full-path="META-INF/container.rdf" manifest:media-type="application/rdf+xml"/>
</manifest:manifest>
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
    <hpf:item id="version" href="../version.xml" media-type="application/xml"/>
    <hpf:item id="settings" href="../settings.xml" media-type="application/xml"/>
    <hpf:item id="header" href="header.xml" media-type="application/xml"/>
    <hpf:item id="section0" href="section0.xml" media-type="application/xml"/>
    <hpf:item id="previewText" href="../Preview/PrvText.txt" media-type="text/plain"/>
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
