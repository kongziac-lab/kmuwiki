"""Local document-layout extraction for multimodal v2.

PP-StructureV3 runs before any external egress.  It contributes masked
Markdown plus bounded table/chart crops; source page images remain local and
still have to pass :class:`VisualSanitizer` before they can be embedded or
stored.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

from .models import ParsedAsset


@dataclass(frozen=True)
class LayoutAnalysis:
    markdown: str = ""
    assets: list[ParsedAsset] = field(default_factory=list)
    succeeded: bool = True
    error: str | None = None


class LayoutAnalyzer:
    """Lazy, fail-soft wrapper around PaddleOCR ``PPStructureV3``."""

    def __init__(self, backend: str = "none"):
        self.backend = backend
        self._pipeline = None
        self.available = backend != "none"
        self.last_error: str | None = None

    def _ensure(self) -> None:
        if self._pipeline is not None or not self.available:
            return
        if self.backend != "ppstructure":
            self.available = False
            return
        from paddleocr import PPStructureV3  # lazy: visual worker only

        self._pipeline = PPStructureV3()

    def ensure_available(self) -> bool:
        try:
            self._ensure()
        except Exception as exc:
            self.available = False
            self.last_error = f"{type(exc).__name__}: {exc}"
        return self.available and self._pipeline is not None

    def analyze(self, image_bytes: bytes, *, page_no: int | None = None) -> LayoutAnalysis:
        if not self.ensure_available():
            return LayoutAnalysis(succeeded=False, error=self.last_error or "layout unavailable")
        try:
            import numpy as np
            from PIL import Image

            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            results = list(self._pipeline.predict(np.asarray(image)) or [])
            markdown = _collect_markdown(results)
            assets = _collect_regions(results, image, page_no=page_no)
            return LayoutAnalysis(markdown=markdown, assets=assets)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return LayoutAnalysis(succeeded=False, error=self.last_error)


def _collect_markdown(results: list[Any]) -> str:
    values: list[str] = []
    for result in results:
        candidate = getattr(result, "markdown", None)
        if callable(candidate):
            candidate = candidate()
        _append_markdown(candidate, values)
    return "\n\n".join(value for value in values if value).strip()


def _append_markdown(value: Any, output: list[str]) -> None:
    if isinstance(value, str):
        value = value.strip()
        if value and value not in output:
            output.append(value)
        return
    if isinstance(value, dict):
        preferred = value.get("markdown_texts") or value.get("markdown_text")
        if preferred is not None:
            _append_markdown(preferred, output)
            return
        for nested in value.values():
            _append_markdown(nested, output)
        return
    if isinstance(value, (list, tuple)):
        for nested in value:
            _append_markdown(nested, output)


def _result_payload(result: Any) -> dict[str, Any]:
    payload = getattr(result, "json", None)
    if callable(payload):
        payload = payload()
    if isinstance(payload, dict):
        nested = payload.get("res")
        return nested if isinstance(nested, dict) else payload
    if isinstance(result, dict):
        return result
    return {}


def _collect_regions(
    results: list[Any], image, *, page_no: int | None,
) -> list[ParsedAsset]:
    assets: list[ParsedAsset] = []
    seen: set[tuple[str, tuple[float, float, float, float]]] = set()
    for result in results:
        for region in _find_region_lists(_result_payload(result)):
            label = str(region.get("block_label") or region.get("label") or "").lower()
            if label not in {"table", "chart", "figure"}:
                continue
            bbox = _bbox(region.get("block_bbox") or region.get("bbox") or region.get("coordinate"))
            if bbox is None:
                continue
            asset_type = "chart" if label in {"chart", "figure"} else "table"
            key = (asset_type, bbox)
            if key in seen:
                continue
            seen.add(key)
            crop, width, height = _crop(image, bbox)
            content = str(region.get("block_content") or region.get("content") or "").strip()
            assets.append(ParsedAsset(
                asset_type=asset_type,
                page_no=page_no,
                bbox=bbox,
                structured_content=content,
                image_bytes=crop,
                media_type="image/png" if crop else None,
                width=width,
                height=height,
                extraction_model="PP-StructureV3",
                extraction_version="v3",
            ))
    return assets


def _find_region_lists(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in {"parsing_res_list", "layout_parsing_result", "blocks"}:
                if isinstance(nested, list):
                    found.extend(item for item in nested if isinstance(item, dict))
            else:
                found.extend(_find_region_lists(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_find_region_lists(nested))
    return found


def _bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        x0, y0, x1, y1 = (float(item) for item in value[:4])
    except (TypeError, ValueError):
        return None
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1, y1


def _crop(image, bbox: tuple[float, float, float, float]) -> tuple[bytes | None, int | None, int | None]:
    x0, y0, x1, y1 = bbox
    box = (
        max(0, round(x0)),
        max(0, round(y0)),
        min(image.width, round(x1)),
        min(image.height, round(y1)),
    )
    if box[2] - box[0] < 2 or box[3] - box[1] < 2:
        return None, None, None
    crop = image.crop(box)
    output = io.BytesIO()
    crop.save(output, format="PNG", optimize=True)
    return output.getvalue(), crop.width, crop.height
