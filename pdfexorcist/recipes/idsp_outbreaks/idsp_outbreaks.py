"""IDSP weekly outbreak report (NCDC)."""

import re
from collections.abc import Iterable, Iterator

import idsp_ruled

from pdfexorcist.rows import Page

ID = re.compile(r"^[A-Z]{2}/[A-Z]{2,4}/\d{4}/\d+/\d*$")  # wrapped IDs may end at the "/"
INT = re.compile(r"^\d+$")
DATE = re.compile(r"^\d\d-\d\d-(\d{4})?$")
# the statuses this report prints; a new one reads as a comment word
STATUS = {"Under", "Control", "Surveillance", "Investigation", "Controlled", "Contained"}
LATE = "REPORTED LATE"


def _join_numbers(cells: list[tuple[float, str]]) -> list[tuple[float, str]]:
    """Put a number back on the name it starts; rows.group_words splits "24" off "Paraganas"."""
    out: list[tuple[float, str]] = []
    for x, t in cells:
        if out and INT.match(out[-1][1]):
            out[-1] = (out[-1][0], f"{out[-1][1]} {t}")
        else:
            out.append((x, t))
    return out


def _row(cells: list[tuple[float, str]], late: bool) -> "_Row | None":
    """The outbreak a line starts, or None when its cases and deaths are not found."""
    texts = [t for _, t in cells]
    # cases and deaths: two whole numbers, then the start date
    for i in range(3, len(texts) - 2):
        if INT.match(texts[i]) and INT.match(texts[i + 1]) and DATE.match(texts[i + 2]):
            return _Row(cells, i, late)
    return None


class _Row:
    """One outbreak: its columns' x on the first line, and the text read under each."""

    def __init__(self, cells: list[tuple[float, str]], cases: int, late: bool) -> None:
        self.id = cells[0][1]
        self.late = late
        cols = ["state", "district", "disease", "cases", "deaths", "start"]
        cols += [] if late else ["reported"]
        cols += ["status", "comment"]  # comment words stay out of status
        names = _join_numbers(cells[1:cases])  # state, district, then the disease in pieces
        rest = cells[cases:]
        # a disease that starts on a later line still needs an anchor
        xs = [x for x, _ in [*names[:2], names[min(2, len(names) - 1)], *rest]]
        self.anchors = list(zip(xs, cols, strict=False))
        self.text: dict[str, list[str]] = {c: [] for c in cols}
        for x, t in [*names[:2], *rest]:
            self.add(x, t)
        self.text["disease"] += [t for _, t in names[2:]]

    def add(self, x: float, t: str) -> None:
        col = min(self.anchors, key=lambda a: abs(a[0] - x))[1]
        if col != "comment" and (col != "status" or set(t.split()) <= STATUS):
            self.text[col].append(t)

    def values(self) -> Iterator[tuple[str, str]]:
        for col, parts in self.text.items():
            if parts:
                yield col, "".join(parts) if col in ("start", "reported") else _words(parts)


def _words(parts: list[str]) -> str:
    """Join a column's lines, gluing words the narrow columns break without a hyphen.

    A lowercase line after a long capitalised word ("Maharashtr" "a",
    "Gastroenterit" "is") continues it; "Fever with" "rash" stays two words.
    """
    out = parts[0]
    for p in parts[1:]:
        last = out.split()[-1]
        glue = p[0].islower() and last[0].isupper() and len(last) >= 6
        out = f"{out}{p}" if glue else f"{out} {p}"
    return out


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each outbreak's columns: by unique ID, or for older reports by drawn cell.

    Reports from 2017 on start every row with a unique ID, which the text alone can
    follow. Older ones have none and merge State cells over many rows (idsp_ruled.py);
    those need the drawn table and an engine that gives word boxes.
    """
    pages = list(pages)
    rows = list(_by_id(pages))
    if any(getattr(c, "box", None) for _, lines in pages for line in lines for c in line):
        # the text parser loses IDs wrapped in a narrow column (2025 on); the larger count wins
        ruled = list(idsp_ruled.parse(pages))
        if len({r["id"] for r in ruled}) > len({r["id"] for r in rows}):
            rows = ruled
    yield from rows


def _by_id(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each outbreak's columns keyed by its unique ID."""
    late = follow_up = False
    for page_no, lines in pages:
        row: _Row | None = None
        for line in lines:
            cells = [(x, s.strip()) for x, s in line if s.strip()]
            text = " ".join(t for _, t in cells)
            # follow-ups update outbreaks an earlier report counted; left out, or they count twice
            is_late, is_follow_up = LATE in text, bool(idsp_ruled.FOLLOW_UP.search(text))
            if is_late or is_follow_up:
                late, follow_up = is_late, is_follow_up
                yield from _emit(row, page_no)
                row = None
            if follow_up:
                continue
            if cells and ID.match(cells[0][1]):
                yield from _emit(row, page_no)
                row = _row(cells, late)
            elif row and text.isupper() and len(text) > 10:  # a heading: the table has ended
                yield from _emit(row, page_no)
                row = None
            elif row:
                if cells and INT.match(cells[0][1]) and cells[0][0] < row.anchors[0][0]:
                    # digits left of the State column end a wrapped ID ("AS/DAR/2025/23/9" "59")
                    row.id += cells[0][1]
                    cells = cells[1:]
                for x, t in cells:
                    row.add(x, t)
        yield from _emit(row, page_no)


def _emit(row: _Row | None, page_no: int) -> Iterator[dict]:
    if row is None:
        return
    table = "late" if row.late else "week"
    for col, v in row.values():
        yield {"id": row.id, "col": col, "value": v, "table": table, "page": page_no}
