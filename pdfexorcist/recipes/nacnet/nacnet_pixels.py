"""Bar and pie charts pasted as pictures (the 2022 and 2023 reports): the same slots as
nacnet_bars, from the pixels.

Bars are connected regions of one colour; Excel's dark outline keeps neighbouring segments apart.
Axis and legend words come from OCR: Apple Vision, then what it missed from docTR and tesseract.

ponytail: one picture per page, upright; line charts in pictures are not read.
"""

import logging
import math
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

import nacnet_bars as nb

from pdfexorcist.cells import Box, token_boxes
from pdfexorcist.extractors import EXTRACTORS

logger = logging.getLogger(__name__)

PLACE_ENGINES = ("ocrmac", "doctr", "tesseract")
DARK = 90  # a channel maximum below this is outline or text


class Picture(NamedTuple):
    rgb: Any  # numpy array, rows x cols x 3
    rect: Box  # where it sits on the page, in points


REGION_PPI = 250  # pixel rules (outline width, the 5-pixel opening) are tuned at this resolution


def picture(path: str, page_no: int, max_ppi: float = REGION_PPI) -> Picture | None:
    """The largest picture on the page, at its own resolution or max_ppi if lower."""
    import numpy as np
    import pymupdf
    from PIL import Image

    with pymupdf.open(path) as doc:
        page = doc[page_no - 1]
        best = None
        for info in page.get_images(full=True):
            for r in page.get_image_rects(info[0]):
                if best is None or r.width * r.height > best[1].width * best[1].height:
                    best = (info[0], r)
        if (
            best is None
            or best[1].width * best[1].height < 0.1 * page.rect.width * page.rect.height
        ):
            return None
        r = best[1]
        width = pymupdf.Pixmap(doc, best[0]).width
        # render the page there at the picture's own resolution: its soft mask is applied on white
        dpi = min(72 * width / r.width, max_ppi)
        pix = page.get_pixmap(clip=r, dpi=round(dpi), alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    return Picture(np.asarray(img).astype(int), (r.x0, r.y0, r.x1, r.y1))


@lru_cache(maxsize=8)
def place_words(path: str, page_no: int) -> list[tuple[str, Box]]:
    """Words of the page's picture, in page points: OCR of the picture alone (at twice its own
    resolution when under 300 ppi), the first engine's words, then words it missed."""
    from PIL import Image

    pic = picture(path, page_no, max_ppi=600)
    if pic is None:
        return []
    img = Image.fromarray(pic.rgb.astype("uint8"))
    ppi = 72 * img.width / (pic.rect[2] - pic.rect[0])
    if ppi < 300:  # small print: read it at twice the size
        img = img.resize((img.width * 2, img.height * 2), Image.Resampling.LANCZOS)
        ppi *= 2
    with tempfile.TemporaryDirectory() as tmp:
        one = Path(tmp) / "picture.pdf"
        img.save(one, resolution=ppi)  # the picture's printed size
        # the engines give points of the saved page (img pixels * 72 / ppi)
        sx = (pic.rect[2] - pic.rect[0]) / (img.width * 72 / ppi)
        sy = (pic.rect[3] - pic.rect[1]) / (img.height * 72 / ppi)
        out: list[tuple[str, Box]] = []
        for name in PLACE_ENGINES:  # each engine fills in words the ones before missed
            try:
                pages = list(EXTRACTORS[name](one))
            except (ImportError, OSError, RuntimeError) as e:
                logger.warning("placing words: %s not run (%s)", name, e)
                continue
            mine = [
                (
                    t,
                    (
                        pic.rect[0] + tb[0] * sx,
                        pic.rect[1] + tb[1] * sy,
                        pic.rect[0] + tb[2] * sx,
                        pic.rect[1] + tb[3] * sy,
                    ),
                )
                for _, lines in pages
                for line in lines
                for _, t, tb in token_boxes(line)
                if tb is not None
            ]
            out += [w for w in mine if not any(_overlap(w[1], o[1]) for o in out)]
    return out


def _overlap(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def picture_pdf(src: str, out: str, scale: int = 2) -> list[int]:
    """A PDF of the chart pictures alone, one per page, at the size they print but `scale` times
    their own resolution, so OCR engines read the small print from the picture itself. Returns
    the source page of each page."""
    import pymupdf

    pages = []
    with pymupdf.open(src) as doc, pymupdf.open() as new:
        for page in doc:
            pic = picture(src, page.number + 1)
            if pic is None:
                continue
            r = pymupdf.Rect(pic.rect)
            dpi = scale * round(72 * pic.rgb.shape[1] / r.width)
            pix = page.get_pixmap(clip=r, dpi=dpi, alpha=False)
            p = new.new_page(width=r.width, height=r.height)
            p.insert_image(p.rect, pixmap=pix)
            pages.append(page.number + 1)
        new.save(out)
    return pages


def _regions(rgb: Any) -> list[dict]:
    """Rectangles of one colour: (x0, top, x1, bottom) in pixels and the colour, for regions that
    fill their box. Regions touching the picture's edge are background."""
    import numpy as np
    from scipy import ndimage

    dark = rgb.max(axis=2) < DARK
    wide_dark = ndimage.binary_opening(
        dark, structure=np.ones((5, 5))
    )  # black fills, not lines or text
    key = (rgb // 32).astype(int)
    code = key[..., 0] * 64 + key[..., 1] * 8 + key[..., 2]
    code[dark & ~wide_dark] = -1
    out = []
    for value in np.unique(code):
        if value < 0:
            continue
        labels, _ = ndimage.label(code == value)
        for i, sl in enumerate(ndimage.find_objects(labels), start=1):
            if sl is None:
                continue
            h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
            if w < 4 or h < 2:
                continue
            if (
                sl[0].start == 0
                or sl[1].start == 0
                or sl[0].stop == rgb.shape[0]
                or sl[1].stop == rgb.shape[1]
            ):
                continue
            area = (labels[sl] == i).sum()
            if area < 0.9 * w * h:
                continue
            col = rgb[sl][labels[sl] == i].mean(axis=0) / 255
            out.append(
                {"px": (sl[1].start, sl[0].start, sl[1].stop, sl[0].stop), "rgb": tuple(col)}
            )

    # a frame (the white plot area inside the chart's border) holds other regions: not a bar
    def holds(a: dict, b: dict) -> bool:
        return (
            a is not b
            and a["px"][0] <= b["px"][0]
            and a["px"][1] <= b["px"][1]
            and b["px"][2] <= a["px"][2]
            and b["px"][3] <= a["px"][3]
        )

    return [a for a in out if not any(holds(a, b) for b in out)]


def _to_page(pic: Picture, px: tuple) -> Box:
    h, w = pic.rgb.shape[:2]
    sx, sy = (pic.rect[2] - pic.rect[0]) / w, (pic.rect[3] - pic.rect[1]) / h
    # the outline is drawn round each region: grow it by one pixel, as the vector bar includes it
    return (
        pic.rect[0] + (px[0] - 1) * sx,
        pic.rect[1] + (px[1] - 1) * sy,
        pic.rect[0] + (px[2] + 1) * sx,
        pic.rect[1] + (px[3] + 1) * sy,
    )


def _hex(c: tuple) -> str:
    return "#" + "".join(f"{round(v * 255):02x}" for v in c)


@lru_cache(maxsize=8)
def page_charts(path: str, page_no: int) -> list[nb.Chart]:
    """The bar charts in the page's picture, as nacnet_bars builds them from a drawing."""
    pic = picture(path, page_no)
    if pic is None:
        return []
    ws = place_words(path, page_no)
    regions = _regions(pic.rgb)
    rects = []
    for r in regions:
        x0, top, x1, bottom = _to_page(pic, r["px"])
        rects.append(
            {
                "x0": x0,
                "top": top,
                "x1": x1,
                "bottom": bottom,
                "width": x1 - x0,
                "height": bottom - top,
                "color": _hex(r["rgb"]),
                "white": min(r["rgb"]) > 0.92,
                "pw": r["px"][2] - r["px"][0],
            }
        )
    text_h = sorted(b[3] - b[1] for _, b in ws)[len(ws) // 2] if ws else 8.0
    # a legend sample: a small square with a word just right of it on its line
    swatches = [
        r
        for r in rects
        if r["width"] <= 1.6 * text_h
        and r["height"] <= 1.6 * text_h
        and abs(r["width"] - r["height"]) < 0.4 * text_h
        and any(
            0 <= b[0] - r["x1"] < 12
            and abs((b[1] + b[3]) / 2 - (r["top"] + r["bottom"]) / 2) < text_h
            and any(ch.isalpha() for ch in t)
            for t, b in ws
        )
    ]
    used: set = set()
    legend = _legend(swatches, ws, used)
    rest = [r for r in rects if r not in swatches and not any(_holds_word(r, b) for _, b in ws)]
    coloured = [r["pw"] for r in rest if not r["white"] and r["pw"] >= 5]
    if not coloured:
        return []
    mode = max(set(coloured), key=lambda w: sum(abs(c - w) <= 1 for c in coloured))
    # ponytail: vertical bars only; they share one width in pixels, give or take one (a white
    # segment too: "others")
    bars = [r for r in rest if abs(r["pw"] - mode) <= max(2, 0.15 * mode)]
    px_pt = (pic.rect[2] - pic.rect[0]) / pic.rgb.shape[
        1
    ]  # points per pixel; pm: 3 pixels of outline
    out = []
    for no, group in enumerate(nb._clusters(bars, [])):
        if len(group) < 3:
            continue
        widths = {round(r["width"], 0) for r in group}
        heights = {round(r["height"], 0) for r in group}
        vertical = len(widths) <= len(heights)
        ticks = nb._ticks(ws, group, vertical)
        axis = nb._axis(ticks, vertical) if ticks else None
        if axis is None:
            continue  # no value axis read: text, or a picture this reader does not know
        box = (
            min(r["x0"] for r in group),
            min(r["top"] for r in group),
            max(r["x1"] for r in group),
            max(r["bottom"] for r in group),
        )
        spans = nb._slots(group, vertical)
        depth = nb._depth(group, [], ws, vertical)
        labels = nb._labels(
            nb._zone(ws, group, vertical, used | {b for _, b in ticks}, depth), vertical
        )
        bars_out = []
        for r in group:
            lo = r["x0"] if vertical else r["top"]
            slot = next(i for i, s in enumerate(spans) if s[0] - 0.5 <= lo <= s[1])
            length = r["height"] if vertical else r["width"]
            span = (r["x0"], r["x1"]) if vertical else (r["top"], r["bottom"])
            series = legend.get(_nearest(r["color"], legend), r["color"])
            bars_out.append(
                nb.Bar(
                    (r["x0"], r["top"], r["x1"], r["bottom"]),
                    r["color"],
                    slot,
                    series,
                    nb._name(labels, spans, (span[0] + span[1]) / 2, slot),
                    round(abs(axis[1]) * length, 4),
                    round(abs(axis[1]) * 3 * px_pt, 4),
                )
            )
        heading = " ".join(
            t
            for line in nb._lines([w for w in ws if w[1][3] <= box[1] and w[1][1] >= pic.rect[1]])[
                :2
            ]
            for t, _ in line
        )
        caption = _caption(path, page_no, pic.rect)
        title = f"{caption} | {heading}" if caption and heading else caption or heading
        out.append(nb.Chart(page_no, no, title, box, vertical, bars_out, ticks))
    return out


def _caption(path: str, page_no: int, rect: Box) -> str:
    """The figure caption in the text layer: the nearest above the picture, else below it (the
    2022 and 2023 reports print it under), else the last on the pages before."""
    import pdfplumber

    with pdfplumber.open(path) as doc:
        caps = nb.captions(nb.words(doc.pages[page_no - 1]))
    above = [c for c in caps if c[1][3] <= rect[1] + 2]
    below = [c for c in caps if c[1][1] >= rect[3] - 2]
    if above:
        return max(above, key=lambda c: c[1][3])[0]
    if below:
        return min(below, key=lambda c: c[1][1])[0]
    return nb._last_caption(path, page_no)


def _holds_word(r: dict, b: Box) -> bool:
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return (
        r["x0"] <= cx <= r["x1"]
        and r["top"] <= cy <= r["bottom"]
        and (b[2] - b[0]) > 0.8 * r["width"]
        and r["height"] < 2 * (b[3] - b[1])
    )  # a label box (a word framed in white), not a bar


def _legend(swatches: list[dict], ws: list[tuple[str, Box]], used: set) -> dict[str, str]:
    out: dict[str, str] = {}
    for s in swatches:
        mid = (s["top"] + s["bottom"]) / 2
        right = sorted(
            (
                w
                for w in ws
                if abs((w[1][1] + w[1][3]) / 2 - mid) < 0.8 * (s["bottom"] - s["top"]) + 2
                and 0 <= w[1][0] - s["x1"] < 12
                and any(ch.isalpha() for ch in w[0])
            ),
            key=lambda w: w[1][0],
        )
        if right:
            used.add(right[0][1])
            out.setdefault(s["color"], right[0][0])
    return out


def _nearest(color: str, legend: dict[str, str], tol: float = 60.0) -> str:
    """The legend colour nearest to a region's colour (antialiasing shifts it a little)."""

    def rgb(h: str) -> tuple[int, int, int]:
        return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)

    if not legend:
        return color
    best = min(legend, key=lambda k: math.dist(rgb(k), rgb(color)))
    return best if math.dist(rgb(best), rgb(color)) < tol else color
