"""AMRSN antibiograms read through their ruling lines: "R/n" over "(%)" as r, n and pct.

A line of counts opens a row; the drawn row rules decide which row a label belongs to.
Rows are keyed by position (page.table.band.line), the same for every engine.
"""

import bisect
import math
import re
from collections.abc import Iterable, Iterator
from itertools import pairwise

import amrsn_tables
from amrsn_cells import BLANK, _cell
from amrsn_common import GAP, TABLE_START, Word, cx, cy, edges, lines_of, norm, spans

from pdfexorcist import grid
from pdfexorcist.cells import Box, token_boxes

Line = tuple[float, list[Word]]  # middle y, words left to right

# a whole word (172/542, *0/0, "C:38/145", "5/7*", "2403/" wrapped), so "CTX-M8/25" stays a gene
FRAC = re.compile(r"(?:[A-Za-z][^:/]*:|:)?\*?\d[\d,]*/(\d[\d,]*)?\*?")
GLUED = re.compile(r"(\*?\d[\d,]*(?:/\d[\d,]*)?\*?)(\(.+\))")  # "27(8.7)", "841/19027(4.42)"
NUM = re.compile(r"\*?\d[\d,]*(?:\.\d+)?")  # 45.8 (2022 Table 10.28)
PCT = re.compile(r"\((?:-|\d+(?:\.\d+)?)%?\)|\d+(?:\.\d+)?\(%\)")  # (31.7), (77.9%), (-), 2.0(%)
YEAR = re.compile(r"(19|20)\d\d")
RANGE = re.compile(r"\d+(?:\.\d+)?-\d+(?:\.\d+)?")  # Range(%) columns: 91.3-100


def parse(pages: Iterable) -> Iterator[dict]:
    """Yield each count, total, percentage and rank keyed by its place in a ruled table."""
    tables = grid.tables(grid.current_pdf())
    last = ""
    for page_no, lines in pages:
        words = [(t, tb) for line in lines for _, t, tb in token_boxes(line) if tb is not None]
        page = tables.get(page_no, [])
        for t_no, table in enumerate(page):
            above = [o.bbox[3] for o in page if o.bbox[3] <= table.bbox[1] + 1]
            # a first table with no caption above it is carried over from the page before
            title = _title(words, table.bbox[1] + 1, max(above, default=0)) or (
                last if t_no == 0 else ""
            )
            last = title or last
            yield from _table(page_no, t_no, table, page, words, title)
        yield from amrsn_tables.unruled(page_no, words, page)


def _lines(words: list[Word]) -> list[Line]:
    """Words grouped into lines by their middle, each line's pieces joined (see _pieces)."""
    return [(cy(ws[0][1]), _pieces(ws)) for ws in lines_of(words)]


def _pieces(words: list[Word]) -> list[Word]:
    """Join "495" "/" "783" and "(" "77.9" ")" into one word each. Split "27(8.7)" in two."""
    out: list[Word] = []
    for t, b in _split_glued(words):
        if out:
            pt, pb = out[-1]
            gap = b[0] - pb[2]
            joins = pt.endswith(("/", "(")) or t.startswith(("/", ")", "%")) or t == "%"
            if joins and gap < 8:
                out[-1] = (pt + t, (pb[0], min(pb[1], b[1]), b[2], max(pb[3], b[3])))
                continue
        out.append((t, b))
    return out


def _split_glued(words: list[Word]) -> Iterator[Word]:
    """A count or pair glued to its percentage as two words."""
    for t, b in words:
        m = GLUED.fullmatch(t)
        if not m:
            yield t, b
            continue
        cut = b[0] + (b[2] - b[0]) * len(m[1]) / len(t)
        yield m[1], (b[0], b[1], cut, b[3])
        yield m[2], (cut, b[1], b[2], b[3])


def _is_num(t: str) -> bool:
    return bool(FRAC.fullmatch(t) or NUM.fullmatch(t) or PCT.fullmatch(t) or RANGE.fullmatch(t))


def _band(rules: list[float], y: float) -> int:
    """The ruled band holding y: the number of rules above it."""
    return bisect.bisect_left(rules, y)


def _title(page_words: list[Word], top: float, floor: float) -> str:
    """The "Table 5.3: ..." caption between the table above (floor) and this one."""
    lines = _lines([w for w in page_words if floor < cy(w[1]) < top])
    texts = [" ".join(t for t, _ in ws) for _, ws in lines]
    starts = [i for i, t in enumerate(texts) if TABLE_START.match(t)]
    return norm(" ".join(texts[starts[-1] :])) if starts else ""


def _table(
    page_no: int,
    t_no: int,
    table: grid.Table,
    page: list[grid.Table],
    page_words: list[Word],
    title: str,
) -> Iterator[dict]:
    x0, top, x1, bottom = table.bbox
    # text can run past the rules (2021 Table 4.8), so only a table beside another keeps to its box
    beside = any(o is not table and o.bbox[1] < bottom and o.bbox[3] > top for o in page)
    lo, hi = (x0 - 2, x1 + 2) if beside else (-math.inf, math.inf)
    words = [w for w in page_words if lo <= cx(w[1]) <= hi and top <= cy(w[1]) <= bottom]
    lines = _lines(words)
    counts = _count_lines(lines)
    if not counts:  # a table of words or plain numbers: each cell's text
        yield from amrsn_tables.ruled(page_no, t_no, table, words, title)
        return
    first = counts[0]
    cols = _value_columns([w for _, ws in lines[first:] for w in ws if _is_num(w[0])])
    rules = edges([e for c in table.cells for e in (c[1], c[3])])
    rows, groups = _rows(lines, counts, rules, cols)
    heads = _headers(lines[:first], cols)
    for key, label, values in _read_rows(lines, rows, cols):
        base = {"page": page_no, "id": f"{page_no}.{t_no}.{key}", "title": title}
        base["group"] = norm(groups[key])
        base["label"] = label
        for c, entry, field, value in values:
            yield {**base, "col": c, "column": heads.get(c, ""), "entry": entry,
                   "field": field, "value": value}  # fmt: skip


def _value_columns(nums: list[Word]) -> list[tuple[float, float]]:
    """The spans of the value columns. A first column of row numbers (S.No) is label."""
    cols = spans([b for _, b in nums], 4)  # a space apart: "29 (3.7)" is one cell
    serial = [
        t for t, b in sorted(nums, key=lambda w: cy(w[1])) if cols[0][0] <= cx(b) <= cols[0][1]
    ]
    counting = bool(serial) and all(t.isdigit() for t in serial)
    if (
        counting
        and len(cols) > 1
        and [int(t) - int(serial[0]) for t in serial] == list(range(len(serial)))
    ):
        return cols[1:]
    return cols


def _read_rows(
    lines: list[Line], rows: dict[str, list[int]], cols: list[tuple[float, float]]
) -> list[tuple[str, str, list[tuple[int, str, str, str]]]]:
    """Each row's key, label and (column, entry, field, value)s."""
    read = []
    for key, ln in rows.items():
        label: list[str] = []
        cells: dict[int, list[str]] = {}
        for i in ln:
            left, inside = _split(lines[i][1], cols)
            label += left
            for c, t in inside:
                cells.setdefault(c, []).append(t)
        values = [(c, *v) for c, texts in sorted(cells.items()) for v in _cell(texts)]
        read.append((key, key.split(".")[0], label, values))
    # named entries (genes) spread one agent's label over the lines of its band
    named = {band for _, band, _, vs in read if any(v[1] for v in vs)}
    whole: dict[str, list[str]] = {}
    for _, band, label, _ in read:
        if band in named:
            whole.setdefault(band, []).extend(label)
    read = _join_unlabelled(read)
    return [(key, norm(" ".join(whole.get(band, label))), vs) for key, band, label, vs in read]


def _join_unlabelled(read: list) -> list:
    """A label line with counts ("RC5  0 / 0 (-)") opens a row. Counts above it with no label
    join this row. They do not join if a (column, entry, field) occurs two times."""
    out: list = []
    for i, (key, band, label, vs) in enumerate(read):
        nxt = read[i + 1] if i + 1 < len(read) else None
        if label or nxt is None or not nxt[2] or nxt[1] != band:
            out.append((key, band, label, vs))
            continue
        if {v[:3] for v in vs} & {v[:3] for v in nxt[3]}:
            out.append((key, band, label, vs))
            continue
        read[i + 1] = (nxt[0], band, nxt[2], sorted(vs + nxt[3], key=lambda v: v[0]))
    return out


def _count_lines(lines: list[Line]) -> list[int]:
    """Lines that open a row: a count pair, a count with its (%), or counts over a line of (%).

    Empty unless most lines with numbers open a row. amrsn_tables reads the other tables.
    """
    out = []
    wrapped = False
    numeric = 0
    # in a table of pairs, a count with its (%) ends a wrapped pair ("101/10" over "1 (100)")
    pairs = any(FRAC.fullmatch(t) for _, ws in lines for t, _ in ws)
    for i, (_, ws) in enumerate(lines):
        texts = [t for t, _ in ws]
        nums = [t for t in texts if NUM.fullmatch(t)]
        if nums and all(YEAR.fullmatch(t) for t in nums):
            nums = []  # a heading of years
        blanks = [t for t in texts if t in BLANK]
        words = [t for t in texts if t not in BLANK and not _is_num(t)]
        opens = (
            any(FRAC.fullmatch(t) for t in texts)
            or (pairs and blanks and words and len(blanks) + len(words) == len(texts))
            or (nums and any(PCT.fullmatch(t) for t in texts) and not pairs)
            or (len(nums) >= 2 and _pcts_below(lines, i) >= 2)
        )
        if opens and not wrapped:
            out.append(i)
        numeric += bool(nums) and not wrapped
        wrapped = any(FRAC.fullmatch(t) and t.endswith("/") for t in texts)
    return out if len(out) * 2 >= numeric else []


def _pcts_below(lines: list[Line], i: int) -> int:
    """Percentages on the next line with numbers. A label ("RC2") can be between them."""
    for _, ws in lines[i + 1 :]:
        if any(_is_num(t) for t, _ in ws):
            return sum(bool(PCT.fullmatch(t)) for t, _ in ws)
    return 0


def _column(cols: list[tuple[float, float]], b: Box) -> int | None:
    """A word's column, the next one right (a gene name before its counts), or None (label)."""
    x = cx(b)
    if x < cols[0][0]:
        return None
    for i, (_, z) in enumerate(cols):
        if x <= z:
            return i
    return len(cols) - 1


def _split(
    ws: list[Word], cols: list[tuple[float, float]]
) -> tuple[list[str], list[tuple[int, str]]]:
    """A line's label words, and its other words by column.

    Words ending in ":" just left of the first column name its counts ("mecA: 102/105").
    """
    left = [w for w in ws if _column(cols, w[1]) is None]
    inside = [(c, w[0]) for w in ws if (c := _column(cols, w[1])) is not None]
    run = max(len(left) - 1, 0)
    while run > 0 and left[run][1][0] - left[run - 1][1][2] < 6:
        run -= 1
    tail = [t for t, _ in left[run:]]
    after = next((t for c, t in inside if c == 0), "")
    if tail and inside and (tail[-1].endswith(":") or after.startswith(":")):
        return [t for t, _ in left[:run]], [(0, t) for t in tail] + inside
    return [t for t, _ in left], inside


def _rows(
    lines: list[Line], counts: list[int], rules: list[float], cols: list[tuple[float, float]]
) -> tuple[dict[str, list[int]], dict[str, str]]:
    """Each row's lines keyed "band.n", and each row's group (the heading above it).

    A line goes with the count line at or above it in its band.
    In a band without counts, a line goes with the row above.
    A band of words from the left margin is a heading ("Carbapenem resistant").
    """
    by_band: dict[int, list[int]] = {}
    lead: dict[int, int] = {}  # a count line -> the count line whose row it is part of
    used: dict[int, set[int]] = {}  # a row's columns holding counts
    for i in counts:
        band = by_band.setdefault(_band(rules, lines[i][0]), [])
        here = _count_cols(lines[i][1], cols)
        # Centred cells start their counts on different lines (2024 Table 6.2).
        # Count lines in one band with no shared column are one row.
        if len(rules) > 2 and band and not (used[band[-1]] & here):  # a frame has only 2 rules
            lead[i] = band[-1]
            used[band[-1]] |= here
            continue
        band.append(i)
        lead[i], used[i] = i, here
    rows: dict[str, list[int]] = {}
    groups: dict[str, str] = {}
    numeric = {_band(rules, y) for y, ws in lines if any(_is_num(t) or t in BLANK for t, _ in ws)}
    name = {i: f"{b}.{n}" for b, ids in by_band.items() for n, i in enumerate(ids)}
    last = counts[0]
    heading: list[str] = []
    group = ""
    for i in range(counts[0], len(lines)):
        y, ws = lines[i]
        band = _band(rules, y)
        here = by_band.get(band)
        if i in lead and lead[i] != i:
            owner = lead[i]  # a later count line of a row opened above
        elif i in name:
            last = i
            owner = i
            group = " ".join(heading) or group
            heading = []
            groups[name[i]] = group
        elif here:
            owner = max([j for j in here if lines[j][0] <= y + 1], default=here[0])
        elif any(_is_num(t) for t, _ in ws):
            owner = last
        elif band not in numeric and ws[0][1][0] < cols[0][0]:
            # a ruled band of words only, from the left margin: a heading
            heading.append(" ".join(t for t, _ in ws))
            continue
        elif all(_column(cols, b) is None for _, b in ws):
            owner = last  # a label set apart from its numbers ("RC2", "aureus")
        else:
            continue  # words under the columns and no number: a repeated heading
        rows.setdefault(name[owner], []).append(i)
    for i in range(counts[0]):  # a label on the line above the table's first counts
        y = lines[i][0]
        if (b := _band(rules, y)) in by_band and not any(_is_num(t) for t, _ in lines[i][1]):
            rows[name[by_band[b][0]]].insert(0, i)
    return rows, groups


def _over_blocks(mids: list[float], centres: list[float]) -> bool:
    """Whether phrases sit centred over equal blocks of columns (a heading over groups)."""
    if len(centres) % len(mids):
        return False
    size = len(centres) // len(mids)
    step = min((b - a for a, b in pairwise(centres)), default=0.0)
    blocks = [sum(centres[i : i + size]) / size for i in range(0, len(centres), size)]
    return all(abs(m - c) <= 0.5 * step for m, c in zip(mids, blocks, strict=True))


def _count_cols(ws: list[Word], cols: list[tuple[float, float]]) -> set[int]:
    """Columns of a line holding a count ("2233/46")."""
    return {c for t, b in ws if FRAC.fullmatch(t) and (c := _column(cols, b)) is not None}


def _headers(lines: list[Line], cols: list[tuple[float, float]]) -> dict[int, str]:
    """Each column's heading: the words above the first counts, by column.

    A line of fewer phrases than half the columns heads groups of columns ("Staphylococcus
    aureus  MSSA  MRSA  CoNS" over 16 columns): each column takes the nearest phrase.
    """
    centres = [(a + z) / 2 for a, z in cols]
    out: dict[int, list[str]] = {}
    for _, ws in lines:
        phrases: list[tuple[str, float, float]] = []  # text, left, right
        for t, b in ws:
            if cx(b) < cols[0][0] - 5:
                continue
            if phrases and b[0] - phrases[-1][2] <= GAP:
                txt, x0, _ = phrases[-1]
                phrases[-1] = (f"{txt} {t}", x0, b[2])
            else:
                phrases.append((t, b[0], b[2]))
        if not phrases:
            continue
        mids = [(x0 + x1) / 2 for _, x0, x1 in phrases]
        if 1 < len(phrases) < len(cols) / 2 and _over_blocks(mids, centres):
            for c, x in enumerate(centres):
                near = min(range(len(mids)), key=lambda k: abs(mids[k] - x))
                out.setdefault(c, []).append(phrases[near][0])
            continue
        for (t, _, _), mid in zip(phrases, mids, strict=True):
            c = min(range(len(cols)), key=lambda i: abs(centres[i] - mid))
            out.setdefault(c, []).append(t)
    return {c: norm(" ".join(ts)) for c, ts in out.items()}
