"""Karnataka daily dengue and chikungunya report (NVBDCP): counts by district.

Columns are named by their place (COLUMNS): engines misread the sideways headings. The
Bangaluru City (BBMP) table draws no header and keeps the columns of the table above it.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import pairwise

from pdfexorcist import grid
from pdfexorcist.cells import Box, _inside
from pdfexorcist.grid import Word

TESTS = ["suspected", "sampled", "igm", "ns1", "positive", "deaths"]
# the lowest header cells, left to right; ns1 is "Others" on the chikungunya page
COLUMNS = (
    ["sl", "district", "blocks", "taluks", "phc", "villages", "population"]
    + [f"day_{t}" for t in TESTS]
    + [f"cum_{t}" for t in TESTS]
    + ["remarks"]
)
SKIP = {"sl", "district", "remarks"}
NUMBER = re.compile(r"^\d+$")
DISEASE = re.compile(r"daily report of (\w+)", re.I)


@dataclass(frozen=True)
class Columns:
    """A table's columns, (name, x0, x1) left to right, and its x span."""

    cols: tuple[tuple[str, float, float], ...]

    @property
    def span(self) -> tuple[float, float]:
        return self.cols[0][1], self.cols[-1][2]


def _text(words: list[Word]) -> str:
    return re.sub(r"\s+", " ", " ".join(w[0] for w in words)).strip()


def district(label: str) -> str:
    """The printed name, spaced alike by every engine: "Bangaluru(U)" -> "Bangaluru (U)"."""
    label = re.sub(r"\s*\(\s*", " (", re.sub(r"\s*\)", ")", label))
    return re.sub(r"\s+", " ", label).strip()


def _fits(word: Box, cell: Box) -> bool:
    """Whether a word is no wider and no taller than a cell (it may overlap a rule)."""
    w, h = word[2] - word[0], word[3] - word[1]
    return w <= cell[2] - cell[0] + grid.SNAP and h <= cell[3] - cell[1] + grid.SNAP


def _data_top(words: list[Word], bands: list[float], x0: float, x1: float) -> float | None:
    """The top of the first band with three whole numbers; None for a table without one.

    A heading holds a number ("NS 1").
    """
    for a, b in pairwise(bands):
        if sum(bool(NUMBER.match(w[0])) for w in words if _inside((x0, a, x1, b), *w[1])) >= 3:
            return a
    return None


def _header(table: grid.Table, words: list[Word], data_top: float, disease: str) -> Columns | None:
    """The columns under the header; None for a table that is not a report."""
    leaves = sorted(c for c in table.cells if abs(c[3] - data_top) <= grid.SNAP)
    x0, top, x1, _ = table.bbox
    heading = re.sub(r"[^a-z]", "", _text(grid.words_in(words, (x0, top, x1, data_top))).lower())
    if len(leaves) != len(COLUMNS) or "district" not in heading or "cum" not in heading:
        return None
    names = COLUMNS
    if disease == "Chikungunya":
        names = [n.replace("ns1", "others") for n in COLUMNS]
    return Columns(tuple((n, c[0], c[2]) for n, c in zip(names, leaves, strict=True)))


def parse(pages: Iterable) -> Iterator[dict]:
    """Yield each count keyed by disease, district and column."""
    tables = grid.tables(grid.current_pdf())
    for page_no, lines in pages:
        words = grid.words(lines)
        title = DISEASE.search(" ".join(w[0] for w in words))
        disease = title.group(1).capitalize() if title else ""
        columns: Columns | None = None
        for table in tables.get(page_no, []):
            x0, top, x1, _ = table.bbox
            inside = [w for w in words if _inside(table.bbox, *w[1])]
            bands = grid.bands(table)
            data_top = _data_top(inside, bands, x0, x1)
            if data_top is None:
                continue
            if data_top - top > grid.SNAP:  # a header: the main table
                columns = _header(table, inside, data_top, disease)
            elif columns is None or any(
                abs(a - b) > 6 for a, b in zip(columns.span, (x0, x1), strict=True)
            ):
                columns = None
            if columns is None:
                continue
            for a, b in pairwise(bands):
                if a >= data_top - grid.SNAP:
                    yield from _row(table, columns, inside, (a, b), disease, page_no)


def _row(
    table: grid.Table,
    columns: Columns,
    words: list[Word],
    band: tuple[float, float],
    disease: str,
    page_no: int,
) -> Iterator[dict]:
    """The values of the row in band (top, bottom)."""
    a, b = band
    words = grid.in_band(words, a, b)
    label = ""
    values = {}
    for name, c0, c1 in columns.cols:
        if name == "district":
            # BBMP's name is printed in one cell across the SL and district columns
            box = table.at((c0 + c1) / 2, (a + b) / 2) or (c0, a, c1, b)
            label = district(_text(grid.words_in(words, box)))
        elif name not in SKIP:
            # pdfium may give the sideways remarks as one word whose centre is in this cell
            box = (c0, a, c1, b)
            inside = [w for w in grid.words_in(words, box) if _fits(w[1], box)]
            text = "".join(w[0] for w in inside)
            if text:
                values[name] = text
    if not label:
        return
    for name, value in values.items():
        yield {"disease": disease, "district": label, "col": name, "value": value, "page": page_no}
