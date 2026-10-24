"""India TB Report annexures: State/UT tables read through their drawn cells (grid.Table).

A cell "225 (44.6)" gives value 225 and pct 44.6. Only the kinds in tb_report_names.KINDS
are read. Needs engines that give word boxes.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import pairwise

from tb_report_names import FIRST, fold, kind_of, state

from pdfexorcist import grid
from pdfexorcist.cells import _inside
from pdfexorcist.grid import Word

CAPTION = re.compile(r"^\s*(\d{1,2}(?:\.\d{1,2})?)\.?\s+([A-Za-z].*)$")
CELL = re.compile(r"^(?P<value>[^()]*)(?:\((?P<pct>[^()]*)\))?$")
NUMBER = re.compile(r"\d+(?:\.\d+)?")
BLANK = {"NA", "-", "–", "—", "NR"}  # printed for a value not given


@dataclass(frozen=True)
class Head:
    """A table's columns, (heading, x0, x1) left to right with the label column first, and
    the first row's top."""

    cols: tuple[tuple[str, float, float], ...]
    data_top: float

    @property
    def text(self) -> str:
        return fold(" ".join(h for h, _, _ in self.cols))


@dataclass(frozen=True)
class Named:
    """The table now being read: its key, caption title, kind and header."""

    table: str
    title: str
    kind: str
    head: str


def _text(words: list[Word]) -> str:
    """Words as one line, a word broken after its hyphen rejoined ("Extra-" "pulmonary")."""
    text = re.sub(r"(?<=[a-z])- (?=[a-z])", "-", " ".join(w[0] for w in words))
    return re.sub(r"\s+", " ", text).strip()


def _lines(words: list[Word]) -> list[str]:
    """Words grouped into lines by their middle, top to bottom."""
    out: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w[1][1] + w[1][3]) / 2):
        mid = (w[1][1] + w[1][3]) / 2
        if out and abs(mid - (out[-1][0][1][1] + out[-1][0][1][3]) / 2) < 3:
            out[-1].append(w)
        else:
            out.append([w])
    return [_text(sorted(ws, key=lambda w: w[1][0])) for ws in out]


def _caption(words: list[Word], top: float, floor: float) -> tuple[str, str]:
    """The annexure number and title printed between floor and top, or ("", "")."""
    lines = _lines([w for w in words if floor < (w[1][1] + w[1][3]) / 2 < top])
    for i, line in enumerate(lines):
        m = CAPTION.match(line)
        if m:
            return m[1], " ".join([m[2], *lines[i + 1 :]]).strip()
    return "", ""


def _data_top(table: grid.Table, words: list[Word], bands: list[float]) -> float | None:
    """The top of the first band whose first column names a State; None for another table."""
    xs = grid.snap([c[0] for c in table.cells] + [c[2] for c in table.cells])
    if len(xs) < 3:
        return None
    for a, b in pairwise(bands):
        if state(_text(grid.words_in(words, (xs[0], a, xs[1], b)))):
            return a
    return None


def _head(table: grid.Table, words: list[Word], data_top: float) -> Head | None:
    """The columns the header's lowest cells give; None for a table without a header."""
    above = [c for c in table.cells if c[3] <= data_top + grid.SNAP]
    if not above:
        return None
    leaves = sorted(c for c in above if abs(c[3] - data_top) <= grid.SNAP)
    cols = []
    for c in leaves:
        mid = (c[0] + c[2]) / 2
        stack = sorted((h for h in above if h[0] <= mid <= h[2]), key=lambda h: h[1])
        heading = " / ".join(t for h in stack if (t := _text(grid.words_in(words, h))))
        cols.append((heading, c[0], c[2]))
    return Head(tuple(cols), data_top) if len(cols) > 1 else None


def _cell(words: list[Word]) -> Iterator[tuple[str, str]]:
    """(field, value) of one cell: "225 (44.6)" -> value 225, pct 44.6."""
    text = "".join(w[0] for w in words)
    if not text:
        return
    m = CELL.match(text.replace(",", ""))
    if not m:
        yield "text", _text(words)
        return
    if m["value"] and not (NUMBER.fullmatch(m["value"]) or m["value"] in BLANK):
        yield "text", _text(words)  # a note printed across a row
        return
    if m["value"]:
        yield "value", m["value"]
    if m["pct"] is not None:
        yield "pct", m["pct"].rstrip("%")


def _rows(table: grid.Table, head: Head, words: list[Word], bands: list[float]) -> Iterator[dict]:
    """Each value below the header, keyed by State, column and field."""
    (_, lx0, lx1), *cols = head.cols
    for a, b in pairwise(bands):
        if a < head.data_top - grid.SNAP:
            continue
        row = grid.in_band(words, a, b)
        label = _text(grid.words_in(row, (lx0, a, lx1, b)))
        if not label:
            continue
        cells = [list(_cell(grid.words_in(row, (c0, a, c1, b)))) for _, c0, c1 in cols]
        name = state(label)
        if name is None and any(f == "text" for cell in cells for f, _ in cell):
            continue  # a note printed across the last row ("Note: Numerator is ...")
        for col, ((heading, _, _), cell) in enumerate(zip(cols, cells, strict=True)):
            for field, value in cell:
                yield {"state": name or label, "col": col, "column": heading, "field": field,
                       "value": value}  # fmt: skip


def _named(
    caption: tuple[str, str], head: Head, last: Named | None, first: str, repeats: bool
) -> Named | None:
    """The table a header and caption name: a new one, the one before, or None (not read).

    A page without a caption continues the table before when it prints the same header
    and none of its States.
    """
    number, title = caption
    if not number and last is not None and head.text == last.head and not repeats:
        return last
    kind = kind_of(title, " ".join(h for h, _, _ in head.cols))
    if kind is None or (not number and first != FIRST):
        return None  # a table named by its header alone is read from its first page
    return Named(number or kind, title, kind, head.text)


def parse(pages: Iterable) -> Iterator[dict]:
    """Yield each value of the State/UT tables keyed by table, State, column and field."""
    tables = grid.tables(grid.current_pdf())
    last: Named | None = None
    seen: set[str] = set()  # the States of the table now being read
    for page_no, lines in pages:
        words = grid.words(lines)
        floor = 0.0
        for table in tables.get(page_no, []):
            inside = [w for w in words if _inside(table.bbox, *w[1])]
            bands = grid.bands(table)
            data_top = _data_top(table, inside, bands)
            head = _head(table, inside, data_top) if data_top is not None else None
            if head is None:
                floor = table.bbox[3]
                continue
            caption = _caption(words, table.bbox[1], floor)
            floor = table.bbox[3]
            rows = list(_rows(table, head, inside, bands))
            states = {r["state"] for r in rows}
            first = rows[0]["state"] if rows else ""
            named = _named(caption, head, last, first, bool(states & seen))
            seen = seen | states if named is last else states
            last = named
            if named is None:
                continue
            base = {"page": page_no, "table": named.table, "title": named.title, "kind": named.kind}
            for row in rows:
                yield {**base, **row}
