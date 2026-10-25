"""Praja Foundation's Delhi health reports: registered cases by MCD zone, one disease a table.

Zone tables (2017 to 2022) have a row per zone; Delhi tables (2017 to 2024) a row per MCD or
state facility. Both have a column a year: calendar years in 2017, 2022 and 2024, financial
years ("2015-16") in 2018 and 2019. The % change, population and rate columns are left out.
"""

import re
from collections.abc import Iterable, Iterator
from itertools import pairwise

from pdfexorcist.cells import word_xs
from pdfexorcist.rows import Page, is_value

ZONE_TITLE = re.compile(
    r"Table\s*(?P<no>\d+)\s*:?\s*Zone\s*-?\s*wise\s+(?P<disease>[A-Za-z]+)\s+(?:Data|cases)",
    re.IGNORECASE,
)
DELHI_TITLE = re.compile(
    r"Table\s*(?P<no>\d+)\s*:?\s*(?:Number\s+of\s+|Registered\s+)?(?P<disease>[A-Za-z]+)\s+"
    r"(?:number\s+of\s+)?cases\s+(?:registered\s+)?in\s+government",
    re.IGNORECASE,
)
DISEASES = {
    "malaria": "Malaria",
    "dengue": "Dengue",
    "tuberculosis": "Tuberculosis",
    "tb": "Tuberculosis",
    "diarrhoea": "Diarrhoea",
    "diarrhea": "Diarrhoea",
    "cholera": "Cholera",
    "typhoid": "Typhoid",
    "hepatitis": "Hepatitis",
    "hiv": "HIV",
    "diabetes": "Diabetes",
    "hypertension": "Hypertension",
}
# printed zone name (letters only, lower case) -> zone
ZONES = {
    "shahdaranorth": "Shahdara North",
    "shahdarasouth": "Shahdara South",
    "city": "City",
    "ruralnarela": "Rural Narela",
    "narela": "Rural Narela",
    "karolbagh": "Karol Bagh",
    "rohini": "Rohini",
    "sadarpaharganj": "Sadar Paharganj",
    "civillines": "Civil Lines",
    "civilline": "Civil Lines",
    "keshavpuram": "Keshav Puram",
    "cityandsadarpaharganj": "City and Sadar Paharganj",
    "citysadarpaharganj": "City and Sadar Paharganj",
    "central": "Central",
    "west": "West",
    "south": "South",
    "najafgarh": "Najafgarh",
    "newdelhimunicipalcouncil": "New Delhi Municipal Council",
    "total": "Total",
}
# corporations printed beside zone rows (NDMC: North Delhi Municipal Corporation)
CORPORATIONS = re.compile(r"^(?:EDMC|NDMC|SDMC|MCD)\s+", re.IGNORECASE)
FY = re.compile(r"^((?:19|20)\d\d)\s*[-–]\s*(\d\d)$")  # 2014-15
CY = re.compile(r"^(?:19|20)\d\d$")
# headings of columns left out, above or just below the year line
OTHER = re.compile(r"^(population\d*|change|%|corporation)$", re.IGNORECASE)
FOOTNOTE = re.compile(r"^(NA|-)\d{1,2}$")  # "NA17": NA with its footnote mark
# lines inside a Delhi table that are not rows of counts
DELHI_SKIP = re.compile(r"population|total\s*cases\s*/|number\s+of|/\s*total", re.IGNORECASE)
# "MCD Hospital", "Dispensaries" (the corporation printed beside the row above), and
# "State dispensaries/hospitals" or "... and hospitals" (both, 2017 to 2019)
FACILITY = re.compile(
    r"^(?:(mcd|state)\s*)?(dispensar\w*|hospital\w*|total)(\s*(?:/|and)\s*hospitals?)?$"
)
Token = tuple[float, str]


def _clean(line: list[Token]) -> list[Token]:
    return [(x, "NA" if FOOTNOTE.match(t) else t) for x, t in line]


def _header(line: list[Token]) -> list[Token] | None:
    """The (x, column) anchors of a line with three or more years, or None."""
    fiscal = any(FY.match(t) for _, t in line)
    cols: list[Token] = []
    for i, (x, t) in enumerate(line):
        census = i > 0 and line[i - 1][1].lower() == "population"  # "Population 2011"
        m = FY.match(t)
        period = f"{m[1]}-{m[2]}" if m else t if CY.match(t) and not fiscal else None
        # a year again is the "% Change 2022 to 2023" heading beside the years
        if period and not census and period not in {c for _, c in cols}:
            cols.append((x, period))
    if len(cols) < 3:
        return None
    total = [(x, "Total") for x, t in line if t.lower() == "total" and x > cols[-1][0]]
    return cols + total[:1]


def _place(x: float, anchors: list[Token], gap: float) -> str | None:
    """The column whose heading is nearest x, if within a column's width."""
    ax, col = min(anchors, key=lambda a: abs(a[0] - x))
    return col if abs(ax - x) <= gap else None


def _zone_row(label: str) -> tuple[str, str] | None:
    # (zone, kind) of a zone table row; a corporation prefix ("EDMC") is dropped
    text = CORPORATIONS.sub("", re.sub(r"[*#\d]+", "", label).strip())
    zone = ZONES.get(re.sub(r"[^a-z]", "", text.lower().replace("&", "and")))
    if zone is None:
        return None
    return zone, "total" if zone == "Total" else "zone"


def _delhi_row(label: str, group: str) -> tuple[str, str] | None:
    """The row of a Delhi table; group is the corporation of an unprefixed row.

    2017 to 2019 print one row each for MCD and state. 2022 and 2024 split them into
    dispensaries and hospitals and print the corporation once beside its rows.
    """
    low = re.sub(r"[*#\d]+", "", label).strip().lower()
    if DELHI_SKIP.search(low):
        return None
    if "death" in low:
        return "Total Deaths", "deaths"
    if low == "total cases":
        return "Total Cases", "delhi"
    m = FACILITY.match(low)
    if m is None:
        return None
    who = "MCD" if (m[1] or group) == "mcd" else "State"
    what = "Total" if m[3] else {"d": "Dispensaries", "h": "Hospital", "t": "Total"}[m[2][0]]
    return f"{who} {what}", "delhi"


def _table(lines: list[list[Token]], start: int, zone: bool) -> Iterator[tuple[str, str, str, str]]:
    """(row, kind, column, value) for the table whose year line is lines[start]."""
    head = _header(lines[start])
    if head is None:
        return
    gap = min(b - a for a, b in pairwise(x for x, _ in head))
    others = [
        (x, "")
        for i in range(max(start - 4, 0), min(start + 4, len(lines)))
        for j, (x, t) in enumerate(lines[i])
        if OTHER.match(t) or (j > 0 and lines[i][j - 1][1].lower() == "population")
    ]
    used = {x for x, _ in head}
    years = [(x, "") for x, t in lines[start] if x not in used and (CY.match(t) or FY.match(t))]
    anchors = head + others + years
    started, held, group = False, "", "mcd"
    for line in lines[start + 1 :]:
        label = " ".join(t for _, t in line if not is_value(t))
        values = [(x, t) for x, t in line if is_value(t)]
        if not label:
            continue  # a footnote mark, or the "2022 to 2023" under "% Change"
        if not values:
            if started:
                held = label  # a corporation printed alone, or the first part of a label
            continue
        text = f"{held} {label}".strip()
        held = ""
        row = (_zone_row(text) or _zone_row(label)) if zone else _delhi_row(label, group)
        if row is None:
            if zone and CORPORATIONS.match(f"{label} "):
                continue  # "EDMC 34,00,000": the corporation and its population
            if not zone and (DELHI_SKIP.search(label) or not started):
                continue
            if started:
                return
            continue
        started = True
        if row[0] == "MCD Total":
            group = "state"  # unprefixed rows after it are the state's
        cols: dict[str, str] = {}
        for x, t in values:
            col = _place(x, anchors, gap)
            if col:
                cols[col] = "" if col in cols else t  # two values under one heading: unread
        for col, v in cols.items():
            if v:
                yield row[0], row[1], col, v
        if row[1] in ("total", "deaths"):
            return


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each count keyed by table, row (zone or facility type) and column (period)."""
    for page_no, raw in pages:
        lines = [_clean(word_xs(cells)) for cells in raw]
        title = None
        for i, line in enumerate(lines):
            text = " ".join(t for _, t in line)
            m = ZONE_TITLE.search(text) or DELHI_TITLE.search(text)
            if m:
                disease = DISEASES.get(m["disease"].lower())
                title = None if disease is None else (m, disease, m.re is ZONE_TITLE)
                continue
            if title is None or _header(line) is None:
                continue
            m, disease, zone = title
            for row, kind, col, value in _table(lines, i, zone):
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
