"""Gujarat NVBDCP monthly report (2018-2019 decks): malaria indicators by district by month.

A page is a chart ("Month wise SPR, SFR, MBER and MPI of <district> ...") over a data table:
a row per indicator, a value per month from January of the year before. The months are axis
labels, so a value is keyed by its order (c01: January of the year before). The district and
years are in the title; the caller reads them.
"""

import re
from collections.abc import Iterable, Iterator

from pdfexorcist.rows import Cell, Page

MEASURES = ("SPR", "SFR", "MBER", "MPI")
VALUE = re.compile(r"^\d+(\.\d+)?$")
TITLE = re.compile(r"month\s*wise\s+SPR", re.IGNORECASE)


def _row(cells: list[Cell]) -> tuple[str, list[str]] | None:
    """The indicator and values of a data table row, else None."""
    toks = [t for _, text in cells for t in text.split()]
    if len(toks) < 13 or toks[0].upper() not in MEASURES:
        return None
    values = toks[1:]
    if not all(VALUE.match(v) for v in values):
        return None
    return toks[0].upper(), values


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each value keyed by page, indicator and month order."""
    for page_no, lines in pages:
        if not any(TITLE.search(" ".join(t for _, t in cells)) for cells in lines):
            continue
        seen: set[str] = set()
        for cells in lines:
            row = _row(cells)
            if row is None or row[0] in seen:
                continue
            measure, values = row
            seen.add(measure)
            for i, value in enumerate(values, start=1):
                yield {"page": page_no, "measure": measure, "col": f"c{i:02d}", "value": value}
