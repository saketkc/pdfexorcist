"""Map engine boxes to display pixels."""

import math
import statistics
from typing import Any

from .cells import Box, token_boxes

SHOW_DPI = 200  # display resolution of a text page (photos keep their own)
PAGE_FRAME = {"pymupdf", "tesseract"}  # boxes in pymupdf page.rect points
RENDER_FRAME = {"ocrmac", "paddleocr", "chandra", "glmocr"}  # the image render_page made
USER_FRAME = {"pdfplumber", "pdfium", "camelot"}  # (x, page height - y) in PDF user space
GEOMETRY_PREFERENCE = ["pymupdf", "pdfplumber", "pdfium", "paddleocr", "ocrmac", "tesseract"]


class _Frames:
    """Map an engine box to display pixels."""

    def __init__(self, page: Any) -> None:
        import pymupdf

        from ._ocr_engines import render_page

        r = render_page(page, text_dpi=SHOW_DPI)  # a photo: as the OCR engines saw it
        self.k = r.dpi / 72  # pixels per point
        self.angle = r.angle
        self.size0 = r.size0
        self.image = r.image
        self.height = page.mediabox.height
        self.matrix = page.transformation_matrix
        self._rect = pymupdf.Rect

    def _rotate(self, x: float, y: float) -> tuple[float, float]:
        """Map an unlevelled pixel into the rotated image."""
        a = math.radians(self.angle)
        (w, h), (W, H) = self.size0, self.image.size
        dx, dy = x - w / 2, y - h / 2
        return (
            W / 2 + dx * math.cos(a) + dy * math.sin(a),
            H / 2 - dx * math.sin(a) + dy * math.cos(a),
        )

    def to_px(self, engine: str, box: Box) -> Box:
        x0, y0, x1, y1 = box
        if engine in RENDER_FRAME:  # already in the levelled image, in points
            return (x0 * self.k, y0 * self.k, x1 * self.k, y1 * self.k)
        if engine in USER_FRAME:  # PDF user space with y flipped by the page height
            r = self._rect(x0, self.height - y1, x1, self.height - y0) * self.matrix
            x0, y0, x1, y1 = r.x0, r.y0, r.x1, r.y1
        pts = [(x * self.k, y * self.k) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        if self.angle:
            pts = [self._rotate(x, y) for x, y in pts]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))


def _shift(box: Box, d: tuple[float, float]) -> Box:
    return (box[0] + d[0], box[1] + d[1], box[2] + d[0], box[3] + d[1])


def _centre(b: Box) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _align(words: list[tuple[str, Box]], ref: list[tuple[str, Box]]) -> tuple[float, float]:
    """Align unknown coordinates to the reference words."""

    def once(ws: list[tuple[str, Box]]) -> dict[str, Box]:
        n: dict[str, int] = {}
        for t, _ in ws:
            n[t] = n.get(t, 0) + 1
        return {t: b for t, b in ws if n[t] == 1 and len(t) > 1}

    a, r = once(words), once(ref)
    pairs = [(_centre(a[t]), _centre(r[t])) for t in a.keys() & r.keys()]
    if len(pairs) < 3:
        return (0.0, 0.0)
    return (
        statistics.median(q[0] - p[0] for p, q in pairs),
        statistics.median(q[1] - p[1] for p, q in pairs),
    )


def _engine_words(lines: list) -> list[tuple[str, Box]]:
    return [(t, b) for line in lines for _, t, b in token_boxes(line) if b is not None]
