"""State Health Society Bihar monthly IDSP report: the annexed district sheets.

A sheet is one disease of one IDSP form (P, L or S): a row per district, a column per month
from JAN to the report's month, and a TOTAL row. Its name and year are left to the caller,
so a row is keyed by page, table number on the page, district and month as printed.
"""

import re
from collections.abc import Iterable, Iterator

from pdfexorcist.rows import Cell, Page

MONTH = re.compile(
    r"^(JAN|FEB|MAR|APR|MAY|JUNE?|JULY?|AUG|SEPT?|OCT|NOV|DEC)[A-Z]*\.?$", re.IGNORECASE
)
# kept as printed: a leading "*" (2012 sheets, unexplained), "NA", and Excel's overflow
# ("1E+05", which the lossy check flags)
COUNT = re.compile(r"^(\*?\d+|NA|\d(\.\d+)?E\+\d+)$")
GLUED = re.compile(r"^(.*[A-Za-z)])(\d+)$")  # "(BETTIAH)0"
SERIAL = re.compile(r"^\d+\.?$")
HEAD_WORD = re.compile(r"^(S\.?\s*NO\.?|SL\.?|NO\.?|SNO|DISTRICT)$", re.IGNORECASE)
TOTAL = re.compile(r"^(grand\s+)?total$", re.IGNORECASE)


def _tokens(cells: list[Cell]) -> list[tuple[float, str]]:
    """Whitespace-separated tokens, each with its cell's x, a count glued on split off."""
    out: list[tuple[float, str]] = []
    for x, text in cells:
        for t in text.split():
            m = GLUED.match(t)
            out.extend([(x, m.group(1)), (x, m.group(2))] if m and not t.isdigit() else [(x, t)])
    return out


def _months(toks: list[tuple[float, str]]) -> list[tuple[float, str]] | None:
    """The month headings of a line naming at least two months, else None."""
    found = [(x, t.upper().rstrip(".")[:3]) for x, t in toks if MONTH.match(t)]
    if not found or found[0][1] != "JAN":
        return None
    # a January report heads one month: take it only on a line of headings
    rest = [t for _, t in toks if not MONTH.match(t)]
    return found if len(found) >= 2 or all(HEAD_WORD.match(t) for t in rest) else None


def _place(counts: list[tuple[float, str]], heads: list[tuple[float, str]]) -> dict[str, str]:
    """Counts by month: in order when all are there, else by nearest heading (a blank cell)."""
    if len(counts) == len(heads):
        return {m: v for (_, m), (_, v) in zip(heads, counts, strict=True)}
    out: dict[str, str] = {}
    for x, v in counts:
        month = min(heads, key=lambda h: abs(h[0] - x))[1]
        if month in out:  # two counts under one heading: the row cannot be placed
            return {}
        out[month] = v
    return out


def _row(toks: list[tuple[float, str]]) -> tuple[str, list[tuple[float, str]]]:
    """The name (upper case, may be empty) and trailing counts of a line."""
    counts: list[tuple[float, str]] = []
    while toks and COUNT.match(toks[-1][1]) and not (len(toks) == 1 and toks[0][1] == "NA"):
        counts.insert(0, toks.pop())
    while toks and SERIAL.match(toks[0][1]):
        toks = toks[1:]
    name = " ".join(t for _, t in toks)
    return ("Total" if TOTAL.match(name) else name.upper()), counts


class _Table:
    """One sheet's rows, a name wrapped over the lines round its counts joined back."""

    def __init__(self, heads: list[tuple[float, str]]) -> None:
        self.heads = heads
        self.rows: list[list] = []  # [name, counts, open for a wrapped name below]
        self.above: list[str] = []

    def add(self, name: str, counts: list[tuple[float, str]]) -> None:
        if not counts:
            if not re.search(r"[A-Za-z]{1}", name):
                return
            if self.rows and self.rows[-1][2]:
                self.rows[-1][0] = f"{self.rows[-1][0]} {name}".strip()
                self.rows[-1][2] = False
            else:
                self.above.append(name)
            return
        wrapped = not name
        if wrapped and len(counts) == len(self.heads) + 1 and counts[0][1].isdigit():
            counts = counts[1:]  # the serial, its name wrapped round the line
        if len(counts) > len(self.heads):
            return  # a date or a note, not a row of this table
        above = " ".join(self.above)
        if wrapped or len(above) <= 5:  # "W" over "CHAMPARAN 2 18 ..."
            name = f"{above} {name}".strip()
        self.above = []
        if self.rows:
            self.rows[-1][2] = False
        self.rows.append([name, counts, wrapped])

    def cells(self, page_no: int, table: int) -> Iterator[dict]:
        for name, counts, _ in self.rows:
            if not re.search(r"[A-Za-z]{3}", name):
                continue
            for month, value in _place(counts, self.heads).items():
                yield {
                    "page": page_no,
                    "table": str(table),
                    "district": name,
                    "col": month,
                    "value": value,
                }


def _page(page_no: int, lines: list[list[Cell]]) -> Iterator[dict]:
    table: _Table | None = None
    n = 0
    for cells in lines:
        toks = _tokens(cells)
        if found := _months(toks):
            if table:
                yield from table.cells(page_no, n)
            table, n = _Table(found), n + 1
            continue
        if table is None:
            continue
        name, counts = _row(toks)
        table.add(name, counts)
        if name == "Total" and counts:
            yield from table.cells(page_no, n)
            table = None
    if table:
        yield from table.cells(page_no, n)


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each count keyed by page, table, district and month."""
    for page_no, lines in pages:
        yield from _page(page_no, lines)
