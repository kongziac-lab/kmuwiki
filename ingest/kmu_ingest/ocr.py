"""OCR (로컬). 1차: EasyOCR(CPU/Mac). 2차: PaddleOCR(GPU 서버).

OCR 본문은 §7.A 고위험 등급으로 마스킹한다(masker high_risk=True).
백엔드 미설치 시 available=False → 파이프라인이 pending_ocr 로 지연한다.
"""

from __future__ import annotations


class OCREngine:
    def __init__(self, backend: str = "easyocr"):
        self.backend = backend
        self._reader = None
        self.available = backend != "none"

    def _ensure(self):
        if self._reader is not None or not self.available:
            return
        if self.backend == "easyocr":
            import easyocr  # lazy
            self._reader = easyocr.Reader(["ko", "en"], gpu=False)
        elif self.backend == "paddle":
            from paddleocr import PaddleOCR  # lazy
            self._reader = PaddleOCR(lang="korean", use_angle_cls=True)
        else:
            self.available = False

    def image_to_text(self, image_bytes: bytes) -> str:
        """이미지 바이트 → 텍스트. 실패/미설치 시 빈 문자열."""
        try:
            self._ensure()
        except ImportError:
            self.available = False
            return ""
        if not self.available or self._reader is None:
            return ""
        if self.backend == "easyocr":
            lines = self._reader.readtext(image_bytes, detail=0, paragraph=True)
            return "\n".join(lines)
        if self.backend == "paddle":
            result = self._reader.ocr(image_bytes, cls=True)
            lines = [w[1][0] for page in (result or []) for w in (page or [])]
            return "\n".join(lines)
        return ""
