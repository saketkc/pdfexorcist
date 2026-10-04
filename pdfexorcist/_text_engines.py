"""Text-layer engines."""

import gc
import logging
import re
import shutil
import subprocess
from collections import defaultdict
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from ._registry import register
from .cells import BoxCell
from .rows import Page, group_words, is_value

logger = logging.getLogger(__name__)


@register("pdftotext")
def pdftotext(pdf: Path) -> Iterator[Page]:
    """Extract layout-preserved text with Poppler."""
    if not shutil.which("pdftotext"):
        raise ImportError("poppler's pdftotext is not on PATH")
    text = subprocess.run(
        ["pdftotext", "-layout", str(pdf), "-"],
        capture_output=True,
        encoding="utf-8",  # Windows defaults to cp1252
        errors="replace",
        check=True,
    ).stdout
    for i, page in enumerate(text.rstrip("\f").split("\f"), start=1):  # no phantom last page
        yield (
            i,
            [
                [
                    (m.start() + len(m.group()) / 2, m.group())
                    for m in re.finditer(r"\S+(?: \S+)*", ln)
                ]
                for ln in page.splitlines()
            ],
        )


def _space_ids(page: Any) -> set[int]:
    """Find space glyphs overprinted on visible glyphs."""
    lines: defaultdict[int, list[tuple[float, float]]] = defaultdict(list)
    for c in page.chars:
        if c["text"] != " ":
            lines[round(c["top"])].append((c["x0"], c["x1"]))
    stray = set()
    for c in page.chars:
        if c["text"] == " ":
            mid = (c["x0"] + c["x1"]) / 2
            near = (lines.get(round(c["top"]) + d, ()) for d in (-2, -1, 0, 1, 2))
            if any(a < mid < b for ln in near for a, b in ln):
                stray.add(id(c))
    return stray


def _not_in(ids: set[int]) -> Callable[[Any], bool]:
    """Filter objects whose ids are absent from ids."""
    return lambda o: id(o) not in ids


def _inside(box: tuple, x0: float, y0: float, x1: float, y1: float) -> bool:
    """Test whether a box center lies inside box."""
    return box[0] <= (x0 + x1) / 2 <= box[2] and box[1] <= (y0 + y1) / 2 <= box[3]


@register("pdfplumber")
def pdfplumber_(pdf: Path) -> Iterator[Page]:
    """Extract pdfplumber words grouped into lines."""
    import pdfplumber

    with pdfplumber.open(pdf) as doc:
        for i, raw in enumerate(doc.pages, start=1):
            page = raw.filter(_not_in(_space_ids(raw)))
            words = [  # pdfminer reads text drawn outside the page box; poppler doesn't
                w
                for w in page.extract_words(use_text_flow=False)
                if _inside(raw.bbox, w["x0"], w["top"], w["x1"], w["bottom"])
            ]
            yield (
                i,
                group_words([(w["x0"], w["x1"], w["bottom"], w["text"], w["top"]) for w in words]),
            )
            raw.close()


@register("pymupdf")
def pymupdf_(pdf: Path) -> Iterator[Page]:
    """Extract PyMuPDF words grouped into lines."""
    import pymupdf

    with pymupdf.open(pdf) as doc:
        for i, page in enumerate(doc, start=1):
            words = page.get_text(
                "words", flags=pymupdf.TEXTFLAGS_WORDS & ~pymupdf.TEXT_MEDIABOX_CLIP
            )
            yield i, group_words([(w[0], w[2], w[3], w[4], w[1]) for w in words])


def _n_values(lines: list) -> int:
    """Count single-value cells."""
    return sum(
        1 for line in lines for _, text in line if len(text.split()) == 1 and is_value(text.strip())
    )


@register("camelot")
def camelot_(pdf: Path) -> Iterator[Page]:
    """Extract tables with Camelot's best flavor."""
    try:
        yield from _camelot_pages(pdf)
    finally:
        # camelot 2 holds the PDF open in ref cycles; Windows cannot delete an open file
        gc.collect()


def _camelot_pages(pdf: Path) -> Iterator[Page]:
    import camelot
    import pymupdf

    with pymupdf.open(pdf) as doc:
        n_pages = doc.page_count
        # camelot: y up from the media box corner; flip to pdfplumber's frame
        boxes = [(p.mediabox.x0, p.mediabox.y0, p.mediabox.height) for p in doc]
    for i in range(1, n_pages + 1):
        reads: list = []
        dx, dy, h = boxes[i - 1]
        for flavor in ("lattice", "stream"):
            try:
                tables = camelot.read_pdf(str(pdf), pages=str(i), flavor=flavor)
            except (
                ValueError,
                IndexError,
                ZeroDivisionError,
            ) as e:  # blank/figure pages
                logger.debug("camelot %s page %d: %s", flavor, i, e)
                continue
            reads.append(
                [
                    [
                        BoxCell(
                            ((b := t.cells[r][j]).x1 + b.x2) / 2,
                            c.replace("\n", " "),
                            (b.x1 + dx, h - b.y2 - dy, b.x2 + dx, h - b.y1 - dy),
                        )
                        for j, c in enumerate(row)
                        if c
                    ]
                    for t in tables
                    for r, row in enumerate(t.df.itertuples(index=False))
                ]
            )
        yield i, max(reads, key=_n_values, default=[])


def _split_cells(row: list) -> list:
    """Split Tabula cells into positioned tokens."""
    out = []
    for c in row:
        text = c.get("text", "").replace("\r", " ")
        top, bottom = c.get("top", 0.0), c.get("top", 0.0) + c.get("height", 0.0)
        out += [
            BoxCell((a + b) / 2, t, (a, top, b, bottom))
            for a, b, t in _spans(c["left"], c["left"] + c["width"], text)
        ]
    return out


def _spans(x0: float, x1: float, text: str) -> list:
    """Position each token within a text box."""
    width = max(len(text), 1)
    return [
        (
            x0 + (x1 - x0) * m.start() / width,
            x0 + (x1 - x0) * m.end() / width,
            m.group(),
        )
        for m in re.finditer(r"\S+", text)
    ]


@register("tabula", default=False)
def tabula_(pdf: Path) -> Iterator[Page]:
    """Extract tables with Tabula's best flavor."""
    import pymupdf
    import tabula

    with pymupdf.open(pdf) as doc:
        n_pages = doc.page_count
    for i in range(1, n_pages + 1):
        reads = []
        for lattice in (True, False):
            try:
                tables = tabula.read_pdf(
                    str(pdf),
                    pages=i,
                    lattice=lattice,
                    stream=not lattice,
                    multiple_tables=True,
                    output_format="json",
                    silent=True,
                )
            except Exception as e:  # noqa: BLE001 - tabula surfaces Java errors as generic exceptions
                logger.debug("tabula page %d: %s", i, e)
                continue
            reads.append(
                [cells for t in tables for row in t.get("data", []) if (cells := _split_cells(row))]
            )
        yield i, max(reads, key=_n_values, default=[])


@register("pdfium")
def pdfium_(pdf: Path) -> Iterator[Page]:
    """Extract PDFium text runs grouped into lines."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    try:
        for i, page in enumerate(doc, start=1):
            height = page.get_height()
            box = page.get_bbox()
            tp = page.get_textpage()
            words = []
            for j in range(tp.count_rects()):
                left, b, r, t = tp.get_rect(j)
                if not _inside(box, left, b, r, t):
                    continue  # drawn outside the page box, which poppler doesn't read
                text = tp.get_text_bounded(left, b, r, t).strip()
                # PDFium keeps stray spaces inside numbers: "32 .0", "( 5 )"
                text = re.sub(r"(?<=\d) (?=[.,]\d)|(?<=\() | (?=\))", "", text)
                if text:
                    words.append((left, r, height - b, text, height - t))  # y from the top
            yield i, group_words(_join_parens(words))
            tp.close()
            page.close()
    finally:
        doc.close()


def _join_parens(words: list) -> list:
    """Rejoin PDFium-split parenthesized column numbers."""
    out: list = []
    for w in words:
        if (
            len(out) >= 2
            and w[3] == ")"
            and out[-2][3] == "("
            and out[-1][3].isdigit()
            and w[0] - out[-2][1] < 2 * (w[2] - w[4])
        ):  # within a few character widths
            o, d = out[-2], out.pop()
            out[-1] = (
                o[0],
                w[1],
                max(o[2], d[2], w[2]),
                f"({d[3]})",
                min(o[4], d[4], w[4]),
            )
        else:
            out.append(w)
    return out
