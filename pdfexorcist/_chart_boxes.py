import math
from typing import Any, NamedTuple

from ._chart_settings import ChartSettings

MIN_CHROMA = 6.0  # RGB distance from gray at which a pixel has a hue (JPEG noise is below)
SAME_HUE = 0.9  # cosine between chroma directions of one hue
SPLIT = (15, 19)  # larger openings that part boxes joined by a wedge of line; boxes are taller
FILLED = 0.9  # a row of a box covers this much of its width
SAME_HEIGHT = 0.3  # labels of one chart differ in height by at most this part (a marker)
TINT = 0.2  # the palest box tint, as a part of its line's chroma (Dec 2021)


class Chart(NamedTuple):
    page: int
    chart: int  # its number on the page
    title: str
    pixels: Any  # RGB numpy array


class Cell(NamedTuple):
    """Where one value (or several, left to right) is printed in a chart picture."""

    series: str
    category: str | None  # None: matched to the category labels by x
    box: tuple[int, int, int, int]  # x0, y0, x1, y1 in the picture's pixels


def excel_cells(chart: Chart, colors: dict, text: Any, settings: ChartSettings) -> list[Cell]:
    """The built-in cells: the solid blocks of each series' hue (Excel data labels).

    A box may be a pale tint of its line (December 2021: light blue-gray for a navy line), so
    pixels go to the series whose line color has their hue. When two series share a hue, or one
    is gray, blocks go by color instead, and a series whose boxes are not in its line color takes
    the commonest fill no series has.
    """
    import numpy as np

    px = chart.pixels.astype(int)
    hues = _hues(px, list(colors.values()))
    if hues is not None:
        found = {name: _blocks(hues == i, text, settings) for i, name in enumerate(colors)}
        return _with_stacked(found, text, settings)
    out = []
    for name, rgb in colors.items():
        out += _color_cells(name, px, rgb, text, settings)
    for name in [n for n in colors if all(c.series != n for c in out)]:
        taken = np.zeros(px.shape[:2], dtype=bool)
        for x0, y0, x1, y1 in (c.box for c in out):
            taken[y0:y1, x0:x1] = True
        fill = _spare_fill(px, taken | text, settings)
        if fill is not None:
            out += _color_cells(name, px, fill, text, settings)
    return out


def _color_cells(name: str, px: Any, rgb: tuple, text: Any, settings: ChartSettings) -> list[Cell]:
    """The series' cells: blocks within the color distance of rgb, kept clear of white."""
    tol = min(settings.color_distance, 0.5 * math.dist(rgb, (255, 255, 255)))
    return [Cell(name, None, b) for b in _blocks(_near(px, rgb, tol), text, settings)[0]]


def _hues(px: Any, colors: list[tuple]) -> Any | None:
    """For each pixel the index of the series color with its hue, or -1 (white, gray, black,
    or no series hue); None when a series is gray or two series share a hue."""
    import numpy as np

    dirs = np.array([np.subtract(c, np.mean(c)) for c in colors], dtype=float)
    norms = np.linalg.norm(dirs, axis=1)
    if (norms < MIN_CHROMA).any():
        return None
    dirs /= norms[:, None]
    if any(dirs[i] @ dirs[j] >= SAME_HUE for i in range(len(dirs)) for j in range(i)):
        return None
    chroma = px - px.mean(axis=2, keepdims=True)
    size = np.linalg.norm(chroma, axis=2)
    cos = (chroma @ dirs.T) / np.maximum(size, 1e-9)[..., None]
    best = cos.argmax(axis=2)
    floor = np.maximum(MIN_CHROMA, TINT * norms)[best]  # JPEG halos are paler than any tint
    sure = (size >= floor) & (cos.max(axis=2) >= SAME_HUE)
    return np.where(sure, best, -1)


def _blocks(mask: Any, text: Any, settings: ChartSettings) -> tuple[list[tuple], list[tuple]]:
    """(x0, y0, x1, y1) of each block of mask the size of a value box, clear of text, and the
    blocks left that hold no single box (see _boxes).

    The digits in a box are holes in its mask; holes a digit's size are filled, so
    boxes a few pixels apart stay apart.
    """
    import cv2
    import numpy as np

    m = cv2.morphologyEx(mask.astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    shapes, tree = cv2.findContours(m, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    digit = (settings.box_height[1] / 2) ** 2  # a hole a digit leaves; a pocket by a line is larger
    holes = [
        h
        for h, (_, _, _, parent) in zip(shapes, tree[0] if tree is not None else [], strict=False)
        if parent >= 0 and cv2.contourArea(h) <= digit
    ]
    cv2.drawContours(m, holes, -1, 255, thickness=cv2.FILLED)
    rest: list[tuple] = []
    boxes = _boxes(m, text, settings, _kernel_size(settings), rest)
    return boxes, rest


def _boxes(m: Any, text: Any, settings: ChartSettings, k: int, rest: list) -> list[tuple]:
    """The value boxes of mask m opened by a k-pixel square, each block cut apart where a line
    or a marker joins boxes. A part that is no box but larger than one (a wedge of line between
    two boxes) is opened again by the next square in SPLIT, which a box survives; what still
    is no box goes to rest as (x0, y0, part)."""
    import cv2
    import numpy as np

    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m)
    out = []
    for i, (x, y, w, h, _) in enumerate(stats[1:n], start=1):
        for c0, r0, c1, r1 in _cut(labels[y : y + h, x : x + w] == i, settings.box_height[0]):
            x0, y0, x1, y1 = int(x + c0), int(y + r0), int(x + c1), int(y + r1)
            part = labels[y0:y1, x0:x1] == i
            if _box_like(part, settings):
                if not text[y0:y1, x0:x1].any():
                    out.append((x0, y0, x1, y1))
            elif (bigger := next((s for s in SPLIT if s > k), None)) and min(part.shape) > bigger:
                sub = np.zeros_like(m)
                sub[y0:y1, x0:x1] = part * 255
                out += _boxes(sub, text, settings, bigger, rest)
            elif min(part.shape) >= settings.box_height[0]:
                rest.append((x0, y0, part))
    return out


def _with_stacked(found: dict, text: Any, settings: ChartSettings) -> list[Cell]:
    """Each series' boxes, and the boxes of its blocks of boxes that touch corner to corner,
    found by the height its chart's labels share."""
    import numpy as np

    heights = [b[3] - b[1] for boxes, _ in found.values() for b in boxes]
    out = [Cell(name, None, b) for name, (boxes, _) in found.items() for b in boxes]
    if not heights:
        return out
    tall = float(np.median(heights))
    for name, (_, rest) in found.items():
        for x0, y0, part in rest:
            for a, b, c, d in _stacked(part, settings, tall):
                if not text[y0 + b : y0 + d, x0 + a : x0 + c].any():
                    out.append(Cell(name, None, (x0 + a, y0 + b, x0 + c, y0 + d)))
    return out


def _stacked(part: Any, settings: ChartSettings, tall: float) -> list[tuple[int, int, int, int]]:
    """(x0, y0, x1, y1) of the boxes in a block of boxes that touch corner to corner along
    their line (December 2020), which no straight cut parts. Each run of a row, grown up and
    down over the rows that fill it, is a box where it grows to about tall, the height of the
    chart's other labels; of boxes that overlap, the widest is kept."""
    found = []
    for r in range(part.shape[0]):
        for c0, c1 in _runs(part[r]):
            r0, r1 = r, r + 1
            while r0 > 0 and part[r0 - 1, c0:c1].mean() >= FILLED:
                r0 -= 1
            while r1 < part.shape[0] and part[r1, c0:c1].mean() >= FILLED:
                r1 += 1
            if abs((r1 - r0) - tall) <= SAME_HEIGHT * tall and _box_like(
                part[r0:r1, c0:c1], settings
            ):
                found.append((c0, r0, c1, r1))
    out: list[tuple[int, int, int, int]] = []
    for box in sorted(set(found), key=lambda b: b[0] - b[2]):  # widest first
        if not any(_overlap(box, o) for o in out):
            out.append(box)
    return out


def _overlap(a: tuple, b: tuple) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _box_like(part: Any, settings: ChartSettings) -> bool:
    """A value box's size and fill; a box of one digit is taller than wide."""
    low, high = settings.box_height
    h, w = part.shape
    return low <= h <= high and w >= 0.6 * h and part.mean() > 0.6


def _cut(block: Any, low: int) -> list[tuple[int, int, int, int]]:
    """(x0, y0, x1, y1) of the parts of block left by cutting, in turn, at columns shorter than
    a box and at rows narrower than one, until no cut is left: boxes joined by a line or a
    marker (December 2021 and 2022 labels sit on their line)."""
    import numpy as np

    rows = np.flatnonzero(block.any(axis=1))
    cols = np.flatnonzero(block.any(axis=0))
    if not len(rows):
        return []
    r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    block = block[r0:r1, c0:c1]
    for axis in (0, 1):
        runs = _runs(block.sum(axis=axis) >= low)
        whole = runs == [(0, block.shape[1 - axis])]
        if not whole:
            out = []
            for a, b in runs:
                part = block[:, a:b] if axis == 0 else block[a:b]
                dx, dy = (a, 0) if axis == 0 else (0, a)
                out += [
                    (c0 + dx + x0, r0 + dy + y0, c0 + dx + x1, r0 + dy + y1)
                    for x0, y0, x1, y1 in _cut(part, low)
                ]
            return out
    return [(c0, r0, c1, r1)]


def _runs(flags: Any, gap: int = 2) -> list[tuple[int, int]]:
    """(start, end) of each run of True in flags, across gaps of up to gap."""
    import numpy as np

    out: list[tuple[int, int]] = []
    for i in np.flatnonzero(flags):
        if out and i - out[-1][1] <= gap:
            out[-1] = (out[-1][0], int(i) + 1)
        else:
            out.append((int(i), int(i) + 1))
    return out


def _near(px: Any, rgb: tuple, tol: float) -> Any:
    """True for each pixel within tol of the color rgb."""
    import numpy as np

    return np.linalg.norm(px - np.array(rgb), axis=2) < tol


def _kernel_size(settings: ChartSettings) -> int:
    """The side of an opening that removes lines and markers and keeps value boxes."""
    return max(3, min(11, settings.box_height[0] - 1))


def _spare_fill(px: Any, taken: Any, settings: ChartSettings) -> tuple | None:
    """The commonest color of solid, non-white blocks outside taken, or None."""
    from collections import Counter

    import cv2
    import numpy as np

    ink = (255 - px).max(axis=2) > 25  # not white
    k = _kernel_size(settings)
    solid = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_OPEN, np.ones((k, k), np.uint8)) > 0
    solid &= ~taken
    if solid.sum() < settings.box_height[0] ** 2 * 4:
        return None
    (color, _), *_ = Counter(map(tuple, (px[solid] // 16).tolist())).most_common(1)
    return tuple(int(v) * 16 + 8 for v in color)
