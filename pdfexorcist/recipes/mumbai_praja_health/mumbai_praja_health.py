"""Praja Foundation's Mumbai health white papers: registered cases by BMC ward, one disease a table.

Years are financial years ("2015-16") up to the 2018 edition and calendar years from 2019.
Population and rate columns are left out. A value goes to the nearest heading on its own
engine's reading, so a blank cell (a hospital with no figure for an early year) stays blank.
"""

import re
from collections.abc import Iterable, Iterator
from itertools import pairwise

from pdfexorcist.cells import word_xs
from pdfexorcist.rows import Page, is_value

TITLE = re.compile(
    r"Table\s*(?P<no>\d+)\s*:?\s*Ward\s*-?\s*wise\s*\d*\s+(?:registered\s+cases\s+of\s+)?"
    r"(?P<disease>[A-Za-z]+)",
    re.IGNORECASE,
)
DISEASES = {
    "malaria": "Malaria",
    "dengue": "Dengue",
    "tb": "Tuberculosis",
    "tuberculosis": "Tuberculosis",
    "diabetes": "Diabetes",
    "diarrhoea": "Diarrhoea",
    "diarrhea": "Diarrhoea",
    "hypertension": "Hypertension",
    "hiv": "HIV",
    "typhoid": "Typhoid",
}
FY = re.compile(r"^((?:19|20)\d\d)\s*[-–]\s*(\d\d)$")  # 2011-12
CY = re.compile(r"^(?:19|20)\d\d$")  # 2014
# headings of columns left out: population, the rate per 1,00,000 and its footnote marks
OTHER = re.compile(r"^(population\d*|average|cases\*?/?|1,00,000|provisional|2011\*?)$", re.I)
WARD = re.compile(r"^([A-Z])(?:\s*/\s*([A-Z]))?$")
Token = tuple[float, str]


def _period(word: str, fiscal: bool) -> str | None:
    """A year heading as printed ("2011-12", "2014"), or None."""
    m = FY.match(word)
    if m:
        return f"{m[1]}-{m[2]}"
    # beside financial years, a bare year is the population census ("Population 2011")
    return word if CY.match(word) and not fiscal else None


def _header(line: list[Token]) -> list[Token] | None:
    """The (x, column) anchors of a heading line with three or more years, or None."""
    fiscal = any(FY.match(t) for _, t in line)
    cols = [(x, p) for x, t in line if (p := _period(t, fiscal))]
    if len(cols) < 3:
        return None
    total = [(x, "Total") for x, t in line if t.lower() == "total" and x > cols[-1][0]]
    return cols + total[:1]


def _row(label: str) -> tuple[str, str] | None:
    """The row key and its kind (ward, hospital, dispensaries, total), or None."""
    text = re.sub(r"[*#]+", "", label).strip()
    m = WARD.match(text)
    if m:
        return (f"{m[1]}/{m[2]}" if m[2] else m[1]), "ward"
    low = text.lower()
    if "dispensar" in low and "total" in low:
        return "Total Municipal Dispensaries", "dispensaries"
    if low == "total":
        return "Total", "total"
    if "hospital" in low:
        if "municipal" in low:
            return "Municipal Hospital", "hospital"
        if "state" in low:
            return "State Hospital", "hospital"
        if "gov" in low:
            return "Other Government Hospital", "hospital"
    return None


def _place(x: float, anchors: list[Token], gap: float) -> str | None:
    """The column whose heading is nearest x, if within a column's width."""
    ax, col = min(anchors, key=lambda a: abs(a[0] - x))
    return col if abs(ax - x) <= gap else None


def _table(lines: list[list[Token]], start: int) -> Iterator[tuple[str, str, str, str]]:
    """(row, kind, column, value) for the table whose heading line is lines[start]."""
    head = _header(lines[start])
    if head is None:
        return
    xs = [x for x, _ in head]
    gap = min(b - a for a, b in pairwise(xs))
    # other headings, above or just below the year line, keep their values out of the years
    others = [
        (x, "") for line in lines[max(start - 4, 0) : start + 3] for x, t in line if OTHER.match(t)
    ]
    anchors = head + others
    started, wrapped = False, ""
    for line in lines[start + 1 :]:
        label = " ".join(t for _, t in line if not is_value(t))
        values = [(x, t) for x, t in line if is_value(t)]
        if started and not values and label and not wrapped:
            wrapped = label  # "Other Government" over "Hospital 593 606 ..."
            continue
        row = _row(f"{wrapped} {label}".strip()) if values else None
        wrapped = ""
        if row is None:
            if started:
                return  # the line after the last row
            continue
        started = True
        cols: dict[str, str] = {}
        for x, t in values:
            col = _place(x, anchors, gap)
            if col:
                cols[col] = "" if col in cols else t  # two values under one heading: unread
        for col, v in cols.items():
            if v:
                yield row[0], row[1], col, v
        if row[1] == "total":
            return


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each count keyed by table, row (ward code or hospital) and column (period)."""
    for page_no, raw in pages:
        lines = [word_xs(cells) for cells in raw]
        title = None
        for i, line in enumerate(lines):
            text = " ".join(t for _, t in line)
            m = TITLE.search(text)
            if m:
                disease = DISEASES.get(m["disease"].lower())
                # the 2012 edition also prints survey estimates by ward
                title = None if disease is None or "survey" in text.lower() else (m, disease)
                continue
            if title is None or _header(line) is None:
                continue
            m, disease = title
            for row, kind, col, value in _table(lines, i):
                yield {
                    "table": f"Table {m['no']}",
                    "disease": disease,
                    "row": row,
                    "kind": kind,
                    "col": col,
                    "value": value,
                    "page": page_no,
                }
            title = None
