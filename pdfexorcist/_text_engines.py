"""Text-layer engines."""

import functools
import gc
import itertools
import logging
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from ._bold import COPY_PT, debold_line, one_value
from ._registry import register
from ._spaces import overprinted_spaces
from .cells import Box, BoxCell, _inside, union
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
        yield i, _layout_lines(page)


def _layout_lines(text: str) -> list:
    """Cells of fixed-width layout text, x in character columns.

    Words one space apart form a cell, so values in narrow columns ("947 948")
    are split into a cell each at its own columns; label words stay joined.
    """
    out = []
    for ln in text.splitlines():
        cells = [(m.start(), m.group()) for m in re.finditer(r"\S+(?: \S+)*", ln)]
        line = debold_line([(at + len(t) / 2, t) for at, t in cells], is_value)
        split = []
        for (at, _), (x, t) in zip(cells, line, strict=True):
            toks = list(re.finditer(r"\S+", t))
            as_printed = t == ln[at : at + len(t)]  # not de-bolded
            if len(toks) > 1 and as_printed and all(is_value(m.group()) for m in toks):
                split += [(at + m.start() + len(m.group()) / 2, m.group()) for m in toks]
            else:
                split.append((x, t))
        out.append(split)
    return out


@register("pypdf", default=False)
def pypdf_(pdf: Path) -> Iterator[Page]:
    """Extract pypdf's fixed-width layout text."""
    import pypdf

    for i, page in enumerate(pypdf.PdfReader(pdf).pages, start=1):
        yield i, _layout_lines(page.extract_text(extraction_mode="layout"))


PDFJS_INSTALL = "npm install -g pdfjs-dist"


@register("pdfjs", default=False)
def pdfjs_(pdf: Path) -> Iterator[Page]:
    """Extract Mozilla pdf.js text items through Node, a page at a time."""
    import json
    import tempfile

    node, dist = shutil.which("node"), _pdfjs_dist()
    if not node or not dist:
        raise ImportError(f"pdfjs needs Node and pdfjs-dist: {PDFJS_INSTALL}")
    cmd = [node, str(Path(__file__).with_name("_pdfjs.mjs")), str(dist), str(pdf.resolve())]
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log, encoding="utf-8")
        assert proc.stdout is not None
        try:
            for i, line in enumerate(proc.stdout, start=1):
                yield i, group_words([w for box in json.loads(line) for w in _words(*box)])
            if proc.wait():
                log.seek(0)
                raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=log.read())
        finally:
            if proc.poll() is None:  # stopped early (an error, or the caller stopped reading)
                proc.kill()
                proc.wait()


@functools.lru_cache(maxsize=1)
def _pdfjs_dist() -> Path | None:
    """Find pdfjs-dist: $PDFEXORCIST_PDFJS, else the global npm root."""
    if env := os.environ.get("PDFEXORCIST_PDFJS"):
        return Path(env)
    npm = shutil.which("npm")  # npm.cmd on Windows; a bare name fails there
    if not npm:
        return None
    root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True).stdout.strip()
    dist = Path(root) / "pdfjs-dist"
    return dist if dist.is_dir() else None


def _space_ids(page: Any) -> set[int]:
    """Find space glyphs overprinted on visible glyphs."""
    return overprinted_spaces(page.chars)


def _not_in(ids: set[int]) -> Callable[[Any], bool]:
    """Filter objects whose ids are absent from ids."""
    return lambda o: id(o) not in ids


@register("pdfplumber")
def pdfplumber_(pdf: Path) -> Iterator[Page]:
    """Extract pdfplumber words grouped into lines."""
    import pdfplumber

    with pdfplumber.open(pdf) as doc:
        for i, raw in enumerate(doc.pages, start=1):
            # fake bold draws a glyph again a fraction of a point off
            page = raw.filter(_not_in(_space_ids(raw))).dedupe_chars(tolerance=COPY_PT)
            words = [  # pdfminer reads text drawn outside the page box; poppler doesn't
                w
                for w in _plumber_words(page, sideways=raw.rotation % 360 == 0)
                if _inside(raw.bbox, w["x0"], w["top"], w["x1"], w["bottom"])
            ]
            yield (
                i,
                group_words([(w["x0"], w["x1"], w["bottom"], w["text"], w["top"]) for w in words]),
            )
            raw.close()


def _plumber_words(page: Any, sideways: bool) -> list[dict]:
    """pdfplumber's words. Text turned a quarter (headings printed sideways, 2024 AMRSN
    Table 2.21) is read along its baseline as whole words, as PyMuPDF and pdfium read it;
    pdfplumber alone would give one word per letter."""
    if not sideways:
        return page.extract_words(use_text_flow=False)

    def turn(o: dict) -> float:
        return o["matrix"][1] if o.get("object_type") == "char" else 0.0

    flat = page.filter(lambda o: abs(turn(o)) <= 0.5).extract_words(use_text_flow=False)
    up = page.filter(lambda o: o.get("object_type") != "char" or turn(o) > 0.5)
    down = page.filter(lambda o: o.get("object_type") != "char" or turn(o) < -0.5)
    return (
        flat
        + up.extract_words(line_dir="ltr", char_dir="btt")
        + down.extract_words(line_dir="rtl", char_dir="ttb")
    )


@register("pymupdf")
def pymupdf_(pdf: Path) -> Iterator[Page]:
    """Extract PyMuPDF words grouped into lines."""
    import pymupdf

    flags = pymupdf.TEXTFLAGS_WORDS & ~pymupdf.TEXT_MEDIABOX_CLIP
    with pymupdf.open(pdf) as doc:
        for i, page in enumerate(doc, start=1):
            tp = page.get_textpage(flags=flags)  # laid out once for both readings
            words = _respace(
                page.get_text("words", textpage=tp), page.get_text("rawdict", textpage=tp)
            )
            turn = page.rotation_matrix  # words come unrotated
            rects = [(pymupdf.Rect(w[:4]) * turn, w[4]) for w in words]
            yield i, group_words([(r.x0, r.x1, r.y1, t, r.y0) for r, t in rects])


def _respace(words: list, raw: dict) -> list:
    """Rejoin PyMuPDF words split at space glyphs overprinted on letters ("d u c k").

    A line holding such a space gets words rebuilt from its glyphs without it,
    when they spell the same letters; every other line keeps PyMuPDF's words.
    """
    rebuilt: dict[tuple[int, int], list] = {}
    for block in raw["blocks"]:
        for n, line in enumerate(block.get("lines", ())):
            glyphs = [g for span in line["spans"] for g in span["chars"]]
            if line["dir"] != (1.0, 0.0) or not any(g["c"] == " " for g in glyphs):
                continue
            chars = [
                {"text": g["c"], "x0": b[0], "x1": b[2], "top": b[1], "g": g}
                for g in glyphs
                for b in [g["bbox"]]
            ]
            stray = overprinted_spaces(chars)
            if stray:
                kept = [c["g"] for c in chars if id(c) not in stray]
                rebuilt[(block["number"], n)] = _glyph_words(kept, block["number"], n)
    if not rebuilt:
        return words
    out = []
    for key, group in itertools.groupby(words, key=lambda w: (w[5], w[6])):
        old = list(group)
        new = rebuilt.get(key, old)
        out += new if "".join(w[4] for w in new) == "".join(w[4] for w in old) else old
    return out


def _glyph_words(glyphs: list, block: int, line: int) -> list:
    """PyMuPDF word tuples (x0, y0, x1, y1, text, block, line, word) from glyphs split at spaces."""
    out: list = []
    for space, run in itertools.groupby(glyphs, key=lambda g: g["c"].isspace()):
        if space:
            continue
        gs = list(run)
        box = union([g["bbox"] for g in gs])
        assert box is not None  # every glyph has a bbox
        out.append((*box, "".join(g["c"] for g in gs), block, line, len(out)))
    return out


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


def camelot_ml() -> bool:
    """Whether camelot-py[ml] is installed."""
    return all(find_spec(m) for m in ("torch", "transformers", "timm"))


def _camelot_pages(pdf: Path) -> Iterator[Page]:
    import camelot
    import pymupdf

    with pymupdf.open(pdf) as doc:
        n_pages = doc.page_count
        # camelot: y up from the media box corner; flip to pdfplumber's frame
        boxes = [(p.mediabox.x0, p.mediabox.y0, p.mediabox.height) for p in doc]
    flavors = ["lattice", "stream", "network", "hybrid"]
    if camelot_ml():  # a partial ml install imports torch and queries the Hub before failing
        flavors.append("ml")
    for i in range(1, n_pages + 1):
        reads: list = []
        dx, dy, h = boxes[i - 1]
        with _layout_once():
            for flavor in flavors:
                try:
                    tables = camelot.read_pdf(str(pdf), pages=str(i), flavor=flavor)
                except (
                    ValueError,
                    IndexError,
                    ZeroDivisionError,
                    ImportError,  # ml on a broken install
                ) as e:  # blank/figure pages
                    logger.debug("camelot %s page %d: %s", flavor, i, e)
                    continue
                reads.append(
                    [
                        [
                            BoxCell(
                                ((b := t.cells[r][j]).x1 + b.x2) / 2,
                                " ".join(c.split()),  # a wrapped cell's lines, one space apart
                                (b.x1 + dx, h - b.y2 - dy, b.x2 + dx, h - b.y1 - dy),
                            )
                            for j, c in enumerate(row)
                            if c
                        ]
                        for t in _distinct(tables)
                        for r, row in enumerate(t.df.itertuples(index=False))
                    ]
                )
        best: list = max(reads, key=_n_values, default=[])
        yield i, [debold_line(_one_values(ln), is_value) for ln in best]


@contextmanager
def _layout_once() -> Iterator[None]:
    """Lay out each page once, shared by all of camelot's flavors."""
    from camelot.handlers import PDFHandler

    real = getattr(PDFHandler, "_get_layout", None)
    if real is None:  # a private method; another camelot may not have it
        yield
        return
    done: dict = {}  # one page's layouts, by layout settings

    def layout(self: Any, page: Any, **kwargs: Any) -> Any:
        key = tuple(sorted(kwargs.items()))
        if key not in done:  # after camelot's own fix for rotated pages, which runs once
            done[key] = real(self, page, **kwargs)
        return done[key]

    PDFHandler._get_layout = layout  # type: ignore[method-assign]
    try:
        yield
    finally:
        PDFHandler._get_layout = real  # type: ignore[method-assign]


def _one_values(line: list) -> list:
    """Read each overprinted cell once."""
    return [BoxCell(c[0], one_value(c[1], is_value), c.box) for c in line]


def _distinct(tables: Any) -> list:
    """Drop tables mostly inside a larger one; network and hybrid repeat rows across them."""

    def overlap(a: Box, b: Box) -> float:
        return max(min(a[2], b[2]) - max(a[0], b[0]), 0) * max(min(a[3], b[3]) - max(a[1], b[1]), 0)

    boxes = [t._bbox for t in tables]
    area = [overlap(b, b) for b in boxes]
    kept: list[int] = []
    for i in sorted(range(len(tables)), key=lambda i: area[i], reverse=True):
        if all(overlap(boxes[i], boxes[k]) < area[i] / 2 for k in kept):
            kept.append(i)
    return [tables[i] for i in sorted(kept)]


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


def _words(x0: float, x1: float, y_top: float, y_bottom: float, text: str) -> list:
    """Split a text box into positioned tokens."""
    return [(a, b, y_bottom, t, y_top) for a, b, t in _spans(x0, x1, text)]


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


# last: import order sets registration order
from ._pdfium import _displayed, _pdfium_words, pdfium_  # noqa: E402

__all__ = ["_displayed", "_pdfium_words", "pdfium_"]
