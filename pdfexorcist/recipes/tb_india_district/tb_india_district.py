"""TB India reports (2010-2019): district notification tables, one value a cell.

Values sit in columns by x, so a blank cell shifts nothing. The label left of the first
column holds the State and the district; a row printing no State takes the one above.
"""

import re
import statistics
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from itertools import pairwise

from tb_india_layouts import STATES, Layout, fold, layout_of, split_state

from pdfexorcist.cells import token_boxes
from pdfexorcist.rows import Page, is_value

MARKS = re.compile(r"[*#@$†‡^]+|\(\s*\)")
NOT_ROW = re.compile(
    r"^(total|india|grand\s*total|source|note|summary)\b|\bzone\b|^north[- ]east$", re.I
)
NUMBERED = re.compile(r"\d+(\.\d+)?%?$")  # a zone or summary row's first value read as name


@dataclass
class Row:
    """One printed line: its middle y, label words by part, and positioned values."""

    y: float
    state: list[str] = field(default_factory=list)
    district: list[str] = field(default_factory=list)
    values: list[tuple[float, str]] = field(default_factory=list)


def _tokens(cells: list, line: int) -> list[tuple[float, float, float, str]]:
    """(x0, x centre, y middle, text) of each word of a line.

    A cell without a box (pdftotext, x in character columns) places its words by character
    and takes the line number as y.
    """
    out = []
    for cell in cells:
        x, text = cell[0], cell[1]
        if getattr(cell, "box", None) is None:
            start = x - len(text) / 2
            for m in re.finditer(r"\S+", text):
                x0 = start + m.start()
                out.append((x0, x0 + len(m.group()) / 2, float(line), m.group()))
            continue
        for _, word, box in token_boxes([cell]):
            if box is None:
                continue
            out.append((box[0], (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, word))
    return out


def _clean(words: list[str]) -> str:
    """A name: footnote marks dropped, a hyphen broken at the line end rejoined."""
    text = MARKS.sub(" ", " ".join(words))
    text = re.sub(r"(?<=[a-z])- (?=[a-z])|(?<=[A-Z]{2})- (?=[A-Z]{2})", "", text)
    return " ".join(text.split()).strip(" .,-")


def _has_header(lines: list[list]) -> bool:
    """Whether the page prints the State and District headings."""
    for cells in lines:
        texts = [t for _, text in cells for t in text.split()]
        if "District" in texts and any(t.startswith("State") for t in texts):
            return True
    return False


def _district_x(lines: list[list], label_right: float, k: int) -> float | None:
    """The left x of the district column: the commonest left edge of a label word right of
    the State column (districts are left-aligned, each row starts one; State names are
    split in different places)."""
    edges: list[list[float]] = []
    for i, cells in enumerate(lines):
        toks = _tokens(cells, i)
        values = sum(xc > label_right and is_value(t) for _, xc, _, t in toks)
        if values >= k - 2:
            edges.append([x0 for x0, xc, _, _ in toks if xc <= label_right])
    starts = [x for e in edges for x in e]
    # the State column's left edge; State names may be printed on lines of their own
    labels = [
        x0 for i, c in enumerate(lines) for x0, xc, _, _ in _tokens(c, i) if xc <= label_right
    ]
    if not starts or not labels:
        return None
    left = min(labels)
    right = [x for x in starts if x > left + 6]
    if not right:
        return None
    # the commonest 4 pt window of left edges, a window starting at each edge
    best = max(right, key=lambda a: sum(a <= x < a + 4 for x in right))
    return best - 2.0


def _rows(lines: list[list], label_right: float, split: float) -> list[Row]:
    """Each line's label words (by part) and values right of the label column."""
    rows = []
    for i, cells in enumerate(lines):
        toks = _tokens(cells, i)
        if not toks:
            continue
        row = Row(statistics.median(y for _, _, y, _ in toks))
        for x0, xc, _, text in toks:
            if xc > label_right and is_value(text):
                row.values.append((xc, text))
            elif xc <= label_right:
                (row.state if x0 < split else row.district).append(text)
        rows.append(row)
    return rows


def _centres(rows: list[Row], k: int) -> list[float] | None:
    """Median x of each of the k columns over rows printing all k; None if under two."""
    full = [r.values for r in rows if len(r.values) == k]
    if len(full) < 2:
        return None
    return [statistics.median(v[i][0] for v in full) for i in range(k)]


def _place(values: list[tuple[float, str]], centres: list[float]) -> dict[int, str]:
    """Values by column: nearest centre within half the spacing; a clash unreads both."""
    within = 0.5 * min(b - a for a, b in pairwise(centres))
    out: dict[int, str] = {}
    for x, text in values:
        c = min(range(len(centres)), key=lambda i: abs(centres[i] - x))
        if abs(centres[c] - x) <= within:
            out[c] = "" if c in out else text
    return {c: v for c, v in out.items() if v}


def _owner(r: Row, part: str, data: list[Row], spacing: float) -> Row | None:
    """The value row a label-only line's State or district words belong to.

    Of the rows just above and below it, the one whose own line lacks that part (a name
    centred on two lines around its values, 2017-2019), else the nearer, the row above on a
    tie.
    Above the first row only a centred wrap joins (lines further up are headings).
    """
    above = max((d for d in data if d.y < r.y), key=lambda d: d.y, default=None)
    below = min((d for d in data if d.y > r.y), key=lambda d: d.y, default=None)
    reach = 2.2 * spacing if above is not None else 0.6 * spacing
    near = [d for d in (above, below) if d is not None and abs(d.y - r.y) <= reach]
    if not near:
        return None
    lacking = [d for d in near if not getattr(d, part)]
    if len(lacking) == 1 and len(near) == 2:
        return lacking[0]
    return min(near, key=lambda d: (abs(d.y - r.y), d.y > r.y))


def _attach(rows: list[Row], first: int) -> list[Row]:
    """Value rows with the name fragments of the label-only lines near them."""
    data = [r for r in rows[first:] if r.values]
    if not data:
        return []
    gaps = [b.y - a.y for a, b in pairwise(data)]
    spacing = statistics.median(gaps) if gaps else 12.0
    extra: dict[tuple[int, str], list[tuple[float, list[str]]]] = {}
    for r in rows[first:]:
        if r.values:
            continue
        for part in ("state", "district"):
            words = getattr(r, part)
            owner = _owner(r, part, data, spacing) if words else None
            if owner is not None:
                extra.setdefault((id(owner), part), []).append((r.y, words))
    out = []
    for d in data:
        names = {}
        for part in ("state", "district"):
            frags = [*extra.get((id(d), part), []), (d.y, getattr(d, part))]
            names[part] = [w for _, ws in sorted(frags, key=lambda f: f[0]) for w in ws]
        out.append(Row(d.y, names["state"], names["district"], d.values))
    return out


def _page(lines: list[list], layout: Layout) -> Iterator[dict]:
    if not _has_header(lines):
        return
    k = len(layout.cols)
    rough = _rows(lines, 0.0, 0.0)  # first pass: every number is a value
    centres = _centres(rough, k)
    if centres is None:
        return
    label_right = centres[0] - 0.5 * (centres[1] - centres[0])
    split = _district_x(lines, label_right, k)
    if split is None:
        return
    rows = _rows(lines, label_right, split)
    first = next((i for i, r in enumerate(rows) if len(r.values) >= k - 2), 0)
    # a label-only line just above the first row may be its wrapped name
    start = max(first - 2, 0)
    state = ""
    for row in _attach(rows, start):
        name, district = split_state(_clean(row.state), _clean(row.district))
        if NOT_ROW.search(name or district) or not district or NUMBERED.search(district):
            continue
        if name and fold(name) not in STATES:
            continue  # a heading, a note, or two rows an engine read as one
        state = name or state
        for col, value in _place(row.values, centres).items():
            if layout.cols[col] is None:
                continue
            yield {
                "table": layout.name,
                "state": state,
                "district": district,
                "col": layout.cols[col],
                "value": value,
            }


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield one value per district table, State, district and column."""
    for page_no, lines in pages:
        text = " ".join(t for cells in lines for _, t in cells)
        counts = Counter(sum(is_value(t) for _, text in c for t in text.split()) for c in lines)
        common = {n for n, c in counts.items() if c >= 2}
        layout = layout_of(text, common)
        if layout is None:
            continue
        for cell in _page(lines, layout):
            yield {"page": page_no, **cell}
