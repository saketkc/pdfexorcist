"""NEET (UG) 2024 press release tables."""

import re
from collections.abc import Iterable, Iterator

from pdfexorcist.rows import Page, label_key

KEY = ["table", "row", "col"]
YEARS = [str(y) for y in range(2019, 2025)]
RAQ = [f"{y}_{m}" for y in (2023, 2024) for m in ("registered", "appeared", "qualified")]
COLUMNS = {
    "highlights": YEARS,
    "change": ["2023", "2024", "change_pct"],
    "language": YEARS,
    "gender": RAQ,
    "category": RAQ,
    "pwbd": RAQ,
    "nationality": RAQ,
    "qualifying": ["2023_marks", "2023_qualified", "2024_marks", "2024_qualified"],
    "state": RAQ,
}
# digits with , . / - ("3570/7877", the misprint "46-853"), or a placeholder
VALUE = re.compile(r"^(?=.*\d)[\d,./-]+$|^-{1,3}$|^NA$")
HYPHEN = re.compile(r"(?<=\w)\s*-\s*(?=\w)")  # pdfium splits "46-853" into 46 | - | 853
CRITERIA = re.compile(r"^(.*?)\s*(\d+th Percentile)$")
# label key prefix -> Table 1 row; the wrapped "Number of Candidates" rows go by order
HIGHLIGHTS = {
    "numberofcities": "Number of Cities",
    "numberoflanguages": "Number of Languages",
    "numberofcentres": "Number of Centres",
    "numberofcentre": "Number of Centre / Deputy Centre Superintendent",
    "numberofinvigilators": "Number of invigilators",
    "numberofobservers": "Number of Observers",
    "numberofcity": "Number of City Coordinators",
}
CANDIDATES = [f"Number of Candidates {w}" for w in ("registered", "Present", "Absent")]


def _header(words: list[str]) -> str | None:
    """Return the table opened by a header line, or None."""
    text = " ".join(words)
    first = label_key(words[0]) if words else ""
    if first == "candidates" and "2019" in words:
        return "highlights"
    if "%age change" in text:
        return "change"
    if first == "language" and "2019" in words:
        return "language"
    if "Qualifying" in words:
        return "qualifying"
    if text.startswith("State Name"):
        return "state"
    if "Registered" in words:
        return {"gender": "gender", "category": "category", "nationality": "nationality"}.get(first)
    return None


def _split(words: list[str]) -> tuple[str, list[str]]:
    """Split a line's words into a label and trailing values."""
    i = len(words)
    while i and VALUE.match(words[i - 1]):
        i -= 1
    return " ".join(words[:i]).replace("→", "").strip(), words[i:]


def _cities(cells: list, xs: list[float]) -> list[str] | None:
    """Return Number of Cities values, retaining split parenthetical counts."""
    got: dict[int, str] = {}
    for x, text in cells[1:]:
        m = re.match(r"\d+", text.strip())
        if m:
            col = min(range(len(xs)), key=lambda i: abs(xs[i] - x))
            got.setdefault(col, m.group())
    return [got[i] for i in range(len(xs))] if len(got) == len(xs) else None


def _row(
    table: str, label: str, vals: list[str], cells: list, xs: list[float], seen: set
) -> tuple[str, dict[str, str]] | None:
    """Return a table row's name and column values, or None to skip it."""
    key = label_key(label)
    cols = COLUMNS[table]
    row, extra = label, {}
    if table == "highlights" and key.startswith("numberofcandidates"):
        n = sum((table, c) in seen for c in CANDIDATES)
        row = CANDIDATES[n] if n < len(CANDIDATES) else ""
    elif table == "highlights" and key.startswith("numberofcities"):
        row, vals = HIGHLIGHTS["numberofcities"], _cities(cells, xs) or []
    elif table == "highlights":
        row = next((v for k, v in HIGHLIGHTS.items() if key.startswith(k)), label)
    elif table == "change" and not label and (table, "Total Candidates") not in seen:
        row = "Total Candidates"
    elif table == "qualifying" and (m := CRITERIA.match(label)):
        row, extra = m.group(1), {"criteria": m.group(2)}
    elif table == "qualifying":
        cols = ["2023_qualified", "2024_qualified"] if key == "total" else []
    elif table == "state" and key.startswith("others"):
        row = "Others (including Outside India)"
    if not row or len(vals) != len(cols) or (table, row) in seen:
        return None
    return row, {**extra, **dict(zip(cols, vals, strict=True))}


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield engine values keyed by table, row, and column."""
    table: str | None = None
    xs: list[float] = []  # Table 1's year columns, for Number of Cities
    seen: set[tuple[str, str]] = set()
    for _, lines in pages:
        for cells in lines:
            words = HYPHEN.sub("-", " ".join(t for _, t in cells)).split()
            opened = _header(words)
            if opened:
                table = opened
                xs = [x for x, t in cells if t.strip() in YEARS] if opened == "highlights" else xs
                continue
            label, vals = _split(words)
            where = "pwbd" if label_key(label) == "pwd" else table
            got = _row(where, label, vals, cells, xs, seen) if where else None
            if got is None:
                continue
            row, values = got
            seen.add((where, row))
            for col, v in values.items():
                yield {"table": where, "row": row, "col": col, "value": v}
            if where == "state" and row == "Total":
                table = None  # the top-100 list follows
