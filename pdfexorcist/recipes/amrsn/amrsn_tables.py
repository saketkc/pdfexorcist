"""AMRSN tables of words or plain numbers, each cell's text.

Rows come from the row rules or the lines; columns from column rules or where the words line up.
"""

import re
from collections.abc import Iterator

from amrsn_common import (
    CAPTION,
    END,
    FOOT,
    TABLE_START,
    Word,
    chunks,
    cx,
    cy,
    edges,
    lines_of,
    norm,
    spans,
)

from pdfexorcist import grid
from pdfexorcist.cells import Box


def _index(values: list[float], v: float) -> int:
    return min(range(len(values)), key=lambda i: abs(values[i] - v))


def _col(cols: list[tuple[float, float]], b: Box) -> int:
    x = cx(b)
    for i, (a, z) in enumerate(cols):
        if a - 1 <= x <= z + 1:
            return i
    return min(range(len(cols)), key=lambda i: abs((cols[i][0] + cols[i][1]) / 2 - x))


def _emit(
    page_no: int, tid: str, title: str, cells: dict[tuple[int, int], list[str]]
) -> Iterator[dict]:
    """One record per cell. The label is the first cell of the row.
    The column is the cell of the first row."""
    first_row = min((r for r, _ in cells), default=0)
    for (r, c), texts in sorted(cells.items()):
        text = norm(" ".join(texts))
        if not text:
            continue
        yield {
            "page": page_no, "id": f"{page_no}.{tid}.{r}", "title": title, "group": "",
            "label": norm(" ".join(cells.get((r, 0), []))),
            "col": c, "column": norm(" ".join(cells.get((first_row, c), []))),
            "entry": "", "field": "text", "value": text,
        }  # fmt: skip


def ruled(
    page_no: int, t_no: int, table: grid.Table, words: list[Word], title: str
) -> Iterator[dict]:
    """Every cell of a ruled table."""
    lefts = edges([c[0] for c in table.cells])
    tops = edges([c[1] for c in table.cells])
    cells: dict[tuple[int, int], list[str]] = {}
    rows = lines_of(words)
    if len(lefts) > 1:  # column rules: each drawn cell is a cell
        for line in rows:
            for t, b in line:
                box = table.at(cx(b), cy(b))
                if box is not None:
                    cells.setdefault((_index(tops, box[1]), _index(lefts, box[0])), []).append(t)
    else:  # row rules only: columns from where the words line up below the first band
        body = [b for line in rows if _band(tops, line) > 0 for _, b in chunks(line)]
        cols = spans(body, -1) or [(table.bbox[0], table.bbox[2])]
        for line in rows:
            for t, b in chunks(line):
                cells.setdefault((_band(tops, line), _col(cols, b)), []).append(t)
    yield from _emit(page_no, str(t_no), title, cells)


def _band(tops: list[float], line: list[Word]) -> int:
    return max(sum(t <= cy(line[0][1]) for t in tops) - 1, 0)


def unruled(page_no: int, words: list[Word], tables: list[grid.Table]) -> Iterator[dict]:
    """Tables with no rules: from each caption down to the next caption or figure.

    Each line is a row. A line with one cell as wide as most of the region is prose.
    Prose ends the table.
    """
    lines = lines_of(words)
    if not lines:
        return
    width = max(b[2] for ln in lines for _, b in ln) - min(b[0] for ln in lines for _, b in ln)
    ruled_y = [(t.bbox[1], t.bbox[3]) for t in tables]
    for i, line in enumerate(lines):
        text = " ".join(t for t, _ in line)
        cap = CAPTION.match(text)
        if not cap or re.search(r"\.{4,}", text):  # dot leaders: a contents entry
            continue
        if any(top - 40 <= cy(line[0][1]) <= bottom for top, bottom in ruled_y):
            continue  # a ruled table's caption: read through its rules
        body: list[list[Word]] = []  # each line's cells
        for nxt in lines[i + 1 :]:
            ntext = " ".join(t for t, _ in nxt)
            if END.match(ntext) or TABLE_START.match(ntext) or FOOT.search(ntext):
                break
            if any(top <= cy(nxt[0][1]) <= bottom for top, bottom in ruled_y):
                break
            cs = chunks(nxt)
            prose = len(cs) == 1 and cs[0][1][2] - cs[0][1][0] > 0.6 * width
            if prose and body:
                break
            if len(cs) > 1 or body:  # one cell before the rows: the caption's next line
                body.append(cs)
        if sum(len(cs) > 1 for cs in body) < 2:
            continue  # a caption over a picture: nothing in the text layer
        cols = spans([b for cs in body if len(cs) > 1 for _, b in cs], -1)
        cells: dict[tuple[int, int], list[str]] = {}
        for r, cs in enumerate(body):
            for t, b in cs:
                cells.setdefault((r, _col(cols, b)), []).append(t)
        yield from _emit(page_no, f"t{cap[1]}", norm(text), cells)
