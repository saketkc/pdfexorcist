"""Meghalaya IDSP monthly bulletin: surveillance totals, outbreaks by district, influenza tests.

The first page sets two or three panels side by side on one line, so each count is found by
the words around it.
"""

import re
from collections.abc import Iterable, Iterator

from pdfexorcist.rows import Cell, Page

SURVEILLANCE = ("syndromic", "presumptive", "laboratory")
HEADINGS = {
    "cases": "cases",
    "deaths": "deaths",
    "samples tested": "samples_tested",
    "positive": "positive",
}
# "Reporting Status: 87.61%"; in 2023 one heading before the three ("88.91% 90.87% 91.75%")
STATUS = re.compile(r"Reporting Status:?((?:\s+\d+(?:\.\d+)?%?)+)", re.I)
# the three summary counts after "Period:", or in 2023 after "(01st Jan - ...)"
PERIOD = re.compile(
    r"(?:Period:?|Jan\w*\s*[–-]\s*\d+\w*\s+\w+\s+\d{4}\)?)\s+(\d+)\s+(\d+)\s+(\d+)\b", re.I
)
SUMMARY = ("event_alerts", "ongoing_outbreaks", "outbreaks")
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
# a row of the influenza table, from October 2025 on ("Jan-26" and five counts)
FLU = re.compile(r"^([A-Za-z]{3,9})\s*[-–]\s*(\d{2})((?:\s+\d+){5})$")
FLU_COLS = ("tested", "h1n1", "h3n2", "rsv", "covid19")
DISTRICT = re.compile(r"^(Meghalaya|[A-Za-z][A-Za-z -]*(?:Hills|Bhoi))$")
COUNT = re.compile(r"^\d[\d,]*$")


def _text(cells: list[Cell]) -> str:
    return " ".join(" ".join(t.split()) for _, t in cells).strip()


def _row(table: str, row: str, col: str, value: str, page: int) -> dict:
    return {"table": table, "row": row, "col": col, "value": value, "page": page}


def _headings(cells: list[Cell]) -> list[str]:
    """The count headings on a line, left to right; [] for a line without a pair of them."""
    found = [HEADINGS[t.lower()] for _, t in cells if t.lower() in HEADINGS]
    pair = "cases" in found or "samples_tested" in found
    return found if len(found) >= 2 and pair else []


def _leading_counts(cells: list[Cell], n: int) -> list[str] | None:
    """The first n cells, when each is a count."""
    vals = [t for _, t in cells[:n]]
    return vals if len(vals) == n and all(COUNT.match(v) for v in vals) else None


def _surveillance(page_no: int, lines: list[list[Cell]]) -> Iterator[dict]:
    status = [
        v.rstrip("%") for cells in lines for m in STATUS.findall(_text(cells)) for v in m.split()
    ]
    for name, value in zip(SURVEILLANCE, status, strict=False):
        yield _row("surveillance", name, "reporting_status", value, page_no)
    blocks = iter(SURVEILLANCE)
    # Cases/Deaths and Samples Tested/Positive headings print in bulletins from 2025 on
    for i, cells in enumerate(lines):
        heads = _headings(cells)
        if not heads:
            continue
        # the counts print on the line above their headings (an empty line may come between)
        values = next(
            (
                v
                for c in reversed(lines[max(0, i - 3) : i])
                if (v := _leading_counts(c, len(heads)))
            ),
            None,
        )
        # one heading line per panel: syndromic and presumptive side by side, then laboratory
        names = [next(blocks, None) for _ in range(len(heads) // 2)]
        if values is None or None in names:
            continue
        for j, (head, value) in enumerate(zip(heads, values, strict=True)):
            yield _row("surveillance", str(names[j // 2]), head, value, page_no)


def _outbreaks(page_no: int, lines: list[list[Cell]]) -> Iterator[dict]:
    # the "No. of outbreaks reported" panel: each name and its count in Meghalaya's column
    found: list[tuple[str, str, float]] = []
    for cells in lines:
        for k, (_, label) in enumerate(cells[:-1]):
            name = " ".join(label.split())
            x, value = cells[k + 1]
            after = cells[k + 2][1] if k + 2 < len(cells) else ""
            if DISTRICT.match(name) and COUNT.match(value) and not COUNT.match(after):
                found.append((name, value, x))
    anchor = next((x for name, _, x in found if name == "Meghalaya"), None)
    if anchor is None:
        return
    width = max((c[0] for cells in lines for c in cells), default=1.0)
    for name, value, x in found:
        if abs(x - anchor) <= 0.06 * width:
            yield _row("outbreaks", name, "outbreaks", value, page_no)


def _influenza(page_no: int, lines: list[list[Cell]]) -> Iterator[dict]:
    for cells in lines:
        m = FLU.match(_text(cells))
        if not m or m.group(1)[:3].lower() not in MONTHS:
            continue
        month = f"20{m.group(2)}-{MONTHS.index(m.group(1)[:3].lower()) + 1:02d}"
        for col, value in zip(FLU_COLS, m.group(3).split(), strict=True):
            yield _row("influenza", month, col, value, page_no)


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each count keyed by table, row and column."""
    summary = False
    for page_no, lines in pages:
        yield from _surveillance(page_no, lines)
        yield from _outbreaks(page_no, lines)
        yield from _influenza(page_no, lines)
        for i, cells in enumerate(lines):
            m = PERIOD.search(_text(cells))
            if not m or summary:  # the first such line; later pages repeat no summary
                continue
            summary = True
            cols = SUMMARY
            # April 2023 heads its first count "New outbreaks"
            near = " ".join(_text(c) for c in lines[max(0, i - 2) : i + 3]).lower()
            if "new outbreaks" in near:
                cols = ("new_outbreaks", *SUMMARY[1:])
            for col, value in zip(cols, m.groups(), strict=True):
                yield _row("summary", "Meghalaya", col, value, page_no)
