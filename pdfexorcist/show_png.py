"""Annotated PNG view."""

from pathlib import Path
from typing import Any

from ._show_layout import _font
from .show import PageView

# Okabe-Ito: distinguishable with the common colour-vision deficiencies
COLOURS = {
    "agreed": (0, 158, 115),
    "unresolved": (230, 159, 0),
    "failed": (213, 94, 0),
    "skipped": (130, 130, 130),
    "unnamed": (213, 94, 0),
}
LABELS = {
    "agreed": "agreed",
    "unresolved": "unresolved (engines disagree)",
    "failed": "agreed, fails a check",
    "skipped": "text not read as a cell",
}


def _dashed(
    draw: Any, box: list[float], colour: tuple[int, ...], width: int, dash: int = 6
) -> None:
    x0, y0, x1, y1 = box
    for a, b, horizontal, at in (
        (x0, x1, True, y0),
        (x0, x1, True, y1),
        (y0, y1, False, x0),
        (y0, y1, False, x1),
    ):
        p = a
        while p < b:
            q = min(p + dash, b)
            seg = (p, at, q, at) if horizontal else (at, p, at, q)
            draw.line(seg, fill=colour, width=width)
            p += 2 * dash


def _hatch(draw: Any, box: list[float], colour: tuple[int, ...], step: int = 6) -> None:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    d = -h
    while d < w:
        # a 45-degree line clipped to the box
        ax, ay = x0 + max(d, 0), y1 - max(-d, 0)
        bx, by = x0 + min(d + h, w), y1 - min(h, w - d)
        if bx > ax:
            draw.line((ax, ay, bx, by), fill=colour, width=1)
        d += step


def _status(
    d: Any,
    box: list[float],
    status: str,
    line: tuple[int, ...],
    widths: tuple[int, int, int],
    fill: tuple[int, ...] | None = None,
    fill_unresolved: tuple[int, ...] | None = None,
    hatch: tuple[int, ...] | None = None,
    dash: int = 4,
    step: int = 5,
    dot: int = 0,
) -> None:
    """Draw a cell box in its status style."""
    if status == "agreed":
        d.rectangle(box, fill=fill, outline=line, width=widths[0])
    elif status == "unresolved":
        d.rectangle(box, fill=fill_unresolved)
        _dashed(d, box, line, widths[1], dash=dash)
        if dot:
            cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
            d.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=line)
    elif status == "failed":
        d.rectangle(box, fill=fill, outline=line, width=widths[2])
        _hatch(d, box, hatch or line, step=step)
    else:
        d.rectangle(box, outline=line, width=1)


def draw_cells(img: Any, view: PageView) -> Any:
    """Draw cell boxes over an RGB image."""
    from PIL import Image, ImageDraw

    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    lw = max(1, round(img.width / 1200))
    for w in view.ignored:
        _status(d, w["box"], "skipped", COLOURS["skipped"] + (200,), (1, 1, 1))
    for c in view.cells:
        if not c["box"]:
            continue
        col = COLOURS[c["status"]]
        _status(
            d,
            c["box"],
            c["status"],
            (*col, 255),
            (lw, 2 * lw, 2 * lw),
            fill=(*col, 40),
            fill_unresolved=(*col, 70),
            hatch=(*col, 220),
            dash=max(3, round(4 * lw)),
            step=max(4, 3 * lw),
            dot=lw,
        )
    return Image.alpha_composite(img.convert("RGBA"), over).convert("RGB")


def render(view: PageView) -> Any:
    """Render an annotated page with labels and legend."""
    from PIL import Image, ImageDraw

    page = draw_cells(view.image, view)
    fs = max(12, round(page.width / 90))
    font, small = _font(fs), _font(max(10, round(fs * 0.85)))
    meas = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    def width(text: str, f: Any = font) -> float:
        return meas.textlength(text, font=f)

    row_texts = [_clip(r["label"], 40) for r in view.rows]
    left = int(min(max([width(t, small) for t in row_texts] + [0]) + 2 * fs, page.width * 0.45))
    col_texts = [_clip(c["label"], 32) for c in view.cols]
    head = int(max([width(t, small) for t in col_texts] + [0]) * 0.75 + 2 * fs)
    legend_h = int(3.2 * fs)
    top = legend_h + head
    canvas = Image.new("RGB", (page.width + left + fs, page.height + top + fs), "white")
    canvas.paste(page, (left, top))
    d = ImageDraw.Draw(canvas)

    counts = view.counts()
    x = fs
    title = f"{Path(view.source).name}  page {view.page}  ({len(view.methods)} engines)"
    d.text((fs, fs * 0.4), title, fill=(0, 0, 0), font=font)
    y = int(fs * 1.7)
    for s in ("agreed", "unresolved", "failed", "skipped"):
        col = COLOURS[s]
        _status(
            d,
            [x, y, x + 2 * fs, y + fs],
            s,
            col,
            (2, 2, 3),
            fill=_tint(col),
            fill_unresolved=_tint(col, 0.6),
        )
        text = f"{LABELS[s]}: {counts[s]}"
        d.text((x + 2.5 * fs, y - fs * 0.1), text, fill=(0, 0, 0), font=small)
        x += int(2.5 * fs + width(text, small) + 2 * fs)

    for c, text in zip(view.cols, col_texts, strict=True):
        tw = int(width(text, small)) + 4
        lab = Image.new("RGBA", (tw, int(fs * 1.4)), (255, 255, 255, 0))
        ImageDraw.Draw(lab).text(
            (2, 0),
            text,
            fill=(0, 0, 0) if c["named"] else COLOURS["unnamed"],
            font=small,
        )
        rot = lab.rotate(50, expand=True)
        cx = left + c["x"]
        canvas.paste(rot, (int(cx - rot.width * 0.15), int(top - rot.height - 2)), rot)
        d.line((cx, top - 3, cx, top), fill=(0, 0, 0), width=1)
    for r, text in zip(view.rows, row_texts, strict=True):
        rw = width(text, small)
        cy = top + r["y"]
        d.text((left - rw - fs * 0.6, cy - fs * 0.5), text, fill=(0, 0, 0), font=small)
        d.line((left - fs * 0.4, cy, left, cy), fill=(0, 0, 0), width=1)
    return canvas


def _tint(col: tuple[int, ...], a: float = 0.25) -> tuple[int, int, int]:
    return tuple(round(255 - (255 - v) * a) for v in col)  # type: ignore[return-value]


def _clip(text: str | None, n: int) -> str:
    text = str(text or "")
    return text if len(text) <= n else text[: n - 1] + "…"


def write_png(view: PageView, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    render(view).save(path, optimize=True)
    return path
