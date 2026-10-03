"""Lines to keyed cells."""

import re
import statistics
from collections import Counter
from collections.abc import Iterable, Iterator
from itertools import pairwise

from .cells import Box, BoxCell, token_boxes, union

Cell = tuple[float, str]  # engines may pass a BoxCell: the same pair plus .box
Page = tuple[int, list[list[Cell]]]

# nc: "no cases" in the NFHS-5 national report
VALUE = re.compile(
    r"^\(?[-−]?\d[\d,]*([.·]\d+)?%?\)?[*#@$]?$|^(\*|-|–|—|\.\.\.?|…|--|na|NA|nc|NC|n/a|N/A|N\.A\.|n\.a\.|#REF!|#VALUE!|#N/A|#DIV/0!|#NAME\?)$"
)
KEY = ["page", "row", "col"]


def is_value(tok: str) -> bool:
    """Return whether a token matches a printed table value."""
    return bool(VALUE.match(tok))


def label_key(label: str) -> str:
    """Return a case-, spacing-, and punctuation-insensitive label key."""
    return re.sub(r"[^a-z0-9]", "", label.lower())


def split_values(cells: list[Cell]) -> tuple[str, list[str]]:
    """Split a line into label text and trailing value tokens."""
    toks = [t for _, text in cells for t in text.split()]
    i = len(toks)
    while i and is_value(toks[i - 1]):
        i -= 1
    return " ".join(toks[:i]), toks[i:]


def parse_rows(pages: Iterable[Page], min_values: int = 1) -> Iterator[dict]:
    """Default parser: one dict per value, keyed by KEY, plus the label text.

    A trailing number in a label ("Population 2019") is read as a value; pass a
    document parser to extract() when that matters.
    """
    for page_no, lines in pages:
        seen: Counter = Counter()
        for cells in lines:
            label, vals = split_values(cells)
            if len(vals) < min_values:  # e.g. 2: skip a title ending in its year
                continue
            key = label_key(label)
            seen[key] += 1
            boxes = [b for _, _, b in token_boxes(cells)][-len(vals) :]
            for col, v in enumerate(vals):
                cell = {
                    "page": page_no,
                    "row": f"{key}#{seen[key]}",
                    "col": col,
                    "label": label,
                    "value": v,
                }
                if boxes[col] is not None:  # where the engine saw it (BoxCell lines)
                    cell["box"] = boxes[col]
                yield cell


def group_words(words: list[tuple], gap: float = 8.0) -> list[list[Cell]]:
    """(x0, x1, y_bottom, text[, y_top]) words to lines of (x_centre, text) BoxCells.

    A word joins a line when their vertical extents overlap by half the shorter
    one; a word without y_top is 1 pt tall; a word drawn twice (fake bold) counts
    once. Label words within gap pt join one cell; values never join.
    """
    boxes = [(w[0], w[1], w[4] if len(w) > 4 else w[2] - 1, w[2], w[3]) for w in words]
    # "fake bold": some PDFs draw each word twice, a fraction of a point apart
    seen, unique = set(), []
    for b in boxes:
        k = (b[4], round(b[0]), round(b[3]))
        if k not in seen:
            seen.add(k)
            unique.append(b)
    boxes = unique
    rows: list[list] = []  # [top, bottom, words]
    for x0, x1, top, bottom, t in sorted(boxes, key=lambda b: ((b[2] + b[3]) / 2, b[0])):
        if rows:
            r = rows[-1]
            overlap = min(r[1], bottom) - max(r[0], top)
            if overlap >= 0.5 * min(r[1] - r[0], bottom - top):
                r[0], r[1] = min(r[0], top), max(r[1], bottom)
                r[2].append((x0, x1, t, top, bottom))
                continue
        rows.append([top, bottom, [(x0, x1, t, top, bottom)]])
    out: list[list[Cell]] = []
    for _, _, row in rows:
        row.sort(key=lambda w: w[0])
        cells: list[list] = []  # [x0, x1, text, top, bottom]
        for x0, x1, t, top, bottom in row:
            joinable = (
                cells
                and x0 - cells[-1][1] <= gap
                and not (is_value(t) or is_value(cells[-1][2].split()[-1]))
            )
            if joinable:
                cells[-1][1], cells[-1][2] = x1, cells[-1][2] + " " + t
                cells[-1][3] = min(cells[-1][3], top)
                cells[-1][4] = max(cells[-1][4], bottom)
            else:
                cells.append([x0, x1, t, top, bottom])
        out.append([BoxCell((a + b) / 2, t, (a, y0, b, y1)) for a, b, t, y0, y1 in cells])
    return out


def parse_by_columns(
    pages: Iterable[Page], min_values: int = 2, tol: float = 0.45
) -> Iterator[dict]:
    """Like parse_rows, but a value's column comes from its x.

    Column centres are the median x of the i-th value over rows with the page's
    most common value count; each value goes to the nearest centre within tol x
    the spacing, so a value an engine missed shifts nothing. Tokens in one column
    are joined ("1" "437" -> "1437").
    """
    for page_no, lines in pages:
        rows = []  # (label, [(x, value token, its box or None)])
        for cells in lines:
            toks = list(token_boxes(cells))
            label = " ".join(t for _, t, _ in toks if not is_value(t))
            rows.append((label, [tok for tok in toks if is_value(tok[1])]))
        counts = Counter(len(v) for _, v in rows if len(v) >= min_values)
        if not counts:
            continue
        k = counts.most_common(1)[0][0]
        full = [v for _, v in rows if len(v) == k]
        centres = [statistics.median(v[i][0] for v in full) for i in range(k)]
        spacing = min((b - a for a, b in pairwise(centres)), default=1.0) or 1.0
        seen: Counter = Counter()
        for label, vals in rows:
            if len(vals) < min_values:
                continue
            placed: dict[int, list[tuple[str, Box | None]]] = {}
            for x, t, b in vals:
                c = min(range(k), key=lambda i: abs(centres[i] - x))
                if abs(centres[c] - x) <= tol * spacing:
                    placed.setdefault(c, []).append((t, b))
            key = label_key(label)
            seen[key] += 1
            for col, ts in sorted(placed.items()):
                value = "".join(t for t, _ in ts)
                if is_value(value):
                    cell = {
                        "page": page_no,
                        "row": f"{key}#{seen[key]}",
                        "col": col,
                        "label": label,
                        "value": value,
                    }
                    box = union([b for _, b in ts])
                    if box is not None:
                        cell["box"] = box
                    yield cell
