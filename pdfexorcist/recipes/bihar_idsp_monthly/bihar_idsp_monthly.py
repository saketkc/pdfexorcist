"""State Health Society Bihar monthly IDSP report: the "Summary of Outbreaks" table.

A row is a disease or syndrome, the district, then outbreaks, cases and deaths. The disease
and district columns are swapped in some months, so their order is taken from the heading.
"""

import re
from collections import Counter
from collections.abc import Iterable, Iterator

from pdfexorcist.rows import Cell, Page

COLS = ("outbreaks", "cases", "deaths")
COUNT = re.compile(r"^\d+$")
TITLE = re.compile(r"summary\s+of\s+outbreaks", re.IGNORECASE)
# the end of the table: a section heading, the page footer or the next table
END = re.compile(r"^\s*(\d+\.\s+\w|data\s+table|monthly\s+communicable|note\b)", re.IGNORECASE)
HEADING = re.compile(r"district|disease|outbreak|cases|deaths|affected", re.IGNORECASE)
TOTAL = re.compile(r"^\s*(grand\s+)?total\b", re.IGNORECASE)


def _clean(text: str) -> str:
    return " ".join(text.split())


def _words(cells: list[Cell]) -> list[Cell]:
    """Cells split into words, each with its cell's x (for engines giving whole lines)."""
    return [(x, t) for x, text in cells for t in [_clean(text)] if t]


def _split(cells: list[Cell]) -> tuple[list[Cell], list[str]]:
    """The label cells of a line and its trailing counts."""
    toks: list[tuple[float, str]] = []
    for x, text in cells:
        toks.extend((x, t) for t in text.split())
    counts: list[str] = []
    while toks and COUNT.match(toks[-1][1]) and len(counts) < len(COLS):
        counts.insert(0, toks.pop()[1])
    label: list[Cell] = []
    for x, t in toks:
        if label and label[-1][0] == x:
            label[-1] = (x, f"{label[-1][1]} {t}")
        else:
            label.append((x, t))
    return label, counts


def _header(lines: list[list[Cell]], start: int) -> tuple[int, bool] | None:
    """Index of the heading line naming the district column, and whether district comes first."""
    for i in range(start, min(start + 8, len(lines))):
        text = " ".join(t for _, t in lines[i]).lower()
        if "district" not in text and "disease" not in text:
            continue
        pos = {
            key: x
            for j in range(max(start, i - 2), min(i + 3, len(lines)))
            for x, t in lines[j]
            for key in ("district", "disease")
            if key in t.lower()
        }
        if "district" in pos and "disease" in pos:
            last = max(
                j
                for j in range(i, min(i + 3, len(lines)))
                if HEADING.search(" ".join(t for _, t in lines[j]))
                and len(_split(lines[j])[1]) < len(COLS)  # "Acute Diarrhoeal Disease ..."
            )
            return last, pos["district"] < pos["disease"]
    # January 2014 heads only the counts: disease and district, in that order, go unnamed
    for i in range(start, min(start + 4, len(lines))):
        if re.search(r"outbreaks", " ".join(t for _, t in lines[i]), re.IGNORECASE):
            return i, False
    return None


class _Row:
    """A table row: its name pieces by column, with the x each column starts at."""

    def __init__(self, label: list[Cell], counts: list[str], district_first: bool) -> None:
        if district_first:
            district, disease = label[:1], label[1:]
        else:
            disease, district = label[:-1], label[-1:]
        self.x = (disease[0][0], district[0][0])
        self.disease = [t for _, t in disease]
        self.district = [t for _, t in district]
        self.counts = counts

    def add(self, pieces: list[Cell], before: bool) -> None:
        """Wrapped pieces of its names, from above (before) or below the line with counts."""
        dis_x, dist_x = self.x
        dis = [t for x, t in pieces if abs(x - dis_x) <= abs(x - dist_x)]
        dist = [t for x, t in pieces if abs(x - dis_x) > abs(x - dist_x)]
        if before:
            self.disease, self.district = dis + self.disease, dist + self.district
        else:
            self.disease, self.district = self.disease + dis, self.district + dist


def _rows(lines: list[list[Cell]], district_first: bool) -> Iterator[tuple[str, str, list[str]]]:
    """(disease, district, counts) of each row down to the Total row.

    A wrapped name's other lines ("Unusual event (related to", "East") mostly print above its
    counts, as Excel puts a wrapped cell's text above its bottom line; they go to the next row."""
    rows: list[_Row] = []
    wrapped: list[Cell] = []
    total: list[str] | None = None
    for cells in lines:
        text = " ".join(t for _, t in cells)
        if END.search(text) or TITLE.search(text):
            break
        label, counts = _split(cells)
        if len(counts) < 2:  # a blank deaths cell leaves two (Nalanda, August 2015)
            pieces = _words(cells) if not counts else []
            # a piece in lower case ends the name above ("water", August 2013)
            if pieces and rows and not wrapped and pieces[0][1][:1].islower():
                rows[-1].add(pieces, before=False)
            else:
                wrapped.extend(pieces)
            continue
        if label and TOTAL.match(label[0][1]):
            total = counts
            break
        if len(label) >= 2:
            rows.append(_Row(label, counts, district_first))
            rows[-1].add(wrapped, before=True)
        wrapped = []
    yield from ((_clean(" ".join(r.disease)), _clean(" ".join(r.district)), r.counts) for r in rows)
    if total is not None:
        yield "Total", "", total


def _table(page_no: int, lines: list[list[Cell]], start: int) -> Iterator[dict]:
    head = _header(lines, start)
    if head is None:
        return
    first, district_first = head
    seen: Counter = Counter()
    for disease, district, counts in _rows(lines[first + 1 :], district_first):
        seen[(disease, district)] += 1
        for col, value in zip(COLS, counts, strict=False):
            yield {
                "disease": disease,
                "district": district,
                "n": str(seen[(disease, district)]),
                "col": col,
                "value": value,
                "page": page_no,
            }


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each count keyed by disease, district, occurrence and column."""
    for page_no, lines in pages:
        for i, cells in enumerate(lines):
            if TITLE.search(" ".join(t for _, t in cells)):
                yield from _table(page_no, lines, i + 1)
