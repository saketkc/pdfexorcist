"""Turn sideways or upside-down scanned pages upright by setting their /Rotate.

Line-based OCR engines read nothing from a sideways table, so a run gets too few voters.
/Rotate turns the page for every engine alike; their boxes come in the turned page's coordinates.
"""

import hashlib
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from ._prepare import save_copy

logger = logging.getLogger(__name__)

OSD_DPI = (200, 300)  # below, OSD guesses (DR4-10-23 at 150 dpi: 0 where it is 270)
MIN_CONFIDENCE = 4.0  # summed over OSD_DPI; one sideways Karnataka scan: 5.6-17
OFF = "PDFEXORCIST_TURN_SCANS"  # set to 0 to read scans as they are


def osd(png: bytes) -> tuple[int, float] | None:
    """Tesseract OSD of a page image: degrees to turn it clockwise, and the confidence."""
    try:
        out = subprocess.run(
            ["tesseract", "stdin", "stdout", "--psm", "0"],
            input=png,
            capture_output=True,
            check=True,
            timeout=60,
        ).stdout.decode()
    except (OSError, subprocess.SubprocessError) as e:  # too few characters, or no tesseract
        logger.debug("orientation not detected: %s", e)
        return None
    rot = re.search(r"Rotate: (\d+)", out)
    conf = re.search(r"Orientation confidence: ([\d.]+)", out)
    if not rot or not conf:
        return None
    # OSD's Rotate turns the image clockwise, as /Rotate turns a page (DR4-10-23: 270)
    return int(rot.group(1)) % 360, float(conf.group(1))


def _picture_only(page: Any) -> bool:
    """Whether a page is a picture covering it, without visible text.

    A scanning app's hidden OCR layer does not count (Adobe Scan's on DR17-10-23 reads the
    sideways table as level lines, and cannot be dropped alone)."""
    from ._invisible import _hidden_span
    from .pages import is_scan_page

    if not is_scan_page(page):
        return False
    return all(_hidden_span(s) for s in page.get_texttrace())


def page_turn(page: Any, cache: Path | None = None) -> int:
    """Degrees to turn a scanned page clockwise (0, 90, 180 or 270) so its text reads left to
    right; 0 when OSD is unsure. Cached under cache by the rendered page.

    OSD of one render is fickle on faint scans (DR9-11-23: 270 at 200 dpi, 0 at 300), so
    each render's confidence counts for its turn, and the surest turn wins."""
    pix = _grey(page, OSD_DPI[-1])
    key = hashlib.md5(f"{pix.width}x{pix.height}".encode() + pix.samples)
    f = cache / f"{key.hexdigest()}.txt" if cache else None
    if f is not None and f.exists():
        return int(f.read_text())
    sure: dict[int, float] = {}
    for dpi in OSD_DPI:
        if got := osd(_contrasted(pix if dpi == OSD_DPI[-1] else _grey(page, dpi))):
            sure[got[0]] = sure.get(got[0], 0.0) + got[1]
    turn = max(sure, key=sure.__getitem__, default=0)
    turn = turn if sure.get(turn, 0.0) >= MIN_CONFIDENCE else 0
    if f is not None and sure:
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(str(turn))
        except OSError as e:
            logger.debug("orientation cache not written: %s", e)
    return turn


def _grey(page: Any, dpi: int) -> Any:
    import pymupdf

    return page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)


def _contrasted(pix: Any) -> bytes:
    """A PNG of grey pix, its levels stretched (a faint scan reads better)."""
    import io

    from PIL import Image, ImageOps

    img = ImageOps.autocontrast(Image.frombytes("L", (pix.width, pix.height), pix.samples), 1)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _cache_dir() -> Path:
    from .fetch import cache_root

    return cache_root() / "orient"


def turn_scans(pdf: Path, out_dir: Path) -> Path:
    """Copy of pdf with each sideways or upside-down scanned page turned upright, or pdf itself.

    Only pages that are one picture without text are looked at, and only when tesseract is
    on PATH and $PDFEXORCIST_TURN_SCANS is not 0.
    """
    import pymupdf

    if os.environ.get(OFF, "1") == "0" or not shutil.which("tesseract"):
        return pdf
    with pymupdf.open(pdf) as doc:
        turned = 0
        for page in doc:
            if not _picture_only(page) or not (turn := page_turn(page, _cache_dir())):
                continue
            logger.info("page %d: scan turned %d degrees clockwise", page.number + 1, turn)
            page.set_rotation((page.rotation + turn) % 360)
            turned += 1
        if not turned:
            return pdf
        logger.info("%d scanned pages turned upright", turned)
        return save_copy(doc, out_dir, Path(pdf).name)
