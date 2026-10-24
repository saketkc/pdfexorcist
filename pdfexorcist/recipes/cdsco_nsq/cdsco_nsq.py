"""CDSCO monthly lists of drugs Not of Standard Quality (NSQ), read through the drawn cells.

Values are keyed by serial number and column. Needs engines that give word boxes.
"""

import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

import pandas as pd

from pdfexorcist import check, grid
from pdfexorcist.cells import Box, _inside
from pdfexorcist.grid import Word

LINE = 3.0  # pt: words whose centres are this close in y are one line
# heading (lower case, spaces dropped) -> column; the first match wins
NAMES = [
    ("sno", r"^s\.?no|^sr|^sl"),
    ("product", r"product|drugname"),
    ("batch", r"batch"),
    ("mfg_date", r"manufactu.*date|mfg"),
    ("expiry_date", r"expiry|exp\.?date"),
    ("manufacturer", r"manufactu"),
    ("result", r"nsq|result|reason"),
    ("lab", r"reported|laborator"),
]
# wrapped lines that meet at a digit join without a space
TIGHT = {"batch", "mfg_date", "expiry_date"}
SERIAL = re.compile(r"^(\d+)\.?$")

Columns = list[tuple[str, Box]]  # (name, a cell of the column) left to right


@dataclass
class Record:
    """One drug batch: its serial number, first and last page, and text by column."""

    sno: str
    page: int
    last: int
    text: dict[str, list[str]] = field(default_factory=dict)  # column -> lines


def _lines(words: list[Word], box: Box) -> list[str]:
    """The text of the words whose centre lies in box, one string per printed line."""
    inside = sorted((w for w in words if _inside(box, *w[1])), key=lambda w: w[1][1] + w[1][3])
    rows: list[list[Word]] = []
    for w in inside:
        mid = (w[1][1] + w[1][3]) / 2
        if rows and abs(mid - (rows[-1][0][1][1] + rows[-1][0][1][3]) / 2) <= LINE:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [" ".join(t for t, _ in sorted(r, key=lambda w: w[1][0])) for r in rows]


def _join(lines: list[str], tight: bool) -> str:
    """One cell's lines as one value.

    A line ending in "-", or a batch number or date broken at a digit (tight), joins
    without a space.
    """
    out = ""
    for ln in lines:
        ln = unicodedata.normalize("NFC", ln).strip()
        if not ln:
            continue
        digit = out[-1:].isdigit() or ln[:1].isdigit()
        glue = "" if not out or out.endswith("-") or (tight and digit) else " "
        out += glue + ln
    return re.sub(r"\s+", " ", out)


def _name(heading: str) -> str | None:
    plain = re.sub(r"\s+", "", heading.lower())
    return next((name for name, pattern in NAMES if re.search(pattern, plain)), None)


def _row(table: grid.Table, cell: Box) -> list[Box]:
    """The drawn cells of the band that cell spans, left to right."""
    top, bottom = cell[1], cell[3]
    return sorted(
        c for c in table.cells if abs(c[1] - top) <= grid.SNAP and abs(c[3] - bottom) <= grid.SNAP
    )


def _first_column(table: grid.Table) -> list[Box]:
    """The drawn cells of the table's first column, top to bottom."""
    return sorted(c for c in table.cells if abs(c[0] - table.bbox[0]) <= grid.SNAP)


def _columns(table: grid.Table, words: list[Word]) -> tuple[Columns, float] | None:
    """The header's cells named by column, and the header's bottom; None without a header."""
    for cell in _first_column(table):
        if _name(" ".join(_lines(words, cell))) != "sno":
            continue
        named = [(_name(" ".join(_lines(words, c))), c) for c in _row(table, cell)]
        cols = [(n, c) for n, c in named if n is not None]
        if [n for n, _ in cols] == [n for n, _ in NAMES]:
            return cols, cell[3]
    return None


def _unnamed(table: grid.Table) -> Columns | None:
    """The columns of a table without a header, by order (a cut that starts mid-list)."""
    first = _first_column(table)
    row = _row(table, first[0]) if first else []
    if len(row) != len(NAMES):
        return None
    return [(n, c) for (n, _), c in zip(NAMES, row, strict=True)]


def _bands(table: grid.Table, x0: float, x1: float, below: float) -> list[tuple[float, float]]:
    """The (top, bottom) of the drawn rows of the column x0..x1 below a y."""
    cells = [c for c in table.cells if abs(c[0] - x0) <= grid.SNAP and abs(c[2] - x1) <= grid.SNAP]
    return sorted({(c[1], c[3]) for c in cells if c[1] >= below - grid.SNAP})


def records(pages: Iterable) -> list[Record]:
    """Every record of the alert, in printed order, with continued rows joined."""
    tables = grid.tables(grid.current_pdf())
    columns: Columns | None = None
    out: list[Record] = []
    for page_no, lines in pages:
        words = grid.words(lines)
        for table in tables.get(page_no, []):
            head = _columns(table, words)
            below = table.bbox[1]
            if head is not None:
                columns, below = head
            elif columns is None:
                columns = _unnamed(table)
            if columns is None or abs(columns[0][1][0] - table.bbox[0]) > grid.SNAP:
                continue  # not the alert table, or a table of another width
            sx0, sx1 = columns[0][1][0], columns[0][1][2]
            for top, bottom in _bands(table, sx0, sx1, below):
                cells = {name: _lines(words, (c[0], top, c[2], bottom)) for name, c in columns}
                sno = _join(cells.pop("sno"), True)
                serial = SERIAL.match(sno)
                if serial:
                    out.append(Record(serial.group(1), page_no, page_no))
                elif not out or out[-1].last < page_no - 1 or not any(cells.values()):
                    continue  # a row continued from a page not read, or a blank row
                elif _name(sno) == "sno":
                    continue  # a repeated header
                out[-1].last = page_no
                for name, text in cells.items():
                    out[-1].text.setdefault(name, []).extend(text)
    return out


def parse(pages: Iterable) -> Iterator[dict]:
    """Yield each record's cells keyed by serial number and column."""
    seen: dict[str, int] = {}
    for rec in records(pages):
        seen[rec.sno] = seen.get(rec.sno, 0) + 1
        sno = rec.sno if seen[rec.sno] == 1 else f"{rec.sno}#{seen[rec.sno]}"
        for name, text in rec.text.items():
            value = _join(text, name in TIGHT)
            if value:
                yield {"sno": sno, "col": name, "value": value, "page": rec.page}


@check("serials run on")
def serials(df: pd.DataFrame) -> pd.Series:
    """Fail a record whose serial number does not follow one read before it, or repeats."""
    m = df["sno"].astype(str).str.extract(r"^(\d+)(#\d+)?$")
    num = pd.to_numeric(m[0], errors="coerce")
    nums = set(num.dropna().astype(int))
    first = min(nums, default=0)
    gap = num.map(lambda n: n == n and n != first and int(n) - 1 not in nums)
    return gap.astype(bool) | m[1].notna() | num.isna()


@check("product and batch given")
def named(df: pd.DataFrame) -> pd.Series:
    """Fail every cell of a record without a product name or a batch number."""
    given = df.groupby("sno")["col"].agg(lambda c: {"product", "batch"} <= set(c))
    return ~df["sno"].map(given).astype(bool)


def checks() -> list:
    """The checks on a read alert."""
    return [serials, named]
