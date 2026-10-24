"""CBHI National Health Profile: State/UT cases and deaths by sex, one disease a table.

Rows are keyed by State/UT without footnote marks; the national row is "India".
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from pdfexorcist.rows import Cell, Page, is_value

TITLE = re.compile(
    r"(?P<table>\d+(?:\.\d+)+\s*(?:\(\s*[A-Z]\s*\))?)\s*:?\s*State\s*/\s*UTs?\.?\s*wise\s+"
    r"Cases\s+(?:and|&)\s+Deaths\s+due(?:\s+to)?\s+(?P<disease>.*?)\s*(?:(?:\bin\s+)?india\b|$)",
    re.IGNORECASE,
)
# "Cholera Infection in" (the title wraps after "in"), "Viral Hepatitis(All Causes)"
TRAIL = re.compile(r"(\s+(in|india)\b|[\s,])+$", re.IGNORECASE)
YEAR = re.compile(r"\b((?:19|20)\d\d)\b")
SEXES = ("Male", "Female", "Total")
MEASURES = ("Cases", "Deaths")
COLUMNS = [f"{s} {m}" for s in SEXES for m in MEASURES]
NATIONAL = {"india", "total", "allindia", "indiatotal"}
END = re.compile(r"^\W*(source|notes?\b|~|\*\s*:|na\s*:)|national health profile|nhp-\d", re.I)
SERIAL = re.compile(r"^\d{1,2}\.?$")


@dataclass(frozen=True)
class Table:
    """One table's name, disease and year."""

    table: str
    disease: str
    year: str


def _text(cells: list[Cell]) -> str:
    """A line's text, cells joined by spaces."""
    return " ".join(t for _, t in cells)


def _title(text: str) -> Table | None:
    """The table a title line names, or None."""
    m = TITLE.search(text)
    if not m:
        return None
    table = re.sub(r"\s+", "", m["table"])
    disease = TRAIL.sub("", re.sub(r"\s+", " ", m["disease"]))
    disease = re.sub(r"(\w)\(", r"\1 (", disease)
    year = YEAR.search(text[m.end() :])
    return Table(table, disease, year[1] if year else "")


def _centres(cells: list[Cell]) -> list[float] | None:
    """The x of the six Cases and Deaths headings, or None for another line."""
    heads = [(x, t) for x, t in cells if t in MEASURES]
    names = [t for _, t in heads]
    if names[:6] != list(MEASURES) * 3:
        return None
    return [x for x, _ in heads[:6]]


def _place(x: float, centres: list[float]) -> int | None:
    """The column whose heading is nearest x, if within half the gap on that side.

    Numbers are right-aligned, so a value sits right of its heading's centre.
    """
    i = min(range(len(centres)), key=lambda c: abs(centres[c] - x))
    j = i if x > centres[i] and i + 1 < len(centres) else max(i - 1, 0)
    gap = abs(centres[j + 1] - centres[j])
    return i if abs(centres[i] - x) <= gap / 2 else None


def _name(label: str) -> str:
    """The printed name: serial number and footnote marks dropped, spacing normalised."""
    words = re.sub(r"[*#@$]", " ", label).split()
    if words and SERIAL.match(words[0]):
        words = words[1:]
    return " ".join(words).strip(" .")


def _state(name: str) -> str:
    """The State/UT key; the national row is "India"."""
    return "India" if re.sub(r"[^a-z]", "", name.lower()) in NATIONAL else name


def _row(cells: list[Cell], centres: list[float]) -> tuple[str, dict[int, str]]:
    """A body line's name and its values by column; text right of the label is dropped."""
    label: list[str] = []
    values: dict[int, str] = {}
    left = centres[0] - (centres[1] - centres[0]) / 2
    for x, text in cells:
        col = _place(x, centres) if is_value(text) else None
        if col is not None:
            values[col] = "" if col in values else text  # two values in one column: unread
        elif x < left:
            label.append(text)
    return _name(" ".join(label)), {c: v for c, v in values.items() if v}


def _join(rows: list[tuple[str, dict[int, str]]]) -> Iterator[tuple[str, dict[int, str]]]:
    """Rows with values, each with its name; a name wrapped onto lines without values joins.

    A line without values joins the next row if that row has no name, else the row above.
    """
    names = [[name] for name, _ in rows]
    owner = None
    for i, (name, values) in enumerate(rows):
        if values:
            owner = i
            continue
        nxt = next((j for j in range(i + 1, len(rows)) if rows[j][1]), None)
        if nxt is not None and not rows[nxt][0] and (owner is None or nxt == i + 1):
            names[nxt].insert(-1, name)
        elif owner is not None:
            names[owner].append(name)
    for (_, values), parts in zip(rows, names, strict=True):
        if values:
            yield " ".join(p for p in parts if p), values


def _body(lines: list[list[Cell]], table: Table, page_no: int) -> Iterator[dict]:
    """The cells of one table, from its header to its source note."""
    centres = None
    rows = []
    for cells in lines:
        if centres is None:
            centres = _centres(cells)
            continue
        if END.search(_text(cells)) or _title(_text(cells)):
            break
        rows.append(_row(cells, centres))
    for name, values in _join(rows):
        if not name:
            continue
        for col, value in values.items():
            yield {
                "page": page_no,
                "table": table.table,
                "disease": table.disease,
                "year": table.year,
                "state": _state(name),
                "col": COLUMNS[col],
                "sex": COLUMNS[col].split()[0],
                "measure": COLUMNS[col].split()[1],
                "value": value,
            }


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield one value per table, State/UT and column (sex and measure)."""
    for page_no, lines in pages:
        starts = [(i, _title(_text(c))) for i, c in enumerate(lines)]
        tables = [(i, t) for i, t in starts if t]
        for i, table in tables:
            if not table.year:  # the year wrapped onto the next line
                nxt = " ".join(_text(c) for c in lines[i + 1 : i + 3])
                year = YEAR.search(nxt)
                table = Table(table.table, table.disease, year[1] if year else "")
            yield from _body(lines[i + 1 :], table, page_no)
