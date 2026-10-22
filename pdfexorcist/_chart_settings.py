"""The [charts] section of a recipe: how pdfexorcist charts reads one kind of chart."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._recipe_error import RecipeError
from ._usercode import load_function

KINDS = ("auto", "vector", "image")
CROPS = ("color", "binary")  # color suits Apple Vision, binary (Otsu) suits tesseract
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
OCR_ENGINES = ("ocrmac", "tesseract", "indra")  # the installed ones vote, unless [engines] use

_T = ((str,), 'text in quotes, like "abc"')
SCHEMA: dict[str, tuple[tuple, str]] = {
    "kind": _T,
    "title": _T,
    "categories": ((list,), 'a list of labels, like ["Jan", "Feb"]'),
    "series": ((dict,), 'a table of colors, like { "Current Year" = "#ffc000" }'),
    "names": ((list,), 'a list of series names, like ["Current Year", "Average 3 years"]'),
    "crop": ((dict,), 'a table, like { tesseract = "binary", ocrmac = "color" }'),
    "color_distance": ((int, float), "a number, like 70"),
    "box_height": ((list,), "two pixel sizes, like [12, 60]"),
    "line_tolerance": ((int, float), "a number, like 0.05"),
    "require_line": ((bool,), "true or false"),
    "cells": _T,
}


@dataclass(frozen=True)
class ChartSettings:
    """How to read one kind of chart. The defaults read Excel line charts."""

    kind: str = "auto"  # vector: drawn paths; image: pasted pictures, read by OCR
    title: str | None = None  # regular expression; only charts whose title matches are read
    categories: tuple[str, ...] | None = None  # x labels, left to right; default: the months
    series: dict[str, tuple[int, int, int]] | None = None  # name -> RGB; default: the legend
    names: tuple[str, ...] | None = None  # the legend's names; an OCR reading snaps to the nearest
    engines: tuple[str, ...] = OCR_ENGINES  # from [engines] use
    min_agree: int | None = None  # from [engines]; default: as for extract
    families: dict[str, list[str]] | None = None  # from [engines]
    crop: dict[str, str] = field(default_factory=lambda: {"tesseract": "binary"})  # else color
    color_distance: float = 70.0  # RGB distance of a pixel from its series color
    box_height: tuple[int, int] = (12, 60)  # pixel heights of a value box
    line_tolerance: float = 0.05  # largest value-to-line difference, as a part of the axis
    require_line: bool = False  # a value with no line to check it against fails a check
    cells: Callable | None = None  # user function: where the values are (_chart_image.Cell)


def hex_rgb(text: str) -> tuple[int, int, int] | None:
    """(r, g, b) of "#rrggbb", or None."""
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", text.strip())
    return tuple(int(m.group(1)[i : i + 2], 16) for i in (0, 2, 4)) if m else None  # type: ignore[return-value]


def chart_settings(
    table: dict[str, Any], engines: dict[str, Any], base: Path, err: Callable[..., RecipeError]
) -> ChartSettings:
    """ChartSettings from a [charts] and an [engines] table; err(message, key) builds the error."""
    if table.get("kind", "auto") not in KINDS:
        raise err(f"[charts] kind must be one of {', '.join(KINDS)}", "kind")
    if "title" in table:
        try:
            re.compile(table["title"])
        except re.error as e:
            raise err(f"[charts] title is not a valid regular expression: {e}", "title") from None
    for name, style in table.get("crop", {}).items():
        if style not in CROPS:
            raise err(f"[charts] crop.{name} must be {' or '.join(CROPS)}", "crop")
    given: dict[str, Any] = {
        k: table[k] for k in ("kind", "title", "crop", "require_line") if k in table
    }
    if "box_height" in table:
        h = table["box_height"]
        if len(h) != 2 or not all(isinstance(v, int) and v > 0 for v in h):
            raise err("[charts] box_height needs two whole numbers: [low, high]", "box_height")
        given["box_height"] = tuple(h)
    given |= {k: tuple(table[k]) for k in ("categories", "names") if k in table}
    given |= {k: float(table[k]) for k in ("color_distance", "line_tolerance") if k in table}
    if "series" in table:
        given["series"] = {}
        for name, color in table["series"].items():
            rgb = hex_rgb(color) if isinstance(color, str) else None
            if rgb is None:
                raise err(f'[charts] series.{name} should be a color like "#ffc000"', "series")
            given["series"][name] = rgb
    if "cells" in table:
        try:
            given["cells"] = load_function(table["cells"], base, None, "[charts] cells")
        except RecipeError as e:
            raise err(e.message, "cells", hint=e.hint) from None
    if "use" in engines:
        given["engines"] = tuple(engines["use"])
    given |= {k: engines[k] for k in ("min_agree", "families") if k in engines}
    return ChartSettings(**given)


def charts_section(
    data: dict[str, Any], path: Path | None, err: Callable[..., RecipeError]
) -> ChartSettings | None:
    """The recipe's [charts] settings, or None when it has no [charts] section."""
    if "charts" not in data:
        return None
    base = path.parent if path else Path.cwd()
    return chart_settings(
        data["charts"], data.get("engines", {}), base, lambda m, k, **kw: err(m, "charts", k, **kw)
    )
