"""The legend of a chart picture: each series name with the color of its line sample."""

import difflib
import math
from typing import Any

from ._chart_settings import MONTHS, ChartSettings
from .charts import ChartError, Word, _rows, has_letters

SAME_COLOR = 60  # RGB distance within which two legends give one color


def series_colors(pixels: Any, words: list[Word], settings: ChartSettings) -> dict[str, tuple]:
    """Series name -> RGB: the settings', else each legend line sample and the words after it."""
    if settings.series:
        return dict(settings.series)
    found: dict[str, tuple] = {}
    labels = settings.categories or MONTHS
    for row in _rows([w for w in words if has_letters(w.text)]):
        line = sorted(o for o in words if abs(o.mid - row[0].mid) < 4)
        if sum(difflib.get_close_matches(o.text, labels, n=1, cutoff=0.7) != [] for o in line) > 1:
            continue  # the category labels, beside the plotted lines
        runs = _runs(pixels, min(o.y0 for o in line), max(o.y1 for o in line))
        parts = [part for o in line for part in _split(o, [r[0] for r in runs])]
        for k, (x0, _, rgb) in enumerate(runs):  # OCR can read a sample as part of its name
            stop = runs[k + 1][0] if k + 1 < len(runs) else 1e9
            name = _name(
                " ".join(o.text for o in parts if x0 <= (o.x0 + o.x1) / 2 < stop), settings
            )
            if settings.names and name not in settings.names:
                continue  # the recipe names the legend: other text with a color is not a series
            same = next((n for n, c in found.items() if math.dist(c, rgb) < SAME_COLOR), None)
            if has_letters(name) and (same is None or len(name) > len(same)):
                if same:
                    del found[same]
                found[name] = rgb
    if not found:
        raise ChartError("no legend: set [charts] series to name each color")
    return found


def _name(text: str, settings: ChartSettings) -> str:
    """A legend name as read, or the nearest of the settings' names ("TPCAverage 3 years")."""
    text = text.strip(" •·-–—|")
    if not settings.names:
        return text
    near = difflib.get_close_matches(text, settings.names, n=1, cutoff=0.6)
    return near[0] if near else text


def _split(w: Word, cuts: list[int]) -> list[Word]:
    """w cut at the space nearest each x in cuts that falls inside it (OCR joins legend names)."""
    inside = [x for x in cuts if w.x0 + 4 < x < w.x1 - 4]
    if not inside:
        return [w]
    per = (w.x1 - w.x0) / max(len(w.text), 1)
    x = inside[0]
    spaces = [i for i, ch in enumerate(w.text) if ch == " "]
    if not spaces:
        return [w]
    i = min(spaces, key=lambda i: abs(w.x0 + i * per - x))
    left = w._replace(x1=w.x0 + i * per, text=w.text[:i])
    right = w._replace(x0=w.x0 + (i + 1) * per, text=w.text[i + 1 :])
    return [left, *_split(right, inside[1:])]


def _runs(px: Any, y0: float, y1: float) -> list[tuple[int, int, tuple]]:
    """(x0, x1, RGB) of each horizontal run of saturated color in the rows y0 to y1."""
    import cv2
    import numpy as np

    band = px[max(0, int(y0)) : int(y1) + 1]
    s = cv2.cvtColor(band.astype(np.uint8), cv2.COLOR_RGB2HSV)[..., 1]
    sat = s > 40  # finds the run; gray text is below
    cols = np.flatnonzero(sat.any(axis=0))
    if not len(cols):
        return []
    runs, start = [], None
    for a, b in zip(cols, [*cols[1:], 10**9], strict=True):
        start = a if start is None else start
        if b - a > 3:
            run = s[:, start : a + 1]
            thin = np.median(sat[:, start : a + 1].sum(axis=0)) <= max(3, 0.6 * len(band))
            if a - start >= 15 and thin and np.percentile(run[run > 40], 75) > 80:
                strong = run >= np.percentile(run[run > 40], 75)  # the strongest pixels: its color
                part = band[:, start : a + 1][strong]
                runs.append((int(start), int(a), tuple(int(v) for v in np.median(part, axis=0))))
            start = None
    return runs
