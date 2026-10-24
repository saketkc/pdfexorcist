"""Drop slanted text printed across a table ("Not Available" over blank cells).

Text turned a quarter is a heading printed sideways (2024 AMRSN Table 2.21) and stays."""

import logging
from pathlib import Path
from typing import Any

from ._prepare import redact_dots, replace_each

logger = logging.getLogger(__name__)

Char = tuple[str, float, float]  # text, centre x, centre y


def _chars(page: Any) -> tuple[list[Char], list[Char], list[Any]]:
    """Return the page's level characters, its slanted digit-free ones, and the level boxes."""
    import pymupdf

    level: list[Char] = []
    slanted: list[Char] = []
    boxes = []
    for block in page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
        for line in block.get("lines", []):
            chars = [c for s in line["spans"] for c in s["chars"] if not c["c"].isspace()]
            dx, dy = line["dir"]
            flat = abs(dy) < 0.02 and dx > 0
            if not flat and (_quarter(dx, dy) or any(c["c"].isdigit() for c in chars)):
                continue  # a sideways heading or number is table data
            for c in chars:
                x0, y0, x1, y1 = c["bbox"]
                (level if flat else slanted).append((c["c"], (x0 + x1) / 2, (y0 + y1) / 2))
                if flat:
                    boxes.append(pymupdf.Rect(c["bbox"]))
    return level, slanted, boxes


def _quarter(dx: float, dy: float) -> bool:
    """Whether a line's direction is turned a quarter, up or down."""
    return abs(dx) < 0.02


def _level_copy(doc: Any, n: int, dots: list[tuple[float, float]]) -> Any:
    """A one-page copy of page n with dots redacted, or None if its level text changed."""
    import pymupdf

    one = pymupdf.open()
    one.insert_pdf(doc, from_page=n, to_page=n)
    level = _chars(one[0])[0]
    redact_dots(one[0], dots)
    if _chars(one[0])[0] == level:
        return one
    one.close()
    return None


def _has_slanted(page: Any) -> bool:
    """Whether any text line on the page is not level (cheaper than _chars)."""
    import pymupdf

    return any(
        not (abs(ln["dir"][1]) < 0.02 and ln["dir"][0] > 0) and not _quarter(*ln["dir"])
        for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]
        for ln in block.get("lines", [])
    )


def _levelled(doc: Any, page: Any) -> Any:
    """A one-page copy of page without its slanted text, or None to keep the page."""
    import pymupdf

    if page.rotation or not _has_slanted(page):  # /Rotate pages keep their text
        return None
    _, slanted, boxes = _chars(page)
    dots = [(x, y) for _, x, y in slanted]
    if not dots:
        return None
    if one := _level_copy(doc, page.number, dots):
        return one
    clear = [
        (x, y)
        for x, y in dots
        if not any(b.intersects(pymupdf.Rect(x - 0.3, y - 0.3, x + 0.3, y + 0.3)) for b in boxes)
    ]
    if clear and (one := _level_copy(doc, page.number, clear)):
        return one
    logger.info("page %d: slanted text overlaps level text; kept", page.number + 1)
    return None


def drop_slanted(pdf: Path, out_dir: Path) -> Path:
    """Copy of pdf without slanted digit-free text, or pdf itself.

    Rotated or diagonal words cover several rows, so every engine that groups
    words by height chains those rows into one line. Every slanted character is
    redacted; if that changes the level text, only those clear of level text are;
    if that changes it too, the page is kept as printed.
    """
    return replace_each(pdf, out_dir, _levelled, "slanted text dropped")
