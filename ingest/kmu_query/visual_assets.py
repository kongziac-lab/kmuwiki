"""RLS-authenticated loading of redacted visual derivatives.

Search rows already passed document/search-unit RLS.  Asset bytes are fetched
with the same end-user JWT, so the private Storage policy independently checks
access again.  Raw source images are never addressable here.
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from urllib.parse import quote

from .retriever import Source


ALLOWED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}


@dataclass(frozen=True)
class VisualInput:
    data: bytes
    media_type: str
    label: str
    document_id: str
    asset_id: str | None = None
    page_no: int | None = None


def load_visual_inputs(
    sources: list[Source],
    *,
    supabase_url: str,
    anon_key: str,
    user_jwt: str,
    bucket: str,
    max_images: int = 4,
    max_total_bytes: int = 8 * 1024 * 1024,
    max_image_bytes: int = 4 * 1024 * 1024,
    timeout: float = 15.0,
) -> list[VisualInput]:
    """Load a small, deduplicated visual context; inaccessible assets fail soft."""
    output: list[VisualInput] = []
    seen: set[str] = set()
    total = 0
    for source in sources:
        path = _validated_path(source)
        if not path or path in seen or len(output) >= max_images:
            continue
        seen.add(path)
        try:
            url = (
                f"{supabase_url.rstrip('/')}/storage/v1/object/authenticated/"
                f"{quote(bucket, safe='')}/{quote(path, safe='/')}"
            )
            request = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {user_jwt}",
                "apikey": anon_key,
                "Accept": "image/png,image/jpeg,image/webp",
            })
            with urllib.request.urlopen(request, timeout=timeout) as response:
                media_type = str(response.headers.get_content_type()).lower()
                if media_type not in ALLOWED_MEDIA_TYPES:
                    continue
                payload = response.read(max_image_bytes + 1)
            if not payload or len(payload) > max_image_bytes:
                continue
            if total + len(payload) > max_total_bytes:
                break
            output.append(VisualInput(
                data=payload,
                media_type=media_type,
                label=_visual_label(source),
                document_id=source.document_id,
                asset_id=source.asset_id,
                page_no=source.page_no,
            ))
            total += len(payload)
        except Exception:
            # Text surrogate remains available; a Storage outage must not turn
            # a safe text answer into a 500 response.
            continue
    return output


def _validated_path(source: Source) -> str | None:
    path = (source.storage_path or "").strip().lstrip("/")
    if not path or "\\" in path or ".." in path.split("/"):
        return None
    # Ingest writes every derivative below its immutable document UUID.
    if path.split("/", 1)[0] != source.document_id:
        return None
    if source.modality not in {"image", "mixed"}:
        return None
    return path


def _visual_label(source: Source) -> str:
    bits = [source.label()]
    if source.page_no:
        bits.append(f"p.{source.page_no}")
    if source.asset_type:
        bits.append(source.asset_type)
    return " · ".join(bits)
