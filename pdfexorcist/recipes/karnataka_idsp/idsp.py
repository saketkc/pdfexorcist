"""Karnataka IDSP weekly infectious disease report: boxes of figures beside trend charts.

Each box is a title, a "Last Week | Current Year" heading ("Last Month" for malaria and JE),
a row of measures and a row of values. The charts' axis labels are smaller and dropped by height.
"""

import re
from collections.abc import Iterable, Iterator

from pdfexorcist import grid
from pdfexorcist.grid import Word
from pdfexorcist.rows import Page

HEADING = re.compile(r"Last\s*(Week|Month)\*?\s+Current\s*Year$", re.I)
NUM = re.compile(r"^\d[\d,]*$")
NA = re.compile(r"^-+$")  # malaria and JE before their monthly figures were in
# measure words as printed; "Rabies" heads the human rabies deaths of 2023
MEASURES = {"tested": "tested", "positives": "positives", "positive": "positives"}
MEASURES |= {"cases": "cases", "bites": "bites", "deaths": "deaths", "rabies": "deaths"}
WEEK = re.compile(r"\(\s*Week\s*(?:No\.?)?\s*(\d+)", re.I)
# fractions of a heading's height: chart text is smaller than any box text, and a box's
# values are taller than its words (engines size a word's box differently)
SMALL = 0.6
VALUE = 0.8
# pt either side of a heading that still belongs to its box; a heading wider than WIDE pt
# (COVID-19 in week 44 of 2023: six figures, no chart) takes a third of its width
PAD = 40.0
WIDE = 300.0
REACH = 100.0  # pt below the heading where a box's values may be


def _rows(words: list[Word]) -> list[list[Word]]:
    """Words grouped into lines by their vertical centre, top to bottom, left to right."""
    out: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w[1][1] + w[1][3]) / 2):
        y = (w[1][1] + w[1][3]) / 2
        if out and abs(y - sum(v[1][1] + v[1][3] for v in out[-1]) / (2 * len(out[-1]))) <= 4:
            out[-1].append(w)
        else:
            out.append([w])
    return [sorted(r, key=lambda w: w[1][0]) for r in out]


def _text(words: list[Word]) -> str:
    return " ".join(w[0] for w in words)


def _heading(row: list[Word]) -> tuple[str, float, float, float] | None:
    """(period, x0, x1, height) of a box heading in row, else None."""
    for i, w in enumerate(row):
        if not w[0].lower().startswith("last"):
            continue
        for j in range(i + 1, min(i + 6, len(row))):
            if m := HEADING.match(_text(row[i : j + 1])):
                period = "last_" + m[1].lower()
                return period, w[1][0], row[j][1][2], w[1][3] - w[1][1]
    return None


def _measures(rows: list[list[Word]]) -> list[str]:
    """The measure words left to right, "Reported cases" as one."""
    out: list[tuple[float, str]] = []
    for row in rows:
        words = [w[0].lower().strip("*") for w in row]
        skip = False
        for i, word in enumerate(words):
            if skip:
                skip = False
            elif word == "reported" and words[i + 1 : i + 2] == ["cases"]:
                out.append((row[i][1][0], "reported cases"))
                skip = True
            elif word in MEASURES:
                out.append((row[i][1][0], MEASURES[word]))
    return [m for _, m in sorted(out)]


def _title(rows: list[list[Word]]) -> str:
    """The nearest line above a heading that names something: the box's title."""
    for row in reversed(rows):
        words = []
        for w in row:
            if w[0].startswith(("Trend", "(Source")) or re.match(r"^[\d.,]+$", w[0]):
                break  # a chart title or axis label, or the source of a section heading
            words.append(w[0])
        text = re.sub(r"\s*\(\s*", " (", " ".join(words)).strip(" *")
        labels = all(w[0].lower().strip("*") in {*MEASURES, "reported"} for w in row)
        if text and not text.startswith("*") and not labels:
            return text.rstrip("*").strip()
    return ""


def _box(
    rows: list[list[Word]], top: int, period: str, height: float
) -> Iterator[tuple[str, str, str]]:
    """(period, measure, value) of the box whose heading is rows[top]; NA cells left out."""
    y = rows[top][0][1][3]
    for k in range(top + 1, len(rows)):
        # a value's box is taller than an axis label's beside it
        row = [w for w in rows[k] if not NUM.match(w[0]) or w[1][3] - w[1][1] >= VALUE * height]
        if not row:
            continue
        if row[0][1][1] - y > REACH or _heading(row):
            return
        if not all(NUM.match(w[0]) or NA.match(w[0]) for w in row):
            continue
        names = _measures(rows[top + 1 : k]) or ["cases"] * len(row)
        if len(names) != len(row) or len(row) % 2:
            return
        for i, (w, name) in enumerate(zip(row, names, strict=True)):
            if NUM.match(w[0]):
                yield (period if i < len(row) // 2 else "current_year"), name, w[0]
        return


def _page(words: list[Word]) -> Iterator[tuple[str, str, str, str]]:
    """(disease, period, measure, value) of each box on a page."""
    found = [h for row in _rows(words) if (h := _heading(row))]
    if not found:
        return
    height = sorted(h[3] for h in found)[len(found) // 2]
    rows = _rows([w for w in words if w[1][3] - w[1][1] >= SMALL * height])
    starts = [(i, h) for i, row in enumerate(rows) if (h := _heading(row))]
    for n, (top, (period, x0, x1, _)) in enumerate(starts):
        # the box's own words: charts and their axes lie to the right
        pad = PAD if x1 - x0 < WIDE else (x1 - x0) / 3
        boxed = [[w for w in r if x0 - pad <= (w[1][0] + w[1][2]) / 2 <= x1 + pad] for r in rows]
        above = [r for r in boxed[starts[n - 1][0] + 1 if n else 0 : top] if r]
        title = _title(above)
        for period_, measure, value in _box(boxed, top, period, height):
            yield title, period_, measure, value


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each figure keyed by the disease as printed, the period and the measure."""
    week = None
    for page_no, lines in pages:
        words = grid.words(lines)
        if m := WEEK.search(" ".join(w[0] for w in words)):
            week = m[1]
        for disease, period, measure, value in _page(words):
            if disease:
                yield {
                    "disease": disease,
                    "period": period,
                    "measure": measure,
                    "value": value,
                    "page": page_no,
                    "week": week,
                }
