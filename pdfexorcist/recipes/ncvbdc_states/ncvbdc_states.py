"""NCVBDC State/UT tables: cases and deaths (or tests) by year, one page per disease.

A cell merged over several columns ("NR" over a year) gives its text to each. Values stay
as printed ("30683*"); add_number gives the checks a number. Needs word boxes.
"""

import re
from collections.abc import Iterable, Iterator
from itertools import pairwise

import pandas as pd

from pdfexorcist import grid
from pdfexorcist.cells import Box, _inside
from pdfexorcist.grid import Word

YEAR = re.compile(r"^((?:19|20)\d\d)\b\W*(.*?)\W*$", re.S)
DISEASE = re.compile(r"dengue|chikungunya|malaria|kala.?azar|japanese encephalitis|filaria", re.I)
TOTAL = re.compile(r"^(total|india|all india)$", re.I)
NUMBER = re.compile(r"\d")
SERIAL = re.compile(r"(?:^|(?<=\s))(\d{1,2})(?=\s|[A-Z]|$)")

Column = tuple[str, str, str, float, float]  # year, period, measure, x0, x1


def _text(words: list[Word], box: Box | None) -> str:
    """The words whose centre lies in box, top to bottom then left to right."""
    if box is None:
        return ""
    inside = sorted(
        (w for w in words if _inside(box, *w[1])), key=lambda w: (round(w[1][1] / 4), w[1][0])
    )
    return re.sub(r"\s+", " ", " ".join(w[0] for w in inside)).strip()


def _header(table: grid.Table, words: list[Word]) -> tuple[list[Column], Box, Box, float] | None:
    """The value columns, the State and serial label columns, and the header's bottom.

    None for a table without a year over its measures.
    """
    years = [(c, m) for c in table.cells if (m := YEAR.match(_text(words, c)))]
    cols: list[Column] = []
    bottoms = []
    for cell, m in years:
        leaves = [
            c
            for c in table.cells
            if abs(c[1] - cell[3]) <= grid.SNAP
            and c[0] >= cell[0] - grid.SNAP
            and c[2] <= cell[2] + grid.SNAP
        ]
        for leaf in sorted(leaves):
            measure = re.sub(r"\s+", " ", _text(words, leaf).lower())
            if measure and not NUMBER.search(measure):
                cols.append((m[1], " ".join(m[2].split()), measure, leaf[0], leaf[2]))
                bottoms.append(leaf[3])
    if not cols:
        return None
    left, data_top = min(c[3] for c in cols), max(bottoms)
    labels = sorted(
        c
        for c in table.cells
        if c[2] <= left + grid.SNAP
        and c[1] < data_top - grid.SNAP
        and abs(c[3] - data_top) <= grid.SNAP
    )
    state = next((c for c in labels if "state" in _text(words, c).lower()), None)
    if state is None:
        return None
    sno = next((c for c in labels if c[2] <= state[0] + grid.SNAP), state)
    return sorted(cols, key=lambda c: c[3]), state, sno, data_top


def _serial(label: str) -> tuple[str, str]:
    """Split a serial number from the State's text: ("1", "Andaman And Nicobar Islands").

    An engine may read the serial into the name, glued to a word ("2Andhra Pradesh").
    """
    m = SERIAL.search(label)
    if m is None:
        return "", label
    return m[1], " ".join((label[: m.start()] + " " + label[m.end() :]).split())


def _disease(words: list[Word], top: float) -> str:
    """The disease named in the title above the table, lower case."""
    above = sorted((w for w in words if w[1][3] <= top), key=lambda w: (w[1][1], w[1][0]))
    title = " ".join(w[0] for w in above)
    m = DISEASE.search(title)
    return m[0].lower() if m else ""


def parse(pages: Iterable) -> Iterator[dict]:
    """Yield each value keyed by page, State/UT and column ("2023 cases")."""
    tables = grid.tables(grid.current_pdf())
    for page_no, lines in pages:
        words = grid.words(lines)
        for table in tables.get(page_no, []):
            inside = [w for w in words if _inside(table.bbox, *w[1])]
            head = _header(table, inside)
            if head is None:
                continue
            cols, state_col, sno_col, data_top = head
            disease = _disease(words, table.bbox[1])
            edges = grid.snap(
                e for c in table.cells if c[1] >= data_top - grid.SNAP for e in (c[1], c[3])
            )
            for a, b in pairwise(edges):
                y = (a + b) / 2
                state_cell = table.at((state_col[0] + state_col[2]) / 2, y)
                sno_cell = table.at((sno_col[0] + sno_col[2]) / 2, y)
                glued, state = _serial(_text(inside, state_cell))
                sno = glued if sno_cell == state_cell else _text(inside, sno_cell) or glued
                if not state:
                    continue
                if TOTAL.match(state):
                    state, sno = "Total", ""
                for year, period, measure, x0, x1 in cols:
                    value = _text(inside, table.at((x0 + x1) / 2, y))
                    if not value:
                        continue
                    if NUMBER.search(value):
                        value = value.replace(" ", "")
                    yield {
                        "page": page_no,
                        "state": state,
                        "col": f"{year} {measure}",
                        "sno": sno,
                        "disease": disease,
                        "year": year,
                        "period": period,
                        "measure": measure,
                        "value": value,
                    }


def add_number(cells: pd.DataFrame, pdf: object) -> pd.DataFrame:
    """Add the value as a number for the checks: "30683*" -> 30683, "NR" -> empty."""
    text = cells["value"].astype(str).str.rstrip("*")
    return cells.assign(number=pd.to_numeric(text, errors="coerce"))
