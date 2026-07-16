"""OCR (로컬). 1차: EasyOCR(CPU/Mac). 2차: PaddleOCR(GPU 서버).

OCR 본문은 §7.A 고위험 등급으로 마스킹한다(masker high_risk=True).
백엔드 미설치 시 available=False → 파이프라인이 pending_ocr 로 지연한다.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field


@dataclass(frozen=True)
class OCRSpan:
    text: str
    bbox: tuple[float, float, float, float]
    confidence: float = 0.0


@dataclass(frozen=True)
class OCRAnalysis:
    spans: list[OCRSpan] = field(default_factory=list)
    succeeded: bool = True
    error: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(span.text for span in self.spans if span.text.strip())


class OCREngine:
    def __init__(self, backend: str = "easyocr"):
        self.backend = backend
        self._reader = None
        self.available = backend != "none"
        self.last_error: str | None = None

    def _ensure(self):
        if self._reader is not None or not self.available:
            return
        if self.backend == "easyocr":
            import easyocr  # lazy
            self._reader = easyocr.Reader(["ko", "en"], gpu=False)
        elif self.backend == "paddle":
            from paddleocr import PaddleOCR  # lazy
            try:
                self._reader = PaddleOCR(
                    lang="korean",
                    text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=True,
                    enable_mkldnn=False,
                )
            except TypeError:
                # PaddleOCR 2.x compatibility. v3 workers always take the
                # explicit PP-OCRv5 path above.
                self._reader = PaddleOCR(lang="korean", use_angle_cls=True)
        else:
            self.available = False

    def ensure_available(self) -> bool:
        try:
            self._ensure()
        except Exception as exc:
            self.available = False
            self.last_error = f"{type(exc).__name__}: {exc}"
        return self.available and self._reader is not None

    def analyze(self, image_bytes: bytes) -> OCRAnalysis:
        """Return text with source pixel boxes for visual redaction."""
        if not self.ensure_available():
            return OCRAnalysis(succeeded=False, error=self.last_error or "OCR unavailable")
        try:
            if self.backend == "easyocr":
                result = self._reader.readtext(image_bytes, detail=1, paragraph=False)
                spans = []
                for polygon, text, confidence in result or []:
                    xs = [float(point[0]) for point in polygon]
                    ys = [float(point[1]) for point in polygon]
                    spans.append(OCRSpan(
                        text=str(text),
                        bbox=(min(xs), min(ys), max(xs), max(ys)),
                        confidence=float(confidence or 0.0),
                    ))
                return OCRAnalysis(spans=spans)
            if self.backend == "paddle":
                if hasattr(self._reader, "predict"):
                    return _paddle_v3_analysis(self._reader, image_bytes)
                result = self._reader.ocr(image_bytes, cls=True)
                spans = []
                for page in result or []:
                    for item in page or []:
                        if not item or len(item) < 2:
                            continue
                        polygon, recognition = item[0], item[1]
                        text = recognition[0] if recognition else ""
                        confidence = recognition[1] if recognition and len(recognition) > 1 else 0.0
                        xs = [float(point[0]) for point in polygon]
                        ys = [float(point[1]) for point in polygon]
                        spans.append(OCRSpan(
                            text=str(text),
                            bbox=(min(xs), min(ys), max(xs), max(ys)),
                            confidence=float(confidence or 0.0),
                        ))
                return OCRAnalysis(spans=spans)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return OCRAnalysis(succeeded=False, error=self.last_error)
        return OCRAnalysis(succeeded=False, error=f"unsupported backend: {self.backend}")

    def image_to_text(self, image_bytes: bytes) -> str:
        """이미지 바이트 → 텍스트. 실패/미설치 시 빈 문자열."""
        return self.analyze(image_bytes).text


def _paddle_v3_analysis(reader, image_bytes: bytes) -> OCRAnalysis:
    import numpy as np
    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    spans: list[OCRSpan] = []
    for result in reader.predict(np.asarray(image)) or []:
        payload = getattr(result, "json", None)
        if callable(payload):
            payload = payload()
        if not isinstance(payload, dict):
            payload = result if isinstance(result, dict) else {}
        if isinstance(payload.get("res"), dict):
            payload = payload["res"]
        texts = payload.get("rec_texts") or []
        scores = payload.get("rec_scores") or []
        polygons = payload.get("rec_polys") or payload.get("dt_polys") or []
        boxes = payload.get("rec_boxes") or []
        for index, text in enumerate(texts):
            polygon = polygons[index] if index < len(polygons) else None
            box = boxes[index] if index < len(boxes) else None
            candidate = polygon if polygon is not None and len(polygon) else box
            bbox = _paddle_bbox(candidate)
            if bbox is None:
                continue
            confidence = scores[index] if index < len(scores) else 0.0
            spans.append(OCRSpan(str(text), bbox, float(confidence or 0.0)))
    return OCRAnalysis(spans=spans)


def _paddle_bbox(value) -> tuple[float, float, float, float] | None:
    try:
        first = value[0]
        try:
            is_polygon = len(first) >= 2
        except TypeError:
            is_polygon = False
        if len(value) == 4 and not is_polygon:
            x0, y0, x1, y1 = (float(item) for item in value)
            return (x0, y0, x1, y1) if x1 > x0 and y1 > y0 else None
        xs = [float(point[0]) for point in value]
        ys = [float(point[1]) for point in value]
        return min(xs), min(ys), max(xs), max(ys)
    except (TypeError, ValueError, IndexError):
        return None
