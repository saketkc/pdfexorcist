"""Pie and donut charts drawn as filled paths: wedges and the labels printed on them.

Values come from the labels only (curve points give the angles too roughly); the check is that
a pie's percentages add up to 100.
"""

import math
from functools import lru_cache
from typing import NamedTuple

import nacnet_bars as nb

from pdfexorcist.cells import Box


class Wedge(NamedTuple):
    color: str
    series: str
    pts: list[tuple[float, float]]


class Pie(NamedTuple):
    page: int
    no: int
    title: str
    heading: str  # the word in the hole ("2017")
    box: Box
    wedges: list[Wedge]
    leaders: list[list[tuple[float, float]]]  # leader lines from labels to wedges


def _inside(pt: tuple[float, float], pts: list[tuple[float, float]]) -> bool:
    x, y = pt
    hit = False
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1], strict=True):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def _dist(pt: tuple[float, float], pts: list[tuple[float, float]]) -> float:
    """Distance from a point to a polygon's edges (0 inside)."""
    if _inside(pt, pts):
        return 0.0
    best = math.inf
    for a, b in zip(pts, pts[1:] + pts[:1], strict=True):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(
            0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / ((dx * dx + dy * dy) or 1))
        )
        best = min(best, math.dist(pt, (a[0] + t * dx, a[1] + t * dy)))
    return best


@lru_cache(maxsize=4)
def page_pies(path: str, page_no: int) -> list[Pie]:
    import pdfplumber

    with pdfplumber.open(path) as doc:
        page = doc.pages[page_no - 1]
        ws = nb.words(page)
        rects = [r for r in page.rects if r.get("fill")]
        legend = nb._legend(rects, ws, set())
        curves = [
            c
            for c in page.curves
            if c.get("fill") and nb._color(c.get("non_stroking_color")) and len(c["pts"]) >= 4
        ]
        lines = [
            [(float(x), float(y)) for x, y in c["pts"]]
            for c in page.curves
            if not c.get("fill") and len(c["pts"]) <= 4
        ] + [
            [(float(ln["x0"]), float(ln["top"])), (float(ln["x1"]), float(ln["bottom"]))]
            for ln in page.lines
        ]
    groups: list[list[dict]] = []
    for c in sorted(curves, key=lambda c: (c["top"], c["x0"])):
        for g in groups:
            b = (
                min(o["x0"] for o in g),
                min(o["top"] for o in g),
                max(o["x1"] for o in g),
                max(o["bottom"] for o in g),
            )
            if (
                c["x0"] < b[2] + 1
                and c["x1"] > b[0] - 1
                and c["top"] < b[3] + 1
                and c["bottom"] > b[1] - 1
            ):
                g.append(c)
                break
        else:
            groups.append([c])
    caps = nb.captions(ws)
    out = []
    for no, g in enumerate(gr for gr in groups if len(gr) >= 2):
        box = (
            min(o["x0"] for o in g),
            min(o["top"] for o in g),
            max(o["x1"] for o in g),
            max(o["bottom"] for o in g),
        )
        cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
        r = (box[2] - box[0]) / 2
        wedges = []
        for c in g:
            pts = [(float(x), float(y)) for x, y in c["pts"]]
            col = nb._color(c["non_stroking_color"]) or ""
            wedges.append(Wedge(col, legend.get(col, col), pts))
        hole = [
            t
            for t, b in ws
            if math.dist(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), (cx, cy)) < 0.35 * r
            and not any(_inside(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2), w.pts) for w in wedges)
        ]
        above = [cp for cp in caps if cp[1][3] <= box[1] + 1]
        title = max(above, key=lambda cp: cp[1][3])[0] if above else nb._last_caption(path, page_no)
        leaders = [
            ln
            for ln in lines
            if min(min(_dist(p, w.pts) for w in wedges) for p in (ln[0], ln[-1])) < 3
            and max(min(_dist(p, w.pts) for w in wedges) for p in (ln[0], ln[-1])) > 3
        ]
        out.append(Pie(page_no, no, title, " ".join(hole), box, wedges, leaders))
    return out


def owner(pie: Pie, b: Box) -> Wedge | None:
    """The wedge a label sits in, else the one its leader line ends in, else the nearest one
    within a radius."""
    pt = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    r = (pie.box[2] - pie.box[0]) / 2
    if not any(_inside(pt, w.pts) for w in pie.wedges):
        for ln in pie.leaders:
            for near, far in ((ln[0], ln[-1]), (ln[-1], ln[0])):
                if b[0] - 6 <= near[0] <= b[2] + 6 and b[1] - 6 <= near[1] <= b[3] + 6:
                    return min(pie.wedges, key=lambda w: _dist(far, w.pts))
    best = min(pie.wedges, key=lambda w: _dist(pt, w.pts))
    return best if _dist(pt, best.pts) < r else None
