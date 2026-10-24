"""Rural Health Statistics (MoHFW): staff by State/UT, one cadre a table, through drawn cells.

Rows are keyed by table and serial number; the All India row has serial "total". A table
whose header names a column twice, or one not in NAMES, is not read.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import pairwise

from pdfexorcist import grid
from pdfexorcist.cells import _inside
from pdfexorcist.grid import Word

# header text (lower case) -> column; the first match wins
NAMES = [
    ("facilities", r"function"),  # "No. of PHCs functional", "Total Number of CHCs functioning"
    ("sno", r"\bs\.? ?no\b|^s\.?$"),
    ("state", r"state"),
    ("required", r"requir"),
    ("sanctioned", r"sanction"),
    ("in_position", r"in[ -]?position"),
    ("vacant", r"vacan"),
    ("shortfall", r"short ?fall"),
]
VALUES = ("facilities", "required", "sanctioned", "in_position", "vacant", "shortfall")
TABLE = re.compile(r"^table\s*(\d+)\s*-?\s*([a-z])?\b", re.I)
MARKS = re.compile(r"[#@$*\d]+")  # footnote marks after a State name: "Meghalaya #"


@dataclass(frozen=True)
class Columns:
    """A table's columns, (name, x0, x1) left to right, and the bottom of its header."""

    cols: tuple[tuple[str, float, float], ...]
    top: float


def _text(words: list[Word]) -> str:
    return re.sub(r"\s+", " ", " ".join(w[0] for w in words)).strip()


def _name(heading: str) -> str | None:
    plain = heading.lower()
    return next((name for name, pattern in NAMES if re.search(pattern, plain)), None)


def _value(words: list[Word]) -> str:
    """A cell's value: "N App" for Not Applicable, digits without commas."""
    text = "".join(w[0] for w in words).replace(",", "")
    return "N App" if text.lower() == "napp" else text


def _state(label: str) -> tuple[str, str]:
    """(serial, State) for a row: ("", "") for a row without a State."""
    plain = MARKS.sub(" ", label).replace("/", " ")
    plain = re.sub(r"\s+", " ", plain).strip()
    if plain.lower().startswith("all india"):
        return "total", "All India"
    return "", plain


def _lines(words: list[Word]) -> list[str]:
    """The words as printed lines, top to bottom."""
    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w[1][1] + w[1][3]) / 2):
        mid = (w[1][1] + w[1][3]) / 2
        if rows and abs(mid - (rows[-1][0][1][1] + rows[-1][0][1][3]) / 2) <= 4:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [_text(sorted(r, key=lambda w: w[1][0])) for r in rows]


def _title(words: list[Word], top: float) -> tuple[str, str] | None:
    """(number, title) of the table printed above top: ("12", "HEALTH WORKER ...")."""
    lines = _lines([w for w in words if w[1][1] < top])
    for i, line in enumerate(lines):
        m = TABLE.match(line)
        if not m:
            continue
        rest = [line[m.end() :].strip(" ."), *lines[i + 1 :]]
        title = next(
            (t for t in rest if re.search(r"[A-Za-z]{3}", t) and not re.search(r"as on", t, re.I)),
            "",
        )
        return m.group(1) + (m.group(2) or "").upper(), re.sub(r"\s*\(?As on.*$", "", title)
    return None


def _area(title: str) -> str:
    low = title.lower()
    return "tribal" if "tribal" in low else "urban" if "urban" in low else "rural"


def _header(table: grid.Table, words: list[Word], bands: list[float]) -> Columns | None:
    """The columns the header's lowest cells name; None for a table that is not a staff table."""
    x0, _, x1, _ = table.bbox
    data_top = None
    for a, b in pairwise(bands):
        band = sorted(grid.words_in(words, (x0, a, x1, b)), key=lambda w: w[1][0])
        if band and band[0][0] == "1":
            data_top = a
            break
    if data_top is None:
        return None
    leaves = sorted(c for c in table.cells if abs(c[3] - data_top) <= grid.SNAP)
    cols = []
    for c in leaves:
        mid = (c[0] + c[2]) / 2
        stack = [
            h
            for h in table.cells
            if h[0] <= mid <= h[2]
            and h[3] <= data_top + grid.SNAP
            and h[2] - h[0] < 0.6 * (x1 - x0)
        ]  # not a title cell across the table
        name = _name(
            " ".join(_text(grid.words_in(words, h)) for h in sorted(stack, key=lambda h: h[1]))
        )
        if name is None:
            return None
        cols.append((name, c[0], c[2]))
    names = [n for n, _, _ in cols]
    if len(set(names)) < len(names) or not {"state", "sanctioned", "in_position"} <= set(names):
        return None
    return Columns(tuple(cols), data_top)


def parse(pages: Iterable) -> Iterator[dict]:
    """Yield each value of the staff tables keyed by table, serial number and column."""
    tables = grid.tables(grid.current_pdf())
    for page_no, lines in pages:
        if page_no not in tables:
            continue
        words = grid.words(lines)
        for table in tables[page_no]:
            inside = [w for w in words if _inside(table.bbox, *w[1])]
            bands = grid.bands(table)
            columns = _header(table, inside, bands)
            head = _title(words, columns.top) if columns else None
            if columns is None or head is None:
                continue
            number, title = head
            meta = {"table": number, "title": title, "area": _area(title), "page": page_no}
            for a, b in pairwise(bands):
                if a >= columns.top - grid.SNAP:
                    yield from _row(columns, inside, a, b, meta)


def _row(columns: Columns, words: list[Word], a: float, b: float, meta: dict) -> Iterator[dict]:
    """The values of the row between a and b."""
    words = grid.in_band(words, a, b)
    cells = {name: grid.words_in(words, (c0, a, c1, b)) for name, c0, c1 in columns.cols}
    sno = _text(cells.get("sno", []))
    serial, state = _state(_text(cells["state"]))
    if not serial:
        if not re.fullmatch(r"\d+", sno) or not state:
            return
        serial = sno
    for name in VALUES:
        if cells.get(name):
            value = _value(cells[name])
            yield {**meta, "sno": serial, "state": state, "col": name, "value": value}
