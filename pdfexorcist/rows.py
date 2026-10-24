"""Lines to keyed cells."""

import math
import re
import statistics
from collections import Counter
from collections.abc import Iterable, Iterator
from itertools import pairwise

from ._bold import drop_copies
from .cells import Box, BoxCell, token_boxes, union

Cell = tuple[float, str]  # engines may pass a BoxCell: the same pair plus .box
Page = tuple[int, list[list[Cell]]]

# nc: "no cases" (NFHS-5); 2E+05, #####: Excel's display of a number too wide for its cell
# read as values so columns stay in place; checks.lossy fails them
LOSSY_FORMS = r"\d(\.\d+)?E\+\d+|#{3,}|#(REF!|VALUE!|DIV/0!|NAME\?)|\d[\d,]*(\.\d+)?%?\)"
NUMBER = r"[-−]?\d[\d,]*(?:[.·]\d+)?"
# 9.20±0.40, 1489±10: a value with its uncertainty is one cell
UNCERTAIN = rf"{NUMBER}(?:±|\+/-|\+-){NUMBER}%?"
PLACEHOLDERS = r"\*|-|–|—|\.\.\.?|…|--|na|NA|nc|NC|n/a|N/A|N\.A\.|n\.a\.|#N/A"
PLAIN = rf"\(?{NUMBER}%?\)?[*#@$]?"
# 97.1(68/70): a % with its count, joined by the engine or a recipe, is one cell
WITH_COUNT = rf"{NUMBER}%?\(\d+/\d+\)"
VALUE = re.compile(
    "|".join(f"^(?:{p})$" for p in (PLAIN, UNCERTAIN, WITH_COUNT, PLACEHOLDERS, LOSSY_FORMS))
)
KEY = ["page", "row", "col"]
FLUSH_PT = 0.5  # words this close were printed as one, split only by a shifted baseline
PLACEMENTS = ("x", "both")


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


def parse_rows(
    pages: Iterable[Page], min_values: int = 1, fit_width: bool = False
) -> Iterator[dict]:
    """Default parser: one dict per value, keyed by KEY, plus the label text.

    The row key leaves out a side label (a group name printed once left of the label
    column, beside its block of rows) wherever an engine puts it: on a line of its
    own, in a row's first cell, or joined to a label that other rows show alone. Values
    on a line without a label take the label of the label-only line just above (a label
    wrapped onto two lines). A trailing number in a label ("below 20") is read as a
    value; fit_width gives it back when the row is wider than the rows beside it.
    """
    for page_no, lines in pages:
        rows = _page_rows(lines)
        if fit_width:
            rows = _fit_width(rows)
        seen: Counter = Counter()
        for label, vals, boxes in rows:
            if len(vals) < min_values:  # e.g. 2: skip a title ending in its year
                continue
            key = label_key(label)
            seen[key] += 1
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


def _fit_width(rows: list[tuple[str, list[str], list]]) -> list[tuple[str, list[str], list]]:
    """Give a row's leading values back to its label when it is wider than both neighbours."""
    out = []
    for i, (label, vals, boxes) in enumerate(rows):
        near = [len(r[1]) for r in rows[max(i - 1, 0) : i] + rows[i + 1 : i + 2]]
        k = max(near, default=len(vals))
        if label and k < len(vals):
            label, vals, boxes = " ".join([label, *vals[:-k]]), vals[-k:], boxes[-k:]
        out.append((label, vals, boxes))
    return out


def _left(cell: Cell) -> float:
    """Where a cell starts; x only, so a vote never depends on boxes."""
    # exact for character columns (pdftotext), approximate in points
    return cell[0] - len(cell[1]) / 2


def _heads(cells: list[Cell]) -> int:
    """How many leading cells hold label text."""
    n = 0
    while n < len(cells) and not all(is_value(t) for t in cells[n][1].split() or ["-"]):
        n += 1
    return n


def _page_rows(lines: list[list[Cell]]) -> list[tuple[str, list[str], list[Box | None]]]:
    """(label, values, value boxes) per line with values; side labels dropped."""
    out: list[tuple[str, list[str], list[Box | None]]] = []
    above = ""
    for part in _tables(lines):
        valued = [c for c in part if split_values(c)[1]]
        sides = [_left(c[0]) for c in valued if _side_head(c)]
        # leftmost label, skipping rows that start at a side label (joined); 2 units slack
        col = min(
            (_left(c[0]) for c in valued
             if _heads(c) == 1 and all(abs(_left(c[0]) - x) > 2 for x in sides)),
            default=-math.inf,
        ) - 2  # fmt: skip
        part = [c[1:] if _side_head(c) and _left(c[0]) < col else c for c in part]
        labels = {
            key
            for c in part
            if _heads(c) and _left(c[0]) >= col and (key := label_key(split_values(c)[0]))
        }
        for cells in part:
            if _heads(cells) == 1 and _left(cells[0]) < col:
                words = cells[0][1].split()
                # side label joined to a known label (pdftotext)
                cut = max(
                    (i for i in range(1, min(len(words), 5))
                     if _is_side(words[:i]) and label_key("".join(words[i:])) in labels),
                    default=0,
                )  # fmt: skip
                if not cut and not split_values(cells)[1]:
                    above = ""  # a side label on a line of its own
                    continue
                cells = [(cells[0][0], " ".join(words[cut:])), *cells[1:]]
            label, vals = split_values(cells)
            if not vals:
                # a wrapped label is one cell without a closing ":"
                above = label if len(cells) == 1 and not label.rstrip().endswith(":") else ""
                continue
            label, above = label or above, ""
            out.append((label, vals, [b for _, _, b in token_boxes(cells)][-len(vals) :]))
    return out


def _side_head(cells: list[Cell]) -> bool:
    """Whether the first cell is a side label before more label text."""
    return _heads(cells) > 1 and _is_side(cells[0][1].split())


def _is_side(words: list[str]) -> bool:
    """A few words, no digits ("51.") and no closing colon ("Private hospital:")."""
    return (
        0 < len(words) <= 4
        and not words[-1].endswith(":")
        and not any(ch.isdigit() for w in words for ch in w)
    )


def _tables(lines: list[list[Cell]]) -> Iterator[list[list[Cell]]]:
    """Runs of lines; a run ends before a line whose value count differs from the run's."""
    part: list[list[Cell]] = []
    width = None
    for cells in lines:
        n = len(split_values(cells)[1])
        if n:
            if width not in (None, n):
                yield part
                part = []
            width = n
        part.append(cells)
    if part:
        yield part


def _lines(boxes: list[tuple]) -> list[list]:
    """[anchor top, anchor bottom, words, sideways]: a word joins a line when it overlaps the
    line's first word by half the shorter height."""
    rows: list[list] = []
    for x0, x1, top, bottom, t in sorted(boxes, key=lambda b: ((b[2] + b[3]) / 2, b[0])):
        word = (x0, x1, t, top, bottom)
        if rows:
            r = rows[-1]
            overlap = min(r[1], bottom) - max(r[0], top)
            if overlap >= 0.5 * min(r[1] - r[0], bottom - top):
                r[2].append(word)
                continue
        rows.append([top, bottom, [word], False])
    return rows


def group_words(words: list[tuple], gap: float = 8.0) -> list[list[Cell]]:
    """(x0, x1, y_bottom, text[, y_top]) words to lines of (x_centre, text) BoxCells.

    A word joins a line when it overlaps the line's first word by half the shorter
    height; a word without y_top is 1 pt tall. A word printed sideways joins the line
    through its middle. Copies of a word drawn again within
    COPY_PT (fake bold) count once.
    Label words within gap pt join one cell; values never join. A word printed flush
    (FLUSH_PT) joins without a space, as subscripts do ("PM2.5").
    """
    boxes = [(w[0], w[1], w[4] if len(w) > 4 else w[2] - 1, w[2], w[3]) for w in words]
    boxes = drop_copies(boxes)
    # a word printed sideways is tall: it would join the lines above and below it, each engine
    # a different set, so it joins only the line through its middle
    side = [b for b in boxes if b[3] - b[2] > 1.5 * (b[1] - b[0]) and len(b[4]) > 1]
    rows = _lines([b for b in boxes if b not in side])
    for x0, x1, top, bottom, t in side:
        mid = (top + bottom) / 2
        r = next((r for r in rows if r[0] <= mid <= r[1] and not r[3]), None)
        if r is None:
            r = next((r for r in rows if r[3] and r[0] <= mid <= r[1]), None)
        if r is None:  # a line of sideways headings
            r = [mid - 1, mid + 1, [], True]
            rows.append(r)
        r[2].append((x0, x1, t, top, bottom))
    rows.sort(key=lambda r: (r[0] + r[1]) / 2)
    out: list[list[Cell]] = []
    for _, _, row, _ in rows:
        row.sort(key=lambda w: w[0])
        cells: list[list] = []  # [x0, x1, text, top, bottom]
        for x0, x1, t, top, bottom in row:
            flush = bool(cells) and x0 - cells[-1][1] <= FLUSH_PT
            joinable = flush or (
                cells
                and x0 - cells[-1][1] <= gap
                and not (is_value(t) or is_value(cells[-1][2].split()[-1]))
            )
            if joinable:
                cells[-1][1], cells[-1][2] = x1, cells[-1][2] + ("" if flush else " ") + t
                cells[-1][3] = min(cells[-1][3], top)
                cells[-1][4] = max(cells[-1][4], bottom)
            else:
                cells.append([x0, x1, t, top, bottom])
        out.append([BoxCell((a + b) / 2, t, (a, y0, b, y1)) for a, b, t, y0, y1 in cells])
    return out


def parse_by_columns(
    pages: Iterable[Page], min_values: int = 2, tol: float = 0.45, placement: str = "x"
) -> Iterator[dict]:
    """Like parse_rows, but a value's column comes from its x.

    Column centres are the median x of the i-th value over rows with the page's
    most common value count; each value goes to the nearest centre within tol x
    the spacing, so a value an engine missed shifts nothing. Tokens in one column
    are joined ("1" "437" -> "1437").

    placement="both" also places values by their order and keeps a cell only where
    the two agree. Where they differ the engine reads both values there (a blank
    reads ""), so it loses its vote on that cell and the vote shows both readings.
    A row with fewer values than the page's mode is skipped when one of its values
    has no column by x.
    """
    if placement not in PLACEMENTS:
        raise ValueError(f"placement must be 'x' or 'both', got {placement!r}")
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
            cols = [_column(x, centres, tol * spacing) for x, _, _ in vals]
            if placement == "both" and len(vals) < k and None in cols:
                continue  # an engine that dropped a value and misplaced another
            placed: dict[int, list[tuple[str, Box | None]]] = {}
            for c, (_, t, b) in zip(cols, vals, strict=True):
                if c is not None:
                    placed.setdefault(c, []).append((t, b))
            key = label_key(label)
            seen[key] += 1
            by_x = {
                c: ("".join(t for t, _ in ts), union([b for _, b in ts]))
                for c, ts in placed.items()
            }
            if placement == "x":
                readings = [(c, v, b) for c, (v, b) in sorted(by_x.items())]
            else:
                readings = _both(by_x, vals)
            for col, value, box in readings:
                if value and not is_value(value):
                    continue
                cell = {
                    "page": page_no,
                    "row": f"{key}#{seen[key]}",
                    "col": col,
                    "label": label,
                    "value": value,
                }
                if box is not None:
                    cell["box"] = box
                yield cell


def _column(x: float, centres: list[float], within: float) -> int | None:
    """Index of the centre nearest x, or None when it is further than within."""
    c = min(range(len(centres)), key=lambda i: abs(centres[i] - x))
    return c if abs(centres[c] - x) <= within else None


def _both(by_x: dict, vals: list) -> list[tuple[int, str, Box | None]]:
    """Readings where x and order agree, and both readings where they do not."""
    by_order = {i: (t, b) for i, (_, t, b) in enumerate(vals)}
    out = []
    for c in sorted(by_x.keys() | by_order.keys()):
        (a, box), (b, _) = by_order.get(c, ("", None)), by_x.get(c, ("", None))
        out += [(c, a, box)] if a == b else [(c, a, box), (c, b, box)]
    return out
