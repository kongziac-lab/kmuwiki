"""Local visual sanitization boundary for multimodal indexing.

Raw images never cross this module toward Cohere/Supabase.  The sanitizer
normalizes and re-encodes pixels, uses local OCR boxes to redact policy-matched
PII, and OCR-verifies the derivative before it can be marked safe for egress.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from .ocr import OCRAnalysis, OCREngine, OCRSpan
from .pii.egress_gate import scan
from .pii.masker import Masker


@dataclass(frozen=True)
class SanitizedVisual:
    safe: bool
    image_bytes: bytes | None = None
    media_type: str | None = None
    width: int | None = None
    height: int | None = None
    masked_ocr_text: str = ""
    redaction_applied: bool = False
    error: str | None = None


class VisualSanitizer:
    def __init__(
        self,
        ocr: OCREngine,
        *,
        max_input_bytes: int = 20 * 1024 * 1024,
        max_pixels: int = 20_000_000,
        max_side: int = 2000,
        jpeg_quality: int = 85,
        verify_after_redaction: bool = True,
    ):
        self.ocr = ocr
        self.max_input_bytes = max_input_bytes
        self.max_pixels = max_pixels
        self.max_side = max_side
        self.jpeg_quality = max(50, min(jpeg_quality, 95))
        self.verify_after_redaction = verify_after_redaction

    def sanitize(
        self,
        image_bytes: bytes,
        *,
        masker: Masker,
        analysis: OCRAnalysis | None = None,
    ) -> SanitizedVisual:
        if not image_bytes or len(image_bytes) > self.max_input_bytes:
            return SanitizedVisual(False, error="visual input is empty or exceeds size limit")

        try:
            from PIL import Image, ImageDraw, ImageOps

            image = Image.open(io.BytesIO(image_bytes))
            image = ImageOps.exif_transpose(image)
            image.load()
            if image.width * image.height > self.max_pixels:
                image.thumbnail((self.max_side, self.max_side))
            elif max(image.width, image.height) > self.max_side:
                image.thumbnail((self.max_side, self.max_side))
            image = image.convert("RGB")
        except Exception as exc:
            return SanitizedVisual(False, error=f"invalid visual: {type(exc).__name__}: {exc}")

        # OCR boxes must be produced against the normalized dimensions used for
        # redaction.  If the parser supplied analysis for differently-sized
        # pixels, deliberately ignore it and re-run OCR.
        normalized = _encode_jpeg(image, self.jpeg_quality)
        analysis = self.ocr.analyze(normalized)
        if not analysis.succeeded:
            return SanitizedVisual(False, error=analysis.error or "visual OCR failed")

        raw_text, offsets = _span_text_and_offsets(analysis.spans)
        masked = masker.mask(raw_text)
        # The visual path uses the all-PII policy.  If it asks for NER labels,
        # fail closed when the local NER model is unavailable.
        if masker.policy.ner_labels and not masked.ner_available:
            return SanitizedVisual(False, masked_ocr_text=masked.text,
                                   error="visual redaction requires local NER")

        findings = scan(raw_text, enforce_labels=masker.policy.enforced_high())
        redact_indexes = {
            index
            for index, (start, end) in enumerate(offsets)
            if any(start < finding.span[1] and finding.span[0] < end for finding in findings)
        }
        # NER replacements are not represented by regex Finding objects; check
        # each OCR span independently so names/addresses still redact.
        for index, span in enumerate(analysis.spans):
            if masker.mask(span.text).text != span.text:
                redact_indexes.add(index)

        if redact_indexes:
            draw = ImageDraw.Draw(image)
            for index in sorted(redact_indexes):
                if index >= len(analysis.spans):
                    continue
                x0, y0, x1, y1 = analysis.spans[index].bbox
                pad = 3
                draw.rectangle(
                    (max(0, x0 - pad), max(0, y0 - pad),
                     min(image.width, x1 + pad), min(image.height, y1 + pad)),
                    fill="black",
                )

        derivative = _encode_jpeg(image, self.jpeg_quality)
        if self.verify_after_redaction:
            verified = self.ocr.analyze(derivative)
            if not verified.succeeded:
                return SanitizedVisual(False, masked_ocr_text=masked.text,
                                       error=verified.error or "redacted visual verification failed")
            verified_masked = masker.mask(verified.text)
            if (masker.policy.ner_labels and not verified_masked.ner_available
                    or verified_masked.text != verified.text
                    or scan(verified.text, enforce_labels=masker.policy.enforced_high())):
                return SanitizedVisual(False, masked_ocr_text=masked.text,
                                       error="redacted visual still contains policy-matched PII")

        return SanitizedVisual(
            True,
            image_bytes=derivative,
            media_type="image/jpeg",
            width=image.width,
            height=image.height,
            masked_ocr_text=masked.text,
            redaction_applied=True,
        )


def _span_text_and_offsets(spans: list[OCRSpan]) -> tuple[str, list[tuple[int, int]]]:
    parts: list[str] = []
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for span in spans:
        if parts:
            cursor += 1  # newline separator
        text = span.text or ""
        parts.append(text)
        offsets.append((cursor, cursor + len(text)))
        cursor += len(text)
    return "\n".join(parts), offsets


def _encode_jpeg(image, quality: int) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()
