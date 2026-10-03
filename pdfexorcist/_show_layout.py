"""Row, column and word layout for the show views."""

import math
import statistics
from collections.abc import Sequence
from typing import Any

from ._show_frames import _centre
from .cells import Box


def _plain(v: Any) -> Any:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, (int, float, str, bool)):
        return v
    try:
        return v.item()  # numpy scalars
    except AttributeError:
        return str(v)


def _rounded(b: Box | None) -> list[float] | None:
    return None if b is None else [round(float(v), 1) for v in b]


def _field(key: Sequence[str], columns: str) -> str:
    """The field that tells columns apart on the page: 'col' when the key has it."""
    return "col" if "col" in key else columns


def _cols(cells: list[dict[str, Any]], key: Sequence[str], columns: str) -> list[dict[str, Any]]:
    field_ = _field(key, columns)
    groups: dict[Any, list[dict[str, Any]]] = {}
    for c in cells:
        v = c["key"].get(field_, c["extra"].get(field_))
        if v is not None and c["box"]:
            groups.setdefault(v, []).append(c)
    out = []
    for v, cs in groups.items():
        name = None
        if columns != field_:
            names = [c["key"].get(columns, c["extra"].get(columns)) for c in cs]
            names = [n for n in names if n not in (None, "")]
            name = max(set(names), key=names.count) if names else None
        num = f"col {v}" if field_ == "col" else f"{v}"
        label = num if columns == field_ else f"{v}: {name or '?'}"
        out.append(
            {
                "label": label,
                "x": round(statistics.median(_centre(c["box"])[0] for c in cs), 1),
                "named": columns == field_ or name is not None,
            }
        )
    return sorted(out, key=lambda c: c["x"])


def _rows(
    cells: list[dict[str, Any]],
    key: Sequence[str],
    columns: str,
    rows: Sequence[str] | None,
) -> list[dict[str, Any]]:
    fields = (
        list(rows) if rows else [k for k in key if k not in (_field(key, columns), columns, "page")]
    )
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for c in cells:
        if c["box"]:
            rk = tuple(c["key"].get(f, c["extra"].get(f)) for f in fields)
            groups.setdefault(rk, []).append(c)
    out = []
    for rk, cs in groups.items():
        label = next((c["extra"].get("label") for c in cs if c["extra"].get("label")), None)
        text = label or " · ".join(str(v) for v in rk if v not in (None, ""))
        out.append(
            {
                "label": text,
                "y": round(statistics.median(_centre(c["box"])[1] for c in cs), 1),
            }
        )
    return sorted(out, key=lambda r: r["y"])


def _font(size: int) -> Any:
    """Pillow's default font at size (a fixed-size bitmap font before Pillow 10.1)."""
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _type_unplaced(img: Any, words: list[tuple[str, Box]]) -> int:
    """Type words outside the rendered image."""
    from PIL import Image, ImageDraw

    grey = img.convert("L")
    draw = ImageDraw.Draw(img)
    n = 0
    for t, b in words:
        x0, y0, x1, y1 = (round(v) for v in b)
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, img.width), min(y1, img.height)
        if x1 - x0 < 2 or y1 - y0 < 2:
            continue
        if grey.crop((x0, y0, x1, y1)).getextrema()[0] < 200:  # something is drawn there
            continue
        upright = (y1 - y0) > 1.5 * (x1 - x0) and len(t) > 1  # a rotated header word
        size = max(6, int((x1 - x0 if upright else y1 - y0) * 0.8))
        font = _font(size)
        if upright:
            lab = Image.new(
                "RGBA", (int(draw.textlength(t, font=font)) + 2, size + 4), (0, 0, 0, 0)
            )
            ImageDraw.Draw(lab).text((0, 0), t, fill=(110, 110, 110), font=font)
            lab = lab.rotate(90, expand=True)
            img.paste(lab, (x0, max(y0, y1 - lab.height)), lab)
        else:
            draw.text((x0, y0), t, fill=(110, 110, 110), font=font)
        n += 1
    return n


def _ignored(words: list[tuple[str, Box]], cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The reference engine's words whose centre is in no cell's box."""
    boxes = [c["box"] for c in cells if c["box"]]
    out = []
    for t, b in words:
        x, y = _centre(b)
        if not any(a[0] <= x <= a[2] and a[1] <= y <= a[3] for a in boxes):
            out.append({"text": t, "box": _rounded(b)})
    return out
