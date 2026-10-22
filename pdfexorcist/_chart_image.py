"""Charts pasted as images: values printed in colored boxes, read by OCR engines and voted."""

import difflib
import io
import logging
import math
import re
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, NamedTuple

from ._chart_boxes import Cell, Chart, _near, excel_cells
from ._chart_legend import SAME_COLOR, series_colors
from ._chart_ocr import boxed_cells, ocr_pages, read
from ._chart_settings import MONTHS, ChartSettings
from .charts import ChartError, Word, _decimals, _number, _rows, _y_axis, has_letters, heading

logger = logging.getLogger(__name__)

MIN_PT = (100, 60)  # a smaller image is no chart
PAGE_SHARE = 0.8  # an image over more of the page is a background
COLORED = 0.002  # a chart has at least this share of saturated pixels
LAYOUT_SCALE = 2  # chart images are enlarged this much for the layout OCR
LAYOUT_WIDTH = 1800  # and at least to this width: a 120 ppi picture's month labels (Dec 2022)
OFF_LINE = "value off its line"
NO_LINE = "no line to check"
NEARER = "value nearer another point"  # its label may sit at another month or series
SERIES_OFF = "series off its line"  # most of its values are off it: its labels may be misplaced
SHIFTS = (0, 1 / 3, -1 / 3, 1 / 2, -1 / 2)  # of a category: labels set beside their points
SIDES_PX = 4.0  # the segments either side of a hidden point meet within this


class Row(NamedTuple):
    page: int
    chart: int
    title: str
    series: str
    category: str
    value: float | None
    status: str  # verified or unresolved, by the OCR vote
    votes: str
    line_value: float | None  # the series line at this category, by the y axis
    failed: str


COLUMNS = list(Row._fields)


class Plan(NamedTuple):
    chart: Chart
    words: list[Word]
    colors: dict[str, tuple]
    cats: list[tuple[float, str]]
    text: Any  # bool per pixel: the box of a word with letters (no value box there)
    cells: list[Cell]


def chart_images(doc: Any, pages: list[int], settings: ChartSettings) -> list[Chart]:
    """The pictures on the pages that can be charts: large, colored and not a background."""
    import numpy as np
    from PIL import Image

    out = []
    for no in pages:
        page = doc[no - 1]
        area, words, n = page.rect.width * page.rect.height, None, 1
        for item in page.get_images(full=True):
            try:
                box = page.get_image_bbox(item)
            except ValueError:  # an image the page does not show
                continue
            small = box.is_infinite or box.width < MIN_PT[0] or box.height < MIN_PT[1]
            if small or box.width * box.height > PAGE_SHARE * area:
                continue
            raw = Image.open(io.BytesIO(doc.extract_image(item[0])["image"])).convert("RGB")
            if (np.array(raw.convert("HSV"))[..., 1] > 80).mean() < COLORED:
                continue
            words = words or [Word(*w[:6]) for w in page.get_text("words")]
            title = heading(words, box)
            m = re.search(settings.title, title) if settings.title else None
            if not settings.title or m:
                out.append(Chart(no, n, title[m.start() :] if m else title, np.array(raw)))
                n += 1
    return out


def layout(charts: list[Chart], engines: tuple[str, ...]) -> list[list[Word]]:
    """The words of each chart picture, in its pixels, from the first engine that reads them."""
    try:
        import cv2
    except ImportError:
        raise ChartError("charts in pictures need OpenCV and an OCR engine") from None

    ks = [max(LAYOUT_SCALE, math.ceil(LAYOUT_WIDTH / c.pixels.shape[1])) for c in charts]
    grays = [
        cv2.resize(cv2.cvtColor(c.pixels, cv2.COLOR_RGB2GRAY), None, fx=k, fy=k)
        for c, k in zip(charts, ks, strict=True)
    ]
    with tempfile.TemporaryDirectory() as tmp:
        for engine in engines:
            try:
                pages = ocr_pages(engine, grays, Path(tmp))
            except Exception as e:  # noqa: BLE001 - try the next engine
                logger.info("%s did not read the chart layout: %s", engine, e)
                continue
            return [
                [
                    Word(b[0] / k, b[1] / k, b[2] / k, b[3] / k, t)
                    for b, t in boxed_cells(pages.get(i, []))
                ]
                for i, k in enumerate(ks, start=1)
            ]
    raise ChartError("charts in pictures need an OCR engine (pdfexorcist engines)")


def categories(words: list[Word], settings: ChartSettings, width: int) -> list[tuple[float, str]]:
    """(x, label) of each category; a missed label is placed by its evenly spaced neighbours."""
    import numpy as np

    names = list(settings.categories or MONTHS)
    best: list[tuple[int, float]] = []  # (label index, x)
    for row in _rows([w for w in words if _number(w.text) is None]):
        near = [(difflib.get_close_matches(w.text, names, n=1, cutoff=0.5), w) for w in row]
        hits = [(names.index(n[0]), (w.x0 + w.x1) / 2) for n, w in near if n]
        best = max(best, hits, key=len)
    if len(best) < 3:
        raise ChartError("no category labels: set [charts] categories")
    idx, xs = zip(*sorted(best), strict=True)
    slope, at0 = np.polyfit(idx, xs, 1)
    if slope <= 0:
        raise ChartError("the category labels are not left to right")
    return [(at0 + slope * i, n) for i, n in enumerate(names) if 0 <= at0 + slope * i <= width]


def _step(cats: list[tuple[float, str]]) -> float:
    """The spacing of the categories."""
    return (cats[-1][0] - cats[0][0]) / max(len(cats) - 1, 1) if cats else 0.0


def match(points: list[float], cats: list[tuple[float, str]]) -> list[str | None]:
    """The category of each x, left to right: in order, the nearest in sum.

    A point may be left out (None) at the cost of one category spacing: a stray box or token.
    """
    n, m = len(points), len(cats)
    skip = _step(cats)
    inf = float("inf")
    cost = [[inf] * (m + 1) for _ in range(n + 1)]  # i points into j categories
    move = [[""] * (m + 1) for _ in range(n + 1)]
    cost[0] = [0.0] * (m + 1)
    for i in range(1, n + 1):
        cost[i][0], move[i][0] = cost[i - 1][0] + skip, "drop"
        for j in range(1, m + 1):
            cost[i][j], move[i][j] = min(
                (cost[i][j - 1], "unused"),
                (cost[i - 1][j - 1] + abs(points[i - 1] - cats[j - 1][0]), "take"),
                (cost[i - 1][j] + skip, "drop"),
            )
    names: list[str | None] = []
    i, j = n, m
    while i:
        if move[i][j] == "unused":
            j -= 1
        else:
            names.append(cats[j - 1][1] if move[i][j] == "take" else None)
            i, j = i - 1, j - (move[i][j] == "take")
    return names[::-1]


def line_values(plan: Plan, settings: ChartSettings) -> tuple[dict, float]:
    """(series, category) -> the line's value there, by the y axis; and the axis label span."""
    import numpy as np

    if not plan.cats:
        return {}, 0.0
    left = min(x for x, _ in plan.cats) - 5
    ticks = [w for w in plan.words if _number(w.text) is not None and w.x1 < left]
    if ticks:  # the tick column: the most numbers right-aligned, not a value box left of Jan
        top = max(ticks, key=lambda w: sum(abs(o.x1 - w.x1) < 3 for o in ticks))
        ticks = [w for w in ticks if abs(w.x1 - top.x1) < 3]
    try:
        a, b = _y_axis(ticks, [])
    except (ChartError, ValueError):
        return {}, 0.0
    labels = [_number(w.text) or 0.0 for w in ticks]
    px = plan.chart.pixels.astype(int)
    covered = np.zeros(px.shape[:2], dtype=bool)
    for x0, y0, x1, y1 in (c.box for c in plan.cells):
        covered[max(0, y0 - 3) : y1 + 3, max(0, x0 - 3) : x1 + 3] = True
    # the plot spans the tick labels; a legend sample below shares the color
    mids = [w.mid for w in ticks]
    pad = (max(mids) - min(mids)) / max(len(mids) - 1, 1)
    plot = np.zeros(px.shape[0], dtype=bool)
    plot[max(0, int(min(mids) - pad)) : int(max(mids) + pad / 2)] = True
    step = _step(plan.cats)
    out = {}
    for name, rgb in plan.colors.items():
        line = _near(px, rgb, settings.color_distance) & ~covered & ~plan.text & plot[:, None]
        for x, cat in plan.cats:
            y = _line_at(line, x, step)
            if y is not None:
                out[(name, cat)] = a + b * y
    return out, max(labels) - min(labels)


def _line_at(line: Any, x: float, step: float) -> float | None:
    """The line's y at x. Where a value box hides it there, each straight segment beside x
    (to the next category, step away) is fitted where it shows and extended to x; the two
    sides must meet within SIDES_PX."""
    import numpy as np

    ys = np.nonzero(line[:, max(0, int(x) - 2) : int(x) + 3].any(axis=1))[0]
    if len(ys):
        return float(np.median(ys))
    found = []
    for cols in (range(int(x) - 3, int(x - step) + 3, -1), range(int(x) + 3, int(x + step) - 3)):
        pts = [(c, float(np.median(r))) for c in cols if 0 <= c < line.shape[1]
               if len(r := np.nonzero(line[:, c])[0])]  # fmt: skip
        if len(pts) >= 2 and abs(pts[-1][0] - pts[0][0]) >= 4:
            slope, at0 = np.polyfit([c for c, _ in pts], [y for _, y in pts], 1)
            found.append(at0 + slope * x)
    if not found or max(found) - min(found) > SIDES_PX:
        return None
    return float(np.mean(found))


def _text(words: list[Word], shape: tuple) -> Any:
    """True for each pixel under a word with letters: titles, labels and the legend."""
    import numpy as np

    mask = np.zeros(shape[:2], dtype=bool)
    for w in words:
        if has_letters(w.text):
            mask[max(0, int(w.y0)) : int(w.y1) + 1, max(0, int(w.x0)) : int(w.x1) + 1] = True
    return mask


def _no_legend(got: Plan | str | None, names: set[str]) -> bool:
    """A chart whose legend was not read, or read without a series the recipe names."""
    if isinstance(got, str):
        return got.startswith("no legend")
    return got is not None and not names <= set(got.colors)


def _shared_legend(legends: list[dict]) -> dict[str, tuple] | None:
    """The series colors that the legends of a document's charts all give, or None: fewer than
    two legends, or two that name other series or give a name another color."""
    import numpy as np

    if len(legends) < 2 or len({tuple(sorted(lg)) for lg in legends}) != 1:
        return None
    out = {}
    for name in legends[0]:
        colors = np.array([lg[name] for lg in legends], dtype=float)
        mid = np.median(colors, axis=0)
        if (np.linalg.norm(colors - mid, axis=1) > SAME_COLOR).any():
            return None
        out[name] = tuple(int(v) for v in mid)
    return out


def _plan(c: Chart, words: list[Word], settings: ChartSettings) -> Plan | str | None:
    """The chart's plan, why it cannot be read, or None for a picture that is no chart."""
    cats: list[tuple[float, str]] = []
    text = _text(words, c.pixels.shape)
    try:
        cats = categories(words, settings, c.pixels.shape[1])
    except ChartError as e:
        if settings.cells is None:  # numbers up its left side: a chart we cannot place
            axis = sum(_number(w.text) is not None for w in words if w.x1 < c.pixels.shape[1] / 4)
            return str(e) if axis >= 3 else None
    try:
        colors = series_colors(c.pixels, words, settings)
        if settings.cells is None:
            return Plan(c, words, colors, cats, text, excel_cells(c, colors, text, settings))
        from PIL import Image

        found = settings.cells(Image.fromarray(c.pixels), words, settings)
        return Plan(c, words, colors, cats, text, [Cell(*x) for x in found])
    except ChartError as e:
        return str(e)


def image_charts(
    doc: Any, pages: list[int], settings: ChartSettings
) -> tuple[list[Row], list, list[str]]:
    """Rows for the chart pictures on the pages, the charts left out, and notes for the document."""
    from .vote import TooFewReadings

    charts = chart_images(doc, pages, settings)
    if not charts:
        return [], [], []
    try:
        texts = layout(charts, settings.engines)
    except ChartError as e:
        return [], [], [str(e)]
    got_all = [_plan(c, words, settings) for c, words in zip(charts, texts, strict=True)]
    names = set(settings.names or ())
    missing = [_no_legend(g, names) for g in got_all]
    whole = [
        g.colors for g, m in zip(got_all, missing, strict=True) if isinstance(g, Plan) and not m
    ]
    shared = None if settings.series else _shared_legend(whole)
    if shared:  # a legend hidden by the month labels: the colors every other chart names
        own = replace(settings, series=shared)
        got_all = [
            _plan(c, words, own) if m else g
            for c, words, g, m in zip(charts, texts, got_all, missing, strict=True)
        ]
    plans: list[Plan] = []
    skipped: list[tuple] = []
    for c, got in zip(charts, got_all, strict=True):
        if isinstance(got, str):
            skipped.append((c.page, c.chart, got))
        elif got is not None and not got.cells:
            skipped.append((c.page, c.chart, "no value boxes: set [charts] cells to find them"))
        elif got is not None:
            plans.append(got)
    if not plans:
        return [], skipped, []
    crops = [
        [p.chart.pixels[y0:y1, x0:x1] for x0, y0, x1, y1 in (c.box for c in p.cells)] for p in plans
    ]
    try:
        voted = read(crops, settings)
    except TooFewReadings as e:
        why = f"{e} (set [engines] min_agree)"
        return [], skipped + [(p.chart.page, p.chart.chart, why) for p in plans], []
    rows: list[Row] = []
    for p, mine in zip(plans, _by_chart(voted, len(plans)), strict=True):
        try:
            rows += _rows_of(p, mine, settings)
        except ChartError as e:  # noqa: PERF203 - a chart that fails is skipped alone
            skipped.append((p.chart.page, p.chart.chart, str(e)))
    return rows, skipped, []


def _by_chart(voted: Any, n: int) -> list[dict]:
    """For each chart index: box -> its voted tokens, left to right."""
    out: list[dict] = [{} for _ in range(n)]
    ordered = voted.sort_values(["chart", "box", "token"])
    for (chart, box), g in ordered.groupby(["chart", "box"], sort=False):
        out[int(chart)][int(box)] = list(g.itertuples())
    return out


def _rows_of(p: Plan, voted: dict, settings: ChartSettings) -> list[Row]:
    """Each voted value at its category beside the line's value; a value missing is unresolved.

    Labels may sit beside their points (December 2020: a third of a month right), so each
    series' labels go to the categories by the shift in SHIFTS that puts most values on their
    line. A series still mostly off its line fails as a whole: a value of it on its line may
    be one month's label at another's point.
    """
    lines, span = line_values(p, settings)
    c, rows = p.chart, []
    step = _step(p.cats)
    for name in p.colors:
        points = sorted(  # (x, category or None, voted token), left to right
            ((cell.box[0] + r.x, cell.category, r) for b, cell in enumerate(p.cells)
             if cell.series == name for r in voted.get(b, [])),
            key=lambda t: t[0],
        )  # fmt: skip
        tries = [_placed(points, p.cats, -k * step) for k in SHIFTS]
        at = max(tries, key=lambda t: _on_line(t, lines, name, span, settings))  # first: no shift
        mine = []
        for cat in [k for _, k in p.cats] or list(at):
            line, r = lines.get((name, cat)), at.get(cat)
            if r is None and line is None:
                continue
            num = float(r.value) if r is not None and r.value else None
            status, votes = (r.status, r.votes) if r is not None else ("unresolved", "no value box")
            why = ""
            if num is not None and line is None:
                why = NO_LINE if settings.require_line else ""
            elif num is not None and line is not None:
                if not _near_line(num, r, line, span, settings):
                    why = OFF_LINE
                elif any(abs(num - o) < abs(num - line) for o in _beside(lines, p, name, cat)):
                    why = NEARER
            mine.append(Row(c.page, c.chart, c.title, name, cat, num, status, votes, line, why))
        checked = [r for r in mine if r.value is not None and r.line_value is not None]
        off_line = sum(r.failed in (OFF_LINE, NEARER) for r in checked)
        if len(checked) >= 3 and 2 * off_line > len(checked):
            mine = [
                r._replace(failed=r.failed or SERIES_OFF) if r.value is not None else r
                for r in mine
            ]
        rows += mine
    return rows


def _placed(points: list, cats: list, shift: float) -> dict:
    """category -> voted token, each label's x moved by shift before it is matched."""
    named = iter(match([x + shift for x, cat, _ in points if cat is None], cats))
    return {k: r for _, cat, r in points if (k := cat or next(named)) is not None}


def _near_line(num: float, r: Any, line: float, span: float, settings: ChartSettings) -> bool:
    """The value is within the line tolerance of its line, past its printed rounding."""
    return abs(num - line) <= settings.line_tolerance * span + _half_unit(r.value)


def _on_line(at: dict, lines: dict, name: str, span: float, settings: ChartSettings) -> int:
    """How many of a series' placed values sit on its line."""
    return sum(
        1
        for cat, r in at.items()
        if r.value
        and (name, cat) in lines
        and _near_line(float(r.value), r, lines[(name, cat)], span, settings)
    )


def _beside(lines: dict, p: Plan, name: str, cat: str) -> list[float]:
    """The line values a misplaced label may belong to: the other series at this category, and
    this series at the categories either side."""
    names = [k for _, k in p.cats]
    i = names.index(cat) if cat in names else -1
    near = [(o, cat) for o in p.colors if o != name]
    near += [(name, names[j]) for j in (i - 1, i + 1) if i >= 0 and 0 <= j < len(names)]
    return [lines[k] for k in near if k in lines]


def _half_unit(token: str) -> float:
    """Half a unit of the last printed digit: "0.03" is 0.025 to 0.035."""
    return 0.5 * 10.0 ** -_decimals(str(token))
