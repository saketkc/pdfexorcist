"""Bar charts drawn as filled rectangles: bars, series, categories and the value axis.

Geometry comes from pdfplumber, so every engine gets the same slots and votes only on labels.
`pm` is the value of 0.5 pt of drawn length.
"""

import re
from functools import lru_cache
from itertools import pairwise
from typing import Any, NamedTuple

from pdfexorcist.cells import Box

NUM = re.compile(r"-?\d+(?:\.\d+)?%?")
CAPTION = re.compile(r"^(Figure|Fig\.|Table)\s*(\d+[a-z]?(?:\s*&\s*\d+[a-z]?)?)\s*[:.]?", re.I)
SWATCH = 9.0  # a legend sample is a filled square at most this wide
NEAR = 14.0  # a label this close past a bar's end belongs to that bar
PM_PT = 0.5


class Bar(NamedTuple):
    box: Box
    color: str
    slot: int  # category position along the category axis, from 0
    series: str
    category: str
    value: float | None  # from the drawn length (None without an axis)
    pm: float | None


class Chart(NamedTuple):
    page: int
    no: int
    title: str
    box: Box  # bars and their labels
    vertical: bool
    bars: list[Bar]
    ticks: list[tuple[str, Box]]  # value-axis labels


def _color(c: Any) -> str | None:
    """Hex of a fill, or None for white, black and grays."""
    if c is None:
        return None
    c = tuple(c) if isinstance(c, (list, tuple)) else (c,)
    if len(c) == 4:  # cmyk
        k = c[3]
        c = tuple((1 - v) * (1 - k) for v in c[:3])
    if len(c) != 3 or max(c) - min(c) < 0.015:
        return None
    return "#" + "".join(f"{round(v * 255):02x}" for v in c)


def _turned(c: dict) -> bool:
    return abs(c["matrix"][1]) > 0.5  # text turned 90 degrees (pdfplumber calls it upright)


def words(page: Any) -> list[tuple[str, Box]]:
    """Level words, then turned words (Excel's sideways category labels) read along their run."""
    level = page.filter(lambda o: o.get("object_type") != "char" or not _turned(o))
    ws = [
        (w["text"], (w["x0"], w["top"], w["x1"], w["bottom"]))
        for w in level.extract_words(extra_attrs=["size"])
    ]  # a size change ends a word
    turned = sorted(
        (c for c in page.chars if _turned(c)), key=lambda c: (round(c["x0"]), -c["top"])
    )
    runs: list[list[dict]] = []
    for c in turned:
        up = c["matrix"][1] > 0  # reads bottom to top
        if runs and abs(runs[-1][-1]["x0"] - c["x0"]) < 1 and (runs[-1][-1]["matrix"][1] > 0) == up:
            prev = runs[-1][-1]
            gap = (prev["top"] - c["bottom"]) if up else (c["top"] - prev["bottom"])
            if gap < 2 * c["size"]:
                runs[-1].append(c)
                continue
        runs.append([c])
    for run in runs:
        if run[0]["matrix"][1] < 0:
            run.sort(key=lambda c: c["top"])
        else:
            run.sort(key=lambda c: -c["top"])
        text = ""
        for prev, c in zip([None, *run], run, strict=False):
            if prev is not None:
                gap = abs(
                    (prev["top"] - c["bottom"])
                    if run[0]["matrix"][1] > 0
                    else (c["top"] - prev["bottom"])
                )
                if gap > 0.2 * c["size"]:
                    text += " "
            text += c["text"]
        box = (
            min(c["x0"] for c in run),
            min(c["top"] for c in run),
            max(c["x1"] for c in run),
            max(c["bottom"] for c in run),
        )
        ws.append((text.strip(), box))
    return [w for w in ws if w[0]]


def _lines(ws: list[tuple[str, Box]]) -> list[list[tuple[str, Box]]]:
    out: list[list[tuple[str, Box]]] = []
    for w in sorted(ws, key=lambda w: (w[1][1] + w[1][3]) / 2):
        mid = (w[1][1] + w[1][3]) / 2
        if out and abs(mid - (out[-1][0][1][1] + out[-1][0][1][3]) / 2) < 3:
            out[-1].append(w)
        else:
            out.append([w])
    return [sorted(line, key=lambda w: w[1][0]) for line in out]


def captions(ws: list[tuple[str, Box]]) -> list[tuple[str, Box]]:
    """'Figure 5: ...' lines with the box of the line."""
    out = []
    for line in _lines(ws):
        text = " ".join(t for t, _ in line)
        if CAPTION.match(text) and not re.search(r"\.{5,}", text):  # not the list of figures
            b = line[0][1]
            out.append((text, (b[0], b[1], line[-1][1][2], b[3])))
    return out


def _legend(rects: list[dict], ws: list[tuple[str, Box]], used: set) -> dict[str, str]:
    """Color -> series name: a small filled square with words on its right. Every word from a
    sample to the next sample on its line goes in used (an ATC code after the name too)."""
    out: dict[str, str] = {}
    swatches = [
        r
        for r in rects
        if _color(r.get("non_stroking_color")) and r["width"] <= SWATCH and r["height"] <= SWATCH
    ]
    for r in swatches:
        col = _color(r.get("non_stroking_color"))
        mid = (r["top"] + r["bottom"]) / 2
        nxt = min(
            (
                s["x0"]
                for s in swatches
                if abs((s["top"] + s["bottom"]) / 2 - mid) < 3 and s["x0"] > r["x1"]
            ),
            default=r["x1"] + 450,
        )
        right = sorted(
            (w for w in ws if abs((w[1][1] + w[1][3]) / 2 - mid) < 4 and r["x1"] <= w[1][0] < nxt),
            key=lambda w: w[1][0],
        )
        name: list[str] = []
        x = r["x1"]
        for t, b in right:
            used.add(b)
            if b[0] - x <= 8:
                name.append(t)
                x = b[2]
            else:
                x = float("inf")  # the name ended
        if name and col and col not in out:
            out[col] = " ".join(name)
    return out


def _clusters(rects: list[dict], frames: list[dict]) -> list[list[dict]]:
    """Bars in one chart frame (the smallest white box holding them) form one chart; bars
    outside any frame form charts with the bars near them."""

    def frame(r: dict) -> int | None:
        cx, cy = (r["x0"] + r["x1"]) / 2, (r["top"] + r["bottom"]) / 2
        inside = [
            i
            for i, f in enumerate(frames)
            if f["x0"] <= cx <= f["x1"] and f["top"] <= cy <= f["bottom"]
        ]
        return (
            min(inside, key=lambda i: frames[i]["width"] * frames[i]["height"]) if inside else None
        )

    framed: dict[int, list[dict]] = {}
    loose = []
    for r in rects:
        i = frame(r)
        if i is None:
            loose.append(r)
        else:
            framed.setdefault(i, []).append(r)
    groups: list[list[dict]] = list(framed.values())
    # loose bars: one chart when near along one axis and overlapping along the other (side by
    # side on a shared baseline, or stacked rows), joined transitively
    parent = list(range(len(loose)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def near(a: dict, b: dict) -> bool:
        x_gap = max(a["x0"], b["x0"]) - min(a["x1"], b["x1"])
        y_gap = max(a["top"], b["top"]) - min(a["bottom"], b["bottom"])
        reach = max(
            40.0,
            3 * max(a["width"], b["width"]) if y_gap <= 2 else 3 * max(a["height"], b["height"]),
        )
        return (x_gap < reach and y_gap <= 2) or (y_gap < reach and x_gap <= 2)

    for i, a in enumerate(loose):
        for j in range(i):
            if near(a, loose[j]):
                parent[root(i)] = root(j)
    joined: dict[int, list[dict]] = {}
    for i, r in enumerate(loose):
        joined.setdefault(root(i), []).append(r)
    groups += list(joined.values())
    return [g for g in groups if len(g) >= 2]


def _axis(ticks: list[tuple[str, Box]], vertical: bool) -> tuple[float, float] | None:
    """value = a + b * position, least squares through the tick labels."""
    pts = [
        ((b[1] + b[3]) / 2 if vertical else (b[0] + b[2]) / 2, float(t.rstrip("%")))
        for t, b in ticks
    ]
    if len(pts) < 3:
        return None
    n = len(pts)
    mx = sum(p for p, _ in pts) / n
    my = sum(v for _, v in pts) / n
    sxx = sum((p - mx) ** 2 for p, _ in pts)
    if sxx == 0:
        return None
    b = sum((p - mx) * (v - my) for p, v in pts) / sxx
    a = my - b * mx
    step = abs(pts[1][1] - pts[0][1]) or 1
    if any(abs(a + b * p - v) > step / 10 for p, v in pts):
        return None
    return a, b


def _ticks(ws: list[tuple[str, Box]], bars: list[dict], vertical: bool) -> list[tuple[str, Box]]:
    """Numbers in one column left of the bars (vertical) or one row below them."""
    x0 = min(r["x0"] for r in bars)
    y0 = min(r["top"] for r in bars)
    y1 = max(r["bottom"] for r in bars)
    x1 = max(r["x1"] for r in bars)
    if vertical:
        cand = [
            w
            for w in ws
            if NUM.fullmatch(w[0])
            and w[1][2] <= x0 + 1
            and x0 - w[1][2] < 40
            and y0 - 40 < w[1][1] < y1 + 15
        ]
        key = lambda w: round(w[1][2])  # noqa: E731 - right edges align
    else:
        cand = [
            w
            for w in ws
            if NUM.fullmatch(w[0])
            and (w[1][1] >= y1 - 1 or w[1][3] <= y0 + 1)
            and x0 - 15 < w[1][0] < x1 + 40
            and min(abs(w[1][1] - y1), abs(y0 - w[1][3])) < 30
        ]
        key = lambda w: round((w[1][1] + w[1][3]) / 2)  # noqa: E731
    best: list[tuple[str, Box]] = []
    for k in {key(w) for w in cand}:
        col = [w for w in cand if abs(key(w) - k) <= 2]
        if len(col) > len(best):
            best = col
    return best if len(best) >= 3 else []


def _zone(
    ws: list[tuple[str, Box]], bars: list[dict], vertical: bool, skip: set, depth: float
) -> list[tuple[str, Box]]:
    """Words below the bars (vertical) or left of them (horizontal), within depth."""
    if vertical:
        base = max(r["bottom"] for r in bars)
        x0, x1 = min(r["x0"] for r in bars), max(r["x1"] for r in bars)
        got = [
            w
            for w in ws
            if w[1][1] >= base - 1
            and w[1][3] - base < depth
            and x0 - 30 < w[1][2]
            and w[1][0] < x1 + 30
        ]
    else:
        left = min(r["x0"] for r in bars)
        y0, y1 = min(r["top"] for r in bars), max(r["bottom"] for r in bars)
        got = [
            w
            for w in ws
            if w[1][2] <= left + 1
            and left - w[1][0] < depth
            and y0 - 10 < w[1][3]
            and w[1][1] < y1 + 10
        ]
    return [w for w in got if w[1] not in skip and not CAPTION.match(w[0])]


def _labels(got: list[tuple[str, Box]], vertical: bool) -> list[tuple[str, float]]:
    """Category labels with their centre along the category axis. Turned words in neighbouring
    columns join (a label on two turned lines); level words join into blocks of nearby lines."""
    turned = [w for w in got if w[1][3] - w[1][1] > 1.5 * (w[1][2] - w[1][0]) and len(w[0]) > 1]
    level = [w for w in got if w not in turned]
    blocks: list[list[tuple[str, Box]]] = []
    for w in sorted(turned, key=lambda w: w[1][0]):
        last = blocks[-1][-1][1] if blocks else None
        if (
            last
            and w[1][0] - last[2] < 0.45 * (last[2] - last[0])
            and w[1][1] < last[3]
            and w[1][3] > last[1]
        ):
            blocks[-1].append(w)
        else:
            blocks.append([w])
    for line in _lines(level):
        for t, b in line:
            for blk in (
                blocks if vertical else blocks[-1:]
            ):  # beside a horizontal bar, a line is a label
                lb = blk[-1][1]
                if blk[0][1][3] - blk[0][1][1] > 1.5 * (blk[0][1][2] - blk[0][1][0]):
                    continue  # a turned block
                if (
                    vertical
                    and 0 <= b[1] - lb[3] < 0.8 * (b[3] - b[1]) + 2
                    and b[0] < lb[2] + 2
                    and b[2] > lb[0] - 2
                ):
                    blk.append((t, b))  # next line of the same label
                    break
                if abs(b[1] - lb[1]) < 2 and 0 <= b[0] - lb[2] < 5:
                    blk.append((t, b))  # next word on the same line
                    break
            else:
                blocks.append([(t, b)])
    out = []
    for blk in blocks:
        x0 = min(b[0] for _, b in blk)
        x1 = max(b[2] for _, b in blk)
        y0 = min(b[1] for _, b in blk)
        y1 = max(b[3] for _, b in blk)
        out.append((" ".join(t for t, _ in blk), (x0 + x1) / 2 if vertical else (y0 + y1) / 2))
    return out


def _name(
    labels: list[tuple[str, float]], spans: list[tuple[float, float]], mid: float, slot: int
) -> str:
    """A bar's category: by order when there is one label per slot, else the nearest label."""
    if len(labels) == len(spans):
        return sorted(labels, key=lambda lab: lab[1])[slot][0]
    pitch = min((b[0] - a[0] for a, b in pairwise(spans)), default=50.0)
    near = [lab for lab in labels if abs(lab[1] - mid) < max(pitch, 12)]
    return min(near, key=lambda lab: abs(lab[1] - mid))[0] if near else ""


def _slots(bars: list[dict], vertical: bool) -> list[tuple[float, float]]:
    """Category spans along the category axis: bars whose spans overlap share a slot.

    ponytail: clustered (side by side) series get one slot each; their category comes from the
    label under each bar.
    """
    lo, hi = ("x0", "x1") if vertical else ("top", "bottom")
    spans: list[list[float]] = []
    for r in sorted(bars, key=lambda r: r[lo]):
        if spans and r[lo] < spans[-1][1] - 0.5:
            spans[-1][1] = max(spans[-1][1], r[hi])
        else:
            spans.append([r[lo], r[hi]])
    return [(a, b) for a, b in spans]


def _last_caption(path: str, page_no: int) -> str:
    """The last figure caption on the pages before: a chart continued from there."""
    import pdfplumber

    with pdfplumber.open(path) as doc:
        for p in range(page_no - 1, 0, -1):
            caps = [c for c in captions(words(doc.pages[p - 1])) if not c[0].startswith("Table")]
            if caps:
                return max(caps, key=lambda c: c[1][3])[0]
    return ""


def _heading(ws: list[tuple[str, Box]], group: list[dict], frames: list[dict], ticks: list) -> str:
    """An in-chart heading ("2019"): words in the chart frame above the bars, off the axis."""
    cx = sum(r["x0"] + r["x1"] for r in group) / (2 * len(group))
    cy = sum(r["top"] + r["bottom"] for r in group) / (2 * len(group))
    holding = [f for f in frames if f["x0"] <= cx <= f["x1"] and f["top"] <= cy <= f["bottom"]]
    if not holding:
        return ""
    f = min(holding, key=lambda f: f["width"] * f["height"])
    top = min(r["top"] for r in group)
    x0, x1 = min(r["x0"] for r in group), max(r["x1"] for r in group)
    tick_boxes = {b for _, b in ticks}
    tall = 1.3 * max((b[3] - b[1] for _, b in ticks), default=0)  # a heading is printed larger
    got = [
        w
        for w in ws
        if w[1] not in tick_boxes
        and f["top"] <= w[1][1]
        and w[1][3] <= top
        and w[1][3] - w[1][1] >= tall
        and x0 + (x1 - x0) * 0.2 <= (w[1][0] + w[1][2]) / 2 <= x1 - (x1 - x0) * 0.2
    ]
    return " ".join(t for line in _lines(got) for t, _ in line)


def _depth(
    group: list[dict], frames: list[dict], ws: list[tuple[str, Box]], vertical: bool
) -> float:
    """How far category labels reach from the bars: to the chart frame's edge, else to the
    first gap of more than a line."""
    cx = sum(r["x0"] + r["x1"] for r in group) / (2 * len(group))
    cy = sum(r["top"] + r["bottom"] for r in group) / (2 * len(group))
    holding = [f for f in frames if f["x0"] <= cx <= f["x1"] and f["top"] <= cy <= f["bottom"]]
    if holding:
        f = min(holding, key=lambda f: f["width"] * f["height"])
        return (
            (f["bottom"] - max(r["bottom"] for r in group))
            if vertical
            else (min(r["x0"] for r in group) - f["x0"])
        )
    if not vertical:
        return 200.0
    base = max(r["bottom"] for r in group)
    x0, x1 = min(r["x0"] for r in group), max(r["x1"] for r in group)
    below = sorted(b for _, b in ws if b[1] >= base - 1 and x0 - 10 <= (b[0] + b[2]) / 2 <= x1 + 10)
    reach = base
    for b in sorted(below, key=lambda b: b[1]):
        if b[1] - reach > 12:
            break
        reach = max(reach, b[3])
    return reach - base + 1


@lru_cache(maxsize=4)
def page_charts(path: str, page_no: int) -> list[Chart]:
    """Every bar chart on a page (page_no from 1)."""
    import pdfplumber

    with pdfplumber.open(path) as doc:
        page = doc.pages[page_no - 1]
        ws = words(page)
        rects = [r for r in page.rects if r.get("fill")]
        in_legend: set = set()
        legend = _legend(rects, ws, in_legend)
        frames = [
            r
            for r in rects
            if not _color(r.get("non_stroking_color"))
            and r["width"] * r["height"] > 5000
            and r["width"] < page.width * 0.98
        ]
        bars = [
            r
            for r in rects
            if _color(r.get("non_stroking_color"))
            and not (
                r["width"] <= SWATCH
                and r["height"] <= SWATCH
                and _color(r.get("non_stroking_color")) in legend
            )
            and max(r["width"], r["height"]) >= 2
            and min(r["width"], r["height"]) >= 0.2
        ]
    caps = captions(ws)
    out = []
    level = [w for w in ws if re.search(r"[A-Za-z]", w[0])]
    groups = [
        g
        for g in _clusters(bars, frames)
        if sum(
            any(
                r["x0"] <= (b[0] + b[2]) / 2 <= r["x1"]
                and r["top"] <= (b[1] + b[3]) / 2 <= r["bottom"]
                for _, b in level
            )
            for r in g
        )
        <= len(g) / 2
    ]  # shaded table cells hold words; bars hold numbers
    for no, group in enumerate(groups):
        widths = {round(r["width"], 1) for r in group}
        heights = {round(r["height"], 1) for r in group}
        vertical = len(widths) <= len(heights)
        ticks = _ticks(ws, group, vertical)
        axis = _axis(ticks, vertical) if ticks else None
        if axis is None:
            continue  # no value axis: a shaded table, or a chart this reader does not know
        depth = _depth(group, frames, ws, vertical)
        box = (
            min(r["x0"] for r in group),
            min(r["top"] for r in group),
            max(r["x1"] for r in group),
            max(r["bottom"] for r in group),
        )
        above = [c for c in caps if c[1][3] <= box[1] + 1]
        title = max(above, key=lambda c: c[1][3])[0] if above else _last_caption(path, page_no)
        head = _heading(ws, group, frames, ticks)
        if head:
            title = f"{title} | {head}"
        spans = _slots(group, vertical)
        labels = _labels(
            _zone(ws, group, vertical, in_legend | {b for _, b in ticks}, depth), vertical
        )
        out_bars = []
        for r in group:
            lo = r["x0"] if vertical else r["top"]
            slot = next(i for i, s in enumerate(spans) if s[0] - 0.5 <= lo <= s[1])
            col = _color(r["non_stroking_color"]) or ""
            length = r["height"] if vertical else r["width"]
            value = pm = None
            if axis:
                value = round(abs(axis[1]) * length, 4)
                pm = round(abs(axis[1]) * PM_PT, 4)
            span = (r["x0"], r["x1"]) if vertical else (r["top"], r["bottom"])
            cat = _name(labels, spans, (span[0] + span[1]) / 2, slot)
            out_bars.append(
                Bar(
                    (r["x0"], r["top"], r["x1"], r["bottom"]),
                    col,
                    slot,
                    legend.get(col, col),
                    cat,
                    value,
                    pm,
                )
            )
        out.append(Chart(page_no, no, title, box, vertical, out_bars, ticks))
    return out


def owner(chart: Chart, b: Box) -> Bar | None:
    """The bar a printed label belongs to: the one it sits in, else the one it sits just past."""
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    inside = [
        r
        for r in chart.bars
        if r.box[0] - 0.5 <= cx <= r.box[2] + 0.5 and r.box[1] - 0.5 <= cy <= r.box[3] + 0.5
    ]
    if inside:
        return min(inside, key=lambda r: (r.box[2] - r.box[0]) * (r.box[3] - r.box[1]))
    # Excel can print a label off its bar's centre: among bar ends just short of the label and
    # within half a label of it across, the most central, then the nearest
    if chart.vertical:
        cand = [
            ((round(abs(cx - (r.box[0] + r.box[2]) / 2)), r.box[1] - b[3]), r)
            for r in chart.bars
            if -2 <= r.box[1] - b[3] < NEAR
            and abs(cx - (r.box[0] + r.box[2]) / 2) < (b[2] - b[0] + r.box[2] - r.box[0]) / 2 + 2
        ]
    else:
        cand = [
            ((round(abs(cy - (r.box[1] + r.box[3]) / 2)), b[0] - r.box[2]), r)
            for r in chart.bars
            if -2 <= b[0] - r.box[2] < NEAR
            and abs(cy - (r.box[1] + r.box[3]) / 2) < (b[3] - b[1] + r.box[3] - r.box[1]) / 2 + 2
        ]
    return min(cand, key=lambda c: c[0])[1] if cand else None
