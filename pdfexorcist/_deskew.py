"""Straighten scanned pages fed or photographed a degree or two askew.

On a landscape table a 1 degree tilt lifts a row's right end by half a row, so the OCR
engines join one district's counts to the next district's name (Karnataka dengue DR-29-07-2025).
"""

import hashlib
import io
import logging
import os
from pathlib import Path
from typing import Any

from ._prepare import save_copy

logger = logging.getLogger(__name__)

DPI = 75  # enough to place rules and text lines; the search turns this image at each step
RENDER_DPI = 300  # the straightened picture the engines read
MAX_ANGLE = 4.0  # the turns searched
MAX_LEVEL = 2.0  # the turns applied: a photo held at an angle (bmc/2026-07-28.jpg: 3.5)
# is warped too, so turning it alone does not level its rows
MIN_ANGLE = 0.3  # below, rows stay within their line on a page of 30 rows
MIN_GAIN = 1.15  # the best turn's sharpness over the page's as it is
OFF = "PDFEXORCIST_DESKEW"  # set to 0 to read scans as they are


def _sharpness(ink: Any, angle: float) -> float:
    """How sharply the ink falls into rows once turned by angle (counter-clockwise).

    Level text and rules fill few pixel rows, so the row sums jump from one row to the next."""
    import numpy as np
    from PIL import Image

    turned = np.asarray(ink.rotate(angle, resample=Image.Resampling.NEAREST)) > 0
    return float(np.var(np.diff(turned.sum(axis=1).astype(float))))


def tilt(ink: Any) -> float:
    """Degrees to turn the image counter-clockwise to level it; 0 when it is level.

    ink is a PIL image with the ink white. Steps of 0.25 degrees (a peak is ~0.5 wide),
    then 0.1 near the best."""
    score = {0.0: _sharpness(ink, 0.0)}
    steps = [x / 4 for x in range(-int(MAX_ANGLE * 4), int(MAX_ANGLE * 4) + 1)]
    for a in steps:
        score.setdefault(a, _sharpness(ink, a))
    coarse = max(score, key=score.__getitem__)
    for k in range(-4, 5):
        a = round(coarse + k / 10, 1)
        if abs(a) <= MAX_ANGLE:
            score.setdefault(a, _sharpness(ink, a))
    best = max(score, key=score.__getitem__)
    if not MIN_ANGLE <= abs(best) <= MAX_LEVEL or score[best] < MIN_GAIN * score[0.0]:
        return 0.0
    return best


def _ink(page: Any) -> Any:
    """The page at DPI, grey, contrast stretched, ink white on black."""
    import pymupdf
    from PIL import Image, ImageOps

    pix = page.get_pixmap(dpi=DPI, colorspace=pymupdf.csGRAY)
    img = ImageOps.autocontrast(Image.frombytes("L", (pix.width, pix.height), pix.samples), 1)
    return img.point(lambda v: 255 if v < 128 else 0)


def page_tilt(page: Any, cache: Path | None = None) -> float:
    """tilt() of a page, cached under cache by the rendered page."""
    ink = _ink(page)
    key = hashlib.md5(f"{ink.width}x{ink.height}".encode() + ink.tobytes()).hexdigest()
    f = cache / f"{key}.txt" if cache else None
    if f is not None and f.exists():
        return float(f.read_text())
    angle = tilt(ink)
    if f is not None:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(str(angle))
        except OSError as e:
            logger.debug("tilt cache not written: %s", e)
    return angle


def _level(doc: Any, page: Any, angle: float) -> None:
    """Replace page's drawing by its picture turned angle degrees counter-clockwise."""
    from PIL import Image

    # at the picture's own resolution, up to RENDER_DPI: a photo wrapped at 72 dpi is a
    # page of 40 inches, which 300 dpi would make 12,000 pixels wide
    native = [
        im["width"] * 72 / max(im["bbox"][2] - im["bbox"][0], 1) for im in page.get_image_info()
    ]
    pix = page.get_pixmap(dpi=round(min([RENDER_DPI, *native])))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    img = img.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor="white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    n, rect = page.number, page.rect  # the page as shown, after any /Rotate
    doc.delete_page(n)
    new = doc.new_page(n, width=rect.width, height=rect.height)
    new.insert_image(new.rect, stream=buf.getvalue())


def _cache_dir() -> Path:
    from .fetch import cache_root

    return cache_root() / "deskew"


def straighten_scans(pdf: Path, out_dir: Path) -> Path:
    """Copy of pdf with each tilted scanned page levelled, or pdf itself.

    Only pages that are one picture without visible text are looked at, and only when
    $PDFEXORCIST_DESKEW is not 0."""
    import pymupdf

    from ._orient import _picture_only

    if os.environ.get(OFF, "1") == "0":
        return pdf
    with pymupdf.open(pdf) as doc:
        cache = _cache_dir()
        angles = [page_tilt(p, cache) if _picture_only(p) else 0.0 for p in doc]
        tilted = [(n, a) for n, a in enumerate(angles) if a]
        if not tilted:
            return pdf
        for n, angle in tilted:
            logger.info("page %d: scan levelled by %.1f degrees", n + 1, angle)
            _level(doc, doc[n], angle)
        return save_copy(doc, out_dir, Path(pdf).name)
