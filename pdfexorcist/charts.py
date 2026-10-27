import math
import re
import statistics
from collections import defaultdict
from collections.abc import Sequence
from itertools import pairwise
from pathlib import Path
from typing import Any, NamedTuple

import pandas as pd

__all__ = ["ChartError", "read_charts"]

COORD_PT = (
    0.12  # vertex-to-marker offset in the NCVBDC report; measure per chart if exporters differ
)
SNAP_PT = 3  # a tick label this close to a gridline sits on it
NICE = (1, 2, 2.5, 5)  # Excel axis steps are these times a power of ten
NUMBER = re.compile(r"-?\d[\d,]*(\.\d+)?%?|-?\.\d+%?")
COLUMNS = ["page", "chart", "title", "series", "category", "value", "pm", "status"]


class ChartError(ValueError):
    """A chart whose axes or points cannot be placed."""


class Word(NamedTuple):
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    block: int = -1  # MuPDF's text block: the lines of a wrapped title share one

    @property
    def mid(self) -> float:
        return (self.y0 + self.y1) / 2


class Rule(NamedTuple):
    """A flat stroked segment: gridline, axis or legend sample."""

    p: Any  # pymupdf.Point, left end
    q: Any
    color: str


class Series(NamedTuple):
    rect: Any  # pymupdf.Rect
    seg: list  # (start, end) points, left to right
    color: str


def _number(text: str) -> float | None:
    return float(text.replace(",", "").rstrip("%")) if NUMBER.fullmatch(text) else None


def has_letters(text: str) -> bool:
    """Whether text holds a word (two letters running): a title, label or legend name."""
    return bool(re.search(r"[A-Za-z]{2}", text))


def _hex(rgb: tuple) -> str:
    return "#" + "".join(f"{round(c * 255):02x}" for c in rgb)


def _style(d: dict) -> str:
    """A path's colour, and its dash pattern when dashed: Excel draws a series and its average
    in one colour, one of them dashed."""
    dashes = str(d.get("dashes") or "")
    dashed = bool(re.search(r"\[\s*[\d.]", dashes))
    return _hex(d["color"]) + (" " + " ".join(dashes.split()) if dashed else "")


def _segments(d: dict) -> list[tuple[Any, Any]]:
    """The straight segments of a path, or [] when it has curves or rectangles."""
    items = d["items"]
    return [(i[1], i[2]) for i in items] if all(i[0] == "l" for i in items) else []


def _is_series(seg: list) -> bool:
    """A connected left-to-right polyline; gridlines are disjoint, an all-zero series is flat."""
    return (
        bool(seg)
        and all(b.x - a.x > 0.5 for a, b in seg)
        and all(abs(p[1].x - q[0].x) + abs(p[1].y - q[0].y) < 0.01 for p, q in pairwise(seg))
        and (len(seg) > 1 or abs(seg[0][1].y - seg[0][0].y) > 0.5)
    )


def _contains(outer: Any, inner: Any, slack: float = 1.0) -> bool:
    return (
        outer.x0 - slack <= inner.x0
        and outer.y0 - slack <= inner.y0
        and inner.x1 <= outer.x1 + slack
        and inner.y1 <= outer.y1 + slack
    )


def _at(box: Any, p: Any) -> bool:
    """Whether the point p lies in box."""
    return box.x0 <= p.x <= box.x1 and box.y0 <= p.y <= box.y1


def _rows(words: list[Word]) -> list[list[Word]]:
    """Words grouped into lines by their vertical centre, top to bottom, each left to right."""
    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.mid, w.x0)):
        if rows and abs(w.mid - rows[-1][0].mid) < 2:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(r, key=lambda w: w.x0) for r in rows]


def _labels(row: list[Word], gap: float = 3.0) -> list[tuple[float, str]]:
    """(x centre, text) for each label in a row; words closer than gap join one label."""
    out: list[list] = []
    for w in row:
        if out and w.x0 - out[-1][1] < gap:
            out[-1][1:] = [w.x1, out[-1][2] + " " + w.text]
        else:
            out.append([w.x0, w.x1, w.text])
    return [((x0 + x1) / 2, text) for x0, x1, text in out]


def _frame(rect: Any, boxes: list, numbers: list[Word]) -> Any | None:
    """The smallest box around the series with a y axis (two numbers left of it); boxes by area."""
    left = [w for w in numbers if w.x1 <= rect.x0]
    for box in boxes:
        if _contains(box, rect) and sum(_contains(box, w) for w in left) >= 2:
            return box
    return None


def _y_axis(ticks: list[Word], grid: list[float]) -> tuple[float, float]:
    """(a, b) of value = a + b*y; ticks snap to gridlines, as text centres sit up to 0.5 pt off."""
    right = max(w.x1 for w in ticks)
    ticks = [w for w in ticks if right - w.x1 < 3]  # one right-aligned column
    vs = [float(_number(w.text) or 0) for w in ticks]  # ticks are numbers
    snapped: list[float | None] = []
    for w in ticks:
        near = min(grid, key=lambda g: abs(g - w.mid), default=None)
        snapped.append(near if near is not None and abs(near - w.mid) < SNAP_PT else None)
    # a label without its gridline (only the axis line drawn) sits off by the same amount as
    # the labels on gridlines
    shift = statistics.median(
        [y - w.mid for y, w in zip(snapped, ticks, strict=True) if y is not None] or [0.0]
    )
    ys = [w.mid + shift if y is None else y for y, w in zip(snapped, ticks, strict=True)]
    if len(set(ys)) < 2:
        raise ChartError("fewer than two y tick labels")
    b, a = statistics.linear_regression(ys, vs)
    step = min((abs(p - q) for p, q in pairwise(sorted(vs)) if p != q), default=0.0)
    worst = max(abs(a + b * y - v) for y, v in zip(ys, vs, strict=True))
    if step and worst <= step / 10:
        return a, b
    decimals = max(_decimals(w.text) for w in ticks)
    nice = _nice_axis(ys, vs, decimals)
    if nice is None:
        raise ChartError(
            f"y tick labels are off a straight line by {worst:g}, and no Excel axis rounds "
            "to them (a log axis?)"
        )
    return nice


def _decimals(text: str) -> int:
    """Digits printed after the point: "12.5%" has 1."""
    return len(text.rstrip("%").partition(".")[2])


def _shown(v: float, decimals: int) -> float:
    """v as Excel shows it with this many decimals: half away from zero."""
    q = math.floor(abs(v) * 10**decimals + 0.5 + 1e-9) / 10**decimals
    return math.copysign(q, v) if q else 0.0


def _nice_axis(ys: list[float], vs: list[float], decimals: int) -> tuple[float, float] | None:
    """(a, b) of the one Excel axis whose labels, rounded to decimals, read vs; else None.

    An axis from 0 wins, as Excel's does; 0.375 ... 0.6 by 0.025 also reads 0 0 0 0 0 1 1 1 1 1.
    """
    pairs = sorted(zip(ys, vs, strict=True), reverse=True)  # bottom gridline first
    ys, vs = [y for y, _ in pairs], [v for _, v in pairs]
    gaps = [p - q for p, q in pairwise(ys)]
    if max(gaps) - min(gaps) > 2 * COORD_PT:
        return None  # gridlines not evenly spaced
    half = 10.0**-decimals / 2  # rounding error of a label
    fits = []
    for k in range(-decimals - 4, 10):
        for m in NICE:
            s = m * 10.0**k
            lo = max(v - half - i * s for i, v in enumerate(vs))  # starts every label allows
            hi = min(v + half - i * s for i, v in enumerate(vs))
            fits += [
                (j * s, s)
                for j in range(math.ceil(lo / s - 1e-9), math.floor(hi / s + 1e-9) + 1)
                if all(_shown((j + i) * s, decimals) == v for i, v in enumerate(vs))
            ]
    fits = [f for f in fits if f[0] == 0] or fits
    if len(fits) != 1:
        return None
    start, s = fits[0]
    b, a = statistics.linear_regression(ys, [start + i * s for i in range(len(vs))])
    return a, b


def heading(words: list[Word], box: Any, others: Sequence = ()) -> str:
    """The line just over the box and within its width, unless it belongs to another box,
    with the lines over it in its text block (a title wrapped onto two lines)."""
    above = [
        w
        for w in words
        if box.y0 - 40 < w.y1 <= box.y0 + 1
        and w.x1 > box.x0  # a title may start left of a picture
        and w.x0 < box.x1
        and not any(_contains(o, w) for o in others)
    ]
    if not above:
        return ""
    rows = _rows(above)
    blocks = {w.block for w in rows[-1]} - {-1}
    first = len(rows) - 1
    while first and blocks and {w.block for w in rows[first - 1]} <= blocks:
        first -= 1
    title = [w for r in rows[first:] for w in r]
    if blocks:  # whole lines: a title may start left of the box ("GRAPH 3:" over a picture)
        top, bottom = min(w.mid for w in title) - 1, max(w.mid for w in title) + 1
        title = [w for w in words if w.block in blocks and top <= w.mid <= bottom]
    return " ".join(w.text for r in _rows(title) for w in r)


def _chart(
    box: Any, series: list[Series], flat: list[Rule], words: list[Word], others: list
) -> list[list]:
    """[title, series, category, value, pm] for each point of the chart in box; others are the
    page's other chart boxes."""
    inside = [w for w in words if _contains(box, w)]
    x0 = min(s.rect.x0 for s in series)
    width = max(s.rect.x1 for s in series) - x0
    grid = [r.p.y for r in flat if r.q.x - r.p.x > width / 2 and _at(box, r.p)]
    ticks = [w for w in inside if _number(w.text) is not None and w.x1 <= x0]
    a, b = _y_axis(ticks, grid)
    low = max(w.mid for w in ticks)
    below = [w for w in inside if w.y0 > low + 2 and w.x1 > x0 - 20]
    turned = [w for w in below if w.y1 - w.y0 > 1.5 * (w.x1 - w.x0) and has_letters(w.text)]
    if below and len(turned) > len(below) / 2:  # sideways labels: one per column, read by x
        top = statistics.median(
            w.y0 for w in turned
        )  # they end at the axis; a short one is not tall
        turned = [w for w in below if abs(w.y0 - top) < 2 and has_letters(w.text)]
        cols: list[list[Word]] = []
        for w in sorted(turned, key=lambda w: w.x0):
            if cols and w.x0 - cols[-1][-1].x0 < 2:
                cols[-1].append(w)
            else:
                cols.append([w])
        cats = [
            ((c[0].x0 + c[0].x1) / 2, " ".join(w.text for w in sorted(c, key=lambda w: -w.y1)))
            for c in cols
        ]
    else:
        cats = _labels(_rows(below)[0]) if below else []
    if len(cats) < 2:
        raise ChartError("no category labels under the plot")
    tol = min(q[0] - p[0] for p, q in pairwise(cats)) / 4

    colors = {s.color for s in series}
    samples = sorted(  # a flat line in a series colour, shorter than a gridline
        (r for r in flat if r.color in colors and r.q.x - r.p.x <= width / 2 and _at(box, r.p)),
        key=lambda r: (r.p.y, r.p.x),
    )
    names: dict[str, str] = {}
    for i, r in enumerate(samples):
        nxt = next((o.p.x for o in samples[i + 1 :] if abs(o.p.y - r.p.y) < 2), box.x1)
        text = [w.text for w in inside if abs(w.mid - r.p.y) < 4 and r.q.x < w.x0 < nxt]
        if text:
            names.setdefault(r.color, " ".join(text))

    values: dict[str, dict[str, float]] = defaultdict(dict)
    longest = max(len(s.seg) for s in series)
    for s in series:
        name = names.get(s.color, s.color)
        points = [s.seg[0][0]] + [q for _, q in s.seg]
        if len(s.seg) < longest / 2:
            continue  # a few strokes beside full series: a label's leader line
        for pt in points:
            x, cat = min(cats, key=lambda c: abs(c[0] - pt.x))
            if abs(x - pt.x) > tol:
                raise ChartError(f"a point at x={pt.x:.1f} is under no category")
            if cat in values[name]:
                raise ChartError(f"series {name!r} has two points at {cat!r}")
            values[name][cat] = a + b * pt.y
    top = min(min(w.y0 for w in ticks), min(s.rect.y0 for s in series))
    own = [w for w in inside if w.y1 <= top]  # Excel's own title, in the box over the plot
    title = heading(words, box, others) or (" ".join(w.text for w in _rows(own)[0]) if own else "")
    pm = abs(b) * COORD_PT
    return [
        [title, name, cat, _round(vals[cat], pm), pm]
        for name, vals in values.items()
        for _, cat in cats
        if cat in vals
    ]


def _round(v: float, pm: float) -> float:
    return round(v, max(0, 1 - math.floor(math.log10(pm)))) if pm > 0 else v


def _vector_page(doc: Any, no: int, title: str | None) -> tuple[list, list, int]:
    """Rows and skipped charts of the vector charts on one page, and how many charts it has."""
    import pymupdf

    page = doc[no - 1]
    area = page.rect.width * page.rect.height
    boxes: list = []
    series: list[Series] = []
    flat: list[Rule] = []
    for d in page.get_drawings():
        r = d["rect"]
        if r.width > 100 and r.height > 60 and r.width * r.height < 0.9 * area:
            boxes.append(r)
        seg = _segments(d) if d.get("color") and "s" in d["type"] else []
        if _is_series(seg):
            series.append(Series(r, seg, _style(d)))
        else:
            flat += [Rule(p, q, _style(d)) for p, q in seg if abs(p.y - q.y) < 0.5]
    if not series:
        return [], [], 0  # words are the slow part
    words = [Word(*w[:6]) for w in page.get_text("words")]
    numbers = [w for w in words if _number(w.text) is not None]
    boxes.sort(key=lambda b: b.width * b.height)
    charts: dict[tuple, list[Series]] = defaultdict(list)
    for s in series:
        box = _frame(s.rect, boxes, numbers)
        if box is not None:
            charts[tuple(box)].append(s)
    rows, skipped = [], []
    for n, (key, members) in enumerate(sorted(charts.items(), key=lambda kv: kv[0][1]), 1):
        try:
            others = [pymupdf.Rect(k) for k in charts if k != key]
            points = _chart(pymupdf.Rect(key), members, flat, words, others)
        except ChartError as e:  # skip the chart, keep the page
            skipped.append((no, n, str(e)))
            continue
        if title and points and not re.search(title, points[0][0]):
            continue
        rows += [[no, n, *p] for p in points]
    return rows, skipped, len(charts)


def read_charts(
    pdf: str | Path, pages: list[int] | None = None, settings: Any = None
) -> pd.DataFrame:
    """One row per point of each line chart on the pages (1-based; default all).

    Vector values carry a pm and the status estimated; values in pictures are voted by OCR engines.
    settings is a ChartSettings; skipped charts are in attrs["skipped"] as (page, chart, reason),
    and what kept pictures unread in attrs["notes"].
    """
    import pymupdf

    from ._chart_settings import ChartSettings

    settings = settings or ChartSettings()
    rows: list[list] = []
    skipped: list[tuple[int, int, str]] = []
    notes: list[str] = []
    with pymupdf.open(pdf) as doc:
        numbers = list(pages or range(1, doc.page_count + 1))
        drawn: dict[int, int] = {}  # page -> its vector charts
        if settings.kind != "image":
            for no in numbers:
                got, left, drawn[no] = _vector_page(doc, no, settings.title)
                rows += got
                skipped += left
        df = pd.DataFrame(rows, columns=COLUMNS[:-1]).assign(status="estimated")
        if settings.kind == "image" or (settings.kind == "auto" and not rows):  # one kind a report
            from ._chart_image import image_charts

            plain = [no for no in numbers if not drawn.get(no)]
            got, left, notes = image_charts(doc, plain, settings)
            skipped += left
            if got:
                df = pd.DataFrame(got)
    df.attrs["notes"] = notes
    df.attrs["skipped"] = skipped
    return df
