"""Drawn table cells, for parsers whose rows text alone cannot place.

A merged cell prints its text once, in the middle of the rows it spans. The ruling lines
are the same for every engine, so words placed into drawn cells give votes that line up.

A custom parser takes only pages, so extract() publishes the PDF it is reading:

    from pdfexorcist import grid

    def parse(pages):
        tables = grid.tables(grid.current_pdf())   # {page: [Table]}
        for page_no, lines in pages:
            for table in tables.get(page_no, []):
                ...  # table.cells, table.at(x, y); words carry .box (see cells.BoxCell)

Boxes are (x0, top, x1, bottom) in points from the top-left, as BoxCell boxes are.
"""

import math
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from .cells import Box, _inside, token_boxes

_PDF: ContextVar[Path | None] = ContextVar("pdfexorcist_grid_pdf", default=None)

__all__ = ["SNAP", "Table", "Word", "bands", "current_pdf", "reading", "snap", "tables"]
__all__ += ["in_band", "words", "words_in"]

SNAP = 2.5  # pt: drawn edges closer than this are one edge
Word = tuple[str, Box]


@dataclass(frozen=True)
class Table:
    """One ruled table: its box and every drawn cell, merged cells included."""

    bbox: Box
    cells: tuple[Box, ...]

    def at(self, x: float, y: float) -> Box | None:
        """The smallest drawn cell holding the point: a row's own cell, or one merged over it."""
        hits = [
            c for c in self.cells if c[0] - 0.5 <= x <= c[2] + 0.5 and c[1] - 0.5 <= y <= c[3] + 0.5
        ]
        return min(hits, key=lambda c: (c[2] - c[0]) * (c[3] - c[1])) if hits else None


def snap(values: Iterable[float], tol: float = SNAP) -> list[float]:
    """Sorted values, dropping each within tol of the last one kept."""
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def bands(table: Table) -> list[float]:
    """The table's row edges: the top and bottom of every drawn cell, snapped."""
    return snap([c[1] for c in table.cells] + [c[3] for c in table.cells])


def words(lines: Sequence[Sequence]) -> list[Word]:
    """An engine's words on one page that carry a box."""
    return [(t, tb) for line in lines for _, t, tb in token_boxes(line) if tb is not None]


def words_in(ws: Sequence[Word], box: Box) -> list[Word]:
    """The words whose centre lies in box, top to bottom then left to right."""
    inside = [w for w in ws if _inside(box, *w[1])]
    return sorted(inside, key=lambda w: (round(w[1][1] / 4), w[1][0]))


def in_band(ws: Sequence[Word], top: float, bottom: float) -> list[Word]:
    """The words whose centre lies between top and bottom."""
    return [w for w in ws if top <= (w[1][1] + w[1][3]) / 2 <= bottom]


def current_pdf() -> Path:
    """The PDF extract() is reading (after cleaning), for a parser to read geometry from.

    Raises:
        RuntimeError: Outside extract(), where there is no such PDF.
    """
    pdf = _PDF.get()
    if pdf is None:
        raise RuntimeError("grid.current_pdf() is only set while extract() runs a parser")
    return pdf


@contextmanager
def reading(pdf: Path) -> Iterator[Path]:
    """Publish pdf as current_pdf() for the duration of a with block."""
    token = _PDF.set(pdf)
    try:
        yield pdf
    finally:
        _PDF.reset(token)


def tables(pdf: Path | str) -> dict[int, list[Table]]:
    """Every ruled table in pdf, by page number (from 1), read once per file."""
    p = Path(pdf)
    return _tables(str(p.resolve()), p.stat().st_mtime_ns)


@lru_cache(maxsize=8)
def _tables(path: str, _mtime: int) -> dict[int, list[Table]]:
    import pdfplumber

    out: dict[int, list[Table]] = {}
    with pdfplumber.open(path) as doc:
        for page_no, page in enumerate(doc.pages, start=1):
            rules = _rules(page)
            vertical = [r for r in rules if r["orientation"] == "v"]
            horizontal = [r for r in rules if r["orientation"] == "h"]
            if len(vertical) < 2 or len(horizontal) < 2:
                continue  # no ruled table on the page (pdfplumber raises on fewer)
            settings = {
                "vertical_strategy": "explicit",
                "horizontal_strategy": "explicit",
                "explicit_vertical_lines": vertical,
                "explicit_horizontal_lines": horizontal,
            }
            found = [
                Table(cast(Box, tuple(t.bbox)), tuple(cast(Box, tuple(c)) for c in t.cells))
                for t in page.find_tables(settings)
            ]
            if found:
                out[page_no] = found
    return out


RULE_PT = 2.0  # a filled rectangle thinner than this is a drawn rule, not a cell's shading


def _rules(page: Any) -> list[dict]:
    """The page's ruling lines: line objects, and rectangles or paths stroked or hairline thin.

    Word and Excel exports often draw rules as thin filled rectangles and shade cells with
    large ones. pdfplumber's default finder takes every rectangle's sides as edges, so a
    shaded band inside a merged cell cuts it into rows that are not drawn (IDSP 2012). Some
    rules are paths instead (IDSP 2011, the Disease column), kept by the same test.
    """
    from pdfplumber.utils import obj_to_edges

    def rule(obj: dict) -> bool:
        return bool(obj.get("stroke")) or min(obj["width"], obj["height"]) < RULE_PT

    def dot(obj: dict) -> bool:
        return max(obj["width"], obj["height"]) <= DOT_PT

    rects = [r for r in page.rects if not dot(r)]
    keep = [*page.lines, *filter(rule, rects), *filter(rule, page.curves)]
    edges = [e for obj in keep for e in obj_to_edges(obj)]  # _tables keeps the h and v ones
    return edges + _dotted([r for r in page.rects if dot(r)])


DOT_PT = 0.6  # a rectangle this small on both sides is a dot of a dotted rule


def _dotted(dots: list[dict]) -> list[dict]:
    """Edges from rules drawn as rows or columns of touching dots."""
    out: list[dict] = []
    for vertical in (True, False):
        lines: dict[float, list[tuple[float, float]]] = {}
        for d in dots:
            at, span = (
                (d["x0"], (d["top"], d["bottom"])) if vertical else (d["top"], (d["x0"], d["x1"]))
            )
            lines.setdefault(round(at * 2) / 2, []).append(span)
        for at, spans in lines.items():
            spans.sort()
            lo, hi = spans[0]
            for a, b in [*spans[1:], (math.inf, math.inf)]:
                if a - hi <= DOT_PT:
                    hi = max(hi, b)
                    continue
                if hi - lo >= 3:  # pt; shorter runs are specks
                    out.append(_edge(at, lo, hi, vertical))
                lo, hi = a, b
    return out


def _edge(at: float, lo: float, hi: float, vertical: bool) -> dict:
    x0, x1, top, bottom = (at, at, lo, hi) if vertical else (lo, hi, at, at)
    return {
        "x0": x0,
        "x1": x1,
        "top": top,
        "bottom": bottom,
        "width": x1 - x0,
        "height": bottom - top,
        "orientation": "v" if vertical else "h",
        "object_type": "dot_edge",
    }
