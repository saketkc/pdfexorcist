"""Turn pages whose table is printed sideways so its text reads left to right."""

import logging
from collections import Counter
from pathlib import Path
from typing import Any

from ._prepare import redact_dots, save_copy

logger = logging.getLogger(__name__)

# show_pdf_page rotate that levels each text direction (y down)
_TURNS = {(0, -1): 270, (-1, 0): 180, (0, 1): 90}


Centres = dict[tuple[int, int], list[tuple[float, float]]]


def _centres(page: Any) -> Centres:
    """Return each printed character's centre, by its line's direction rounded to an axis."""
    import pymupdf

    out: Centres = {}
    text = page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_TEXT)
    for block in text["blocks"]:
        for line in block.get("lines", []):
            d = (round(line["dir"][0]), round(line["dir"][1]))
            for span in line["spans"]:
                for c in span["chars"]:
                    if not c["c"].isspace():
                        x0, y0, x1, y1 = c["bbox"]
                        out.setdefault(d, []).append(((x0 + x1) / 2, (y0 + y1) / 2))
    return out


def _turn(page: Any) -> tuple[int, int] | None:
    """Return the direction most characters run in, when it is not left to right.

    Digits decide when the page has some: a chart with long sideways category labels and level
    numbers stays as it is.
    """
    import pymupdf

    count: Counter = Counter()
    digits: Counter = Counter()
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
        for line in block.get("lines", []):
            d = (round(line["dir"][0]), round(line["dir"][1]))
            text = "".join("".join(s["text"].split()) for s in line["spans"])
            count[d] += len(text)
            digits[d] += sum(c.isdigit() for c in text)
    if sum(digits.values()) >= 10:
        count = digits
    top = max(count, key=count.__getitem__, default=None)
    return top if top in _TURNS else None


def upright_pages(pdf: Path, out_dir: Path) -> Path:
    """Copy of pdf with sideways pages turned upright, or pdf itself.

    Only poppler levels text drawn sideways without /Rotate. Text across the table
    (running heads, folios, slug) is dropped; turned, it would split table rows.
    """
    import pymupdf

    with pymupdf.open(pdf) as doc:
        dirs = [None if page.rotation else _turn(page) for page in doc]
        if not any(dirs):
            return pdf
        # redact all pages first; copying between redactions breaks object numbers
        for page, d in zip(doc, dirs, strict=True):
            if d is not None:
                # a dot per character; a running head's box can overlap table text
                redact_dots(page, (xy for k, v in _centres(page).items() if k != d for xy in v))
        with pymupdf.open() as out:
            for page, d in zip(doc, dirs, strict=True):
                if d is None:
                    out.insert_pdf(doc, from_page=page.number, to_page=page.number)
                    continue
                w, h = page.rect.width, page.rect.height
                if d[0] == 0:
                    w, h = h, w
                new = out.new_page(width=w, height=h)
                new.show_pdf_page(new.rect, doc, page.number, rotate=_TURNS[d])
            logger.info("%d sideways pages turned upright", sum(map(bool, dirs)))
            path = save_copy(out, out_dir, pdf.name)
    return path
