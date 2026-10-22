"""The PDFium engine: glyphs grouped into words by gap, then into lines."""

import ctypes
import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ._bold import COPY_PT
from ._registry import register
from ._spaces import overprinted_spaces
from .cells import _inside
from .rows import Page, group_words


@register("pdfium")
def pdfium_(pdf: Path) -> Iterator[Page]:
    """Extract PDFium glyphs grouped into words by gap, then into lines."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    try:
        for i, page in enumerate(doc, start=1):
            tp = page.get_textpage()
            yield i, group_words(_pdfium_words(page, tp))
            tp.close()
            page.close()
    finally:
        doc.close()


def _pdfium_words(page: Any, tp: Any) -> list:
    """Group PDFium glyphs into words by gap; PDFium's own text runs span empty columns."""
    import pypdfium2 as pdfium
    from pdfplumber.utils.text import WordExtractor

    rot = page.get_rotation()
    w, h = page.get_size()  # displayed; glyph boxes are unrotated
    box = page.get_bbox()
    chars: list[dict] = []
    runs: list[list[tuple]] = []  # sideways glyphs (j, x0, x1, top, bottom, text) per run
    seen: dict[tuple, list[tuple]] = {}  # (text, x, y) on a COPY_PT grid -> (x0, top, j)
    ox, oy = ctypes.c_double(), ctypes.c_double()
    char_angle = pdfium.raw.FPDFText_GetCharAngle
    for j, ch in enumerate(tp.get_text_range()):
        if ch == "\ufffe":  # PDFium's mark for a hyphen that ends a line; the others read "-"
            ch = "-"
        # tight boxes gap around "."
        left, b, r, t = tp.get_charbox(j, loose=True)
        if r <= left or not _inside(box, left, b, r, t):
            continue  # generated (zero-width) glyph, or outside the page box
        x0, top, x1, bottom = _displayed(left, b, r, t, rot, w, h)
        gx, gy = int(x0 // COPY_PT), int(top // COPY_PT)
        near = (
            k
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for k in seen.get((ch, gx + dx, gy + dy), ())
        )
        # fake bold redraws a glyph a fraction of a point off; ligature letters are neighbours
        if any(
            abs(kx - x0) < COPY_PT and abs(kt - top) < COPY_PT and j - kj != 1
            for kx, kt, kj in near
        ):
            continue
        seen.setdefault((ch, gx, gy), []).append((x0, top, j))
        # pdfium char angles ignore /Rotate
        angle = round(math.degrees(char_angle(tp, j)) + rot) % 360
        if angle == 0:
            chars.append(
                {
                    "text": ch,
                    "x0": x0,
                    "x1": x1,
                    "top": top,
                    "bottom": bottom,
                    "doctop": top,
                    "upright": True,
                }
            )
            continue
        # vertical runs use the baseline; glyph extents across them differ by pdfium build
        if angle in (90, 270):
            pdfium.raw.FPDFText_GetCharOrigin(tp, j, ox, oy)
            x0 = x1 = _displayed(ox.value, oy.value, ox.value, oy.value, rot, w, h)[0]
        glyph = (j, x0, x1, top, bottom, ch)
        if runs and runs[-1][-1][0] == j - 1:
            runs[-1].append(glyph)
        else:
            runs.append([glyph])
    stray = overprinted_spaces(chars)  # "d u c k": spaces drawn over letters
    chars = [c for c in chars if id(c) not in stray]
    out = [
        (wd["x0"], wd["x1"], wd["bottom"], wd["text"], wd["top"])
        for wd, _ in WordExtractor().iter_extract_tuples(chars)
    ]
    for run in runs:
        _, x0s, x1s, tops, bottoms, text = zip(*run, strict=True)
        if word := "".join(text).strip():
            out.append((min(x0s), max(x1s), max(bottoms), word, min(tops)))
    return out


def _displayed(
    left: float, b: float, r: float, t: float, rot: int, w: float, h: float
) -> tuple[float, float, float, float]:
    """Map an unrotated PDF box (y up) to a displayed w x h page: x0, top, x1, bottom."""
    if rot == 90:
        return b, left, t, r
    if rot == 180:
        return w - r, b, w - left, t
    if rot == 270:
        return w - t, h - r, w - b, h - left
    return left, h - t, r, h - b
