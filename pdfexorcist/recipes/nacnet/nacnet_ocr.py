"""Category labels drawn as outlines (no text), read by OCR under the bars.

A label is kept where two engines read the same text (spaces aside) for the same bar.

ponytail: labels under vertical bars only.
"""

import logging
import math
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import nacnet_bars as nb

from pdfexorcist.cells import cell_box
from pdfexorcist.extractors import EXTRACTORS

logger = logging.getLogger(__name__)

ENGINES = ("ocrmac", "tesseract", "doctr")
DPI = 400
ANGLES = (45, 90, 0)


def categories(path: str, chart: nb.Chart) -> dict[int, str]:
    """Slot -> label read under each bar of a vertical chart, trying the label turned 45 and 90
    degrees and level; the angle with most agreed labels wins."""
    import pymupdf
    from PIL import Image

    if not chart.vertical:
        return {}
    mids: dict[int, float] = {}
    for b in chart.bars:
        mids.setdefault(b.slot, (b.box[0] + b.box[2]) / 2)
    pitch = min((abs(a - b) for a in mids.values() for b in mids.values() if a != b), default=20.0)
    base = max(b.box[3] for b in chart.bars)
    with pymupdf.open(path) as doc:
        page = doc[chart.page - 1]
        # the strip ends above any real text under it (the legend)
        below = [
            w[1]
            for w in page.get_text("words")
            if w[1] > base + 3
            and w[1] < base + 60
            and w[2] > chart.box[0] - 70
            and w[0] < chart.box[2] + 10
        ]
        clip = pymupdf.Rect(
            chart.box[0] - 70, base + 1, chart.box[2] + 10, min(below, default=base + 60) - 1
        )
        pix = page.get_pixmap(dpi=DPI, clip=clip)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    best: dict[int, str] = {}
    for angle in ANGLES:
        got = _read(img, angle, clip, mids, pitch)
        if len(got) > len(best):
            best = got
    return best


def _read(img: Any, angle: int, clip: Any, mids: dict[int, float], pitch: float) -> dict[int, str]:
    """Labels two engines agree on, with the strip turned by angle; a label's lines join."""
    turned = img.rotate(-angle, expand=True, fillcolor="white") if angle else img
    reads: dict[int, list[str]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "strip.pdf"
        turned.save(pdf, resolution=DPI)
        for name in ENGINES:
            try:
                pages = list(EXTRACTORS[name](pdf))
            except (ImportError, OSError, RuntimeError) as e:
                logger.warning("category labels: %s not run (%s)", name, e)
                continue
            mine: dict[int, list[tuple[float, str]]] = {}
            for _, lines in pages:
                for line in lines:
                    boxes = [cell_box(c) for c in line]
                    if not line or any(b is None for b in boxes):
                        continue
                    text = " ".join(c[1] for c in line)
                    # a turned label ends under its bar; a level one is centred under it
                    end = boxes[-1]
                    ex = end[2] if angle else (boxes[0][0] + end[2]) / 2
                    x, y = _back(
                        ex * DPI / 72,
                        (end[1] + end[3]) / 2 * DPI / 72,
                        img.size,
                        turned.size,
                        angle,
                    )
                    px = clip.x0 + x * 72 / DPI
                    slot = min(mids, key=lambda s: abs(mids[s] - px))
                    if abs(mids[slot] - px) < pitch / 2:
                        mine.setdefault(slot, []).append((y, text))
            for slot, parts in mine.items():
                reads.setdefault(slot, []).append(" ".join(t for _, t in sorted(parts)))
    out = {}
    for slot, texts in reads.items():
        norm = Counter(t.replace(" ", "").upper() for t in texts)
        top, n = norm.most_common(1)[0]
        if n >= 2:
            out[slot] = next(t for t in texts if t.replace(" ", "").upper() == top)
    return out


def _back(
    x: float, y: float, size: tuple[int, int], turned: tuple[int, int], angle: int
) -> tuple[float, float]:
    """A point of the turned image in the image before turning (PIL rotate with expand)."""
    a = math.radians(-angle)  # the image was turned by -angle (clockwise)
    cx, cy = turned[0] / 2, turned[1] / 2
    dx, dy = x - cx, y - cy
    # PIL turns counterclockwise for positive angles, in image coordinates (y down)
    ox = dx * math.cos(a) - dy * math.sin(a)
    oy = dx * math.sin(a) + dy * math.cos(a)
    return ox + size[0] / 2, oy + size[1] / 2
