"""Place voted cells on the page image."""

import logging
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import pandas as pd

from ._show_frames import (
    GEOMETRY_PREFERENCE,
    PAGE_FRAME,
    RENDER_FRAME,
    SHOW_DPI,
    USER_FRAME,
    _align,
    _engine_words,
    _Frames,
    _shift,
)
from ._show_layout import _cols, _ignored, _plain, _rounded, _rows, _type_unplaced
from .cells import Box
from .checks import Check, validate
from .readings import Readings, consensus, locate
from .vote import _pages, extract

logger = logging.getLogger(__name__)

__all__ = ["SHOW_DPI", "PageView", "inspect_page"]

STATUSES = ("agreed", "unresolved", "failed")


@dataclass
class PageView:
    """Everything the HTML and PNG views draw for one page."""

    source: str
    page: int
    image: Any  # PIL image the boxes are drawn on
    methods: list[str]
    min_agree: int | None
    key: list[str]
    cells: list[dict[str, Any]]  # one per voted cell
    rows: list[dict[str, Any]]  # {"label", "y"}: row names for the left margin
    cols: list[dict[str, Any]]  # {"label", "x", "named"}: column names for the top
    ignored: list[dict[str, Any]]  # {"text", "box"}: words not turned into a cell
    engines: list[dict[str, Any]]  # {"name", "readings", "geometry", "skipped"}
    notes: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        c = {s: sum(x["status"] == s for x in self.cells) for s in STATUSES}
        c["skipped"] = len(self.ignored)
        c["no_box"] = sum(x["box"] is None for x in self.cells)
        return c


def _key(row: Any, key: Sequence[str]) -> tuple[str, ...]:
    return tuple(str(row[k]) for k in key)


def build_view(
    res: pd.DataFrame,
    readings: Readings,
    page: Any,
    key: Sequence[str],
    columns: str = "col",
    rows: Sequence[str] | None = None,
    normalize: Callable[[str], str | None] | None = None,
    source: str = "",
    page_no: int = 1,
    methods: Sequence[str] = (),
    min_agree: int | None = None,
) -> PageView:
    """Place the voted cells (res) and every engine's readings on one page (a pymupdf page)."""
    key = [k for k in key if k in res.columns]
    frames = _Frames(page)
    rd = readings.cells
    notes: list[str] = []

    # each engine's words in display pixels; engines of unknown frame aligned to a reference
    words: dict[str, list[tuple[str, Box]]] = {}
    for m in readings.lines:
        ws = _engine_words(readings.page_lines(m))
        if ws:
            words[m] = [(t, frames.to_px(m, b)) for t, b in ws]
    known = [m for m in GEOMETRY_PREFERENCE if m in words] + [
        m for m in words if m in PAGE_FRAME | RENDER_FRAME | USER_FRAME
    ]
    ref = known[0] if known else next(iter(words), None)
    shift: dict[str, tuple[float, float]] = {}
    for m, ws in list(words.items()):
        if ref and m not in PAGE_FRAME | RENDER_FRAME | USER_FRAME and m != ref:
            shift[m] = _align(ws, words[ref])
            words[m] = [(t, _shift(b, shift[m])) for t, b in ws]

    # every reading's box: the parser's, else located among its engine's words
    own: dict[tuple[str, ...], dict[str, dict[str, Any]]] = {}
    located = 0
    for method, g in rd.groupby("method", sort=False) if len(rd) else []:
        m = str(method)
        boxes = list(g["box"])
        src = ["engine" if b is not None else None for b in boxes]
        missing = [i for i, b in enumerate(boxes) if b is None]
        lines = readings.page_lines(m)
        if missing and lines:
            found = locate([str(g["value"].iat[i]) for i in missing], lines, normalize)
            for i, b in zip(missing, found, strict=True):
                if b is not None:
                    boxes[i], src[i] = b, "located"
                    located += 1
        for (_, r), b, s in zip(g.iterrows(), boxes, src, strict=True):
            px = None
            if b is not None:
                px = _shift(frames.to_px(str(m), b), shift.get(str(m), (0.0, 0.0)))
            entry = own.setdefault(_key(r, key), {}).setdefault(
                str(m), {"values": [], "box": px, "src": s}
            )
            entry["values"].append(str(r["value"]))
    if located:
        notes.append(
            f"{located} readings had no position from their parser; they were found among "
            "their engine's words by value, in reading order."
        )

    cells: list[dict[str, Any]] = []
    failed_col = res["failed"] if "failed" in res.columns else pd.Series("", index=res.index)
    for i, (_, r) in enumerate(res.iterrows()):
        k = _key(r, key)
        per = own.get(k, {})
        mid = consensus([e["box"] for e in per.values() if e["src"]])
        status = (
            "unresolved"
            if r["status"] != "verified"
            else "failed"
            if str(failed_col.loc[cast(Any, r.name)] or "")
            else "agreed"
        )
        reads = {}
        for m, e in per.items():
            vals = list(dict.fromkeys(e["values"]))
            box, how = (e["box"], e["src"]) if e["src"] else (mid, "borrowed" if mid else None)
            reads[m] = {
                "value": vals[0] if len(vals) == 1 else " / ".join(vals),
                "two": len(vals) > 1,  # read two values: lost its vote here
                "box": _rounded(box),
                "src": how,
                "agrees": status != "unresolved" and vals == [str(r["value"])],
            }
        cells.append(
            {
                "i": i,
                "key": {c: _plain(r[c]) for c in key},
                "extra": {
                    c: _plain(r[c])
                    for c in res.columns
                    if c not in key
                    and c
                    not in (
                        "value",
                        "status",
                        "failed",
                        "n_agree",
                        "votes",
                        "sources",
                        "dissent",
                    )
                },
                "value": str(r["value"]),
                "status": status,
                "failed": str(failed_col.loc[cast(Any, r.name)] or ""),
                "votes": str(r.get("votes", "")),
                "n_agree": int(r.get("n_agree", 0) or 0),
                "box": _rounded(mid),
                "box_n": sum(1 for e in per.values() if e["src"]),  # engines placing it
                "readings": reads,
            }
        )
    no_box = sum(c["box"] is None for c in cells)
    if no_box:
        notes.append(
            f"{no_box} cells could not be placed on the page (no engine gave a position): "
            "they are in the Grid view only."
        )

    view_rows = _rows(cells, key, columns, rows)
    view_cols = _cols(cells, key, columns)
    ignored = _ignored(words.get(ref, []) if ref else [], cells)
    if not frames.angle and ref:
        typed = _type_unplaced(frames.image, words[ref])
        if typed:
            notes.append(
                f"{typed} words the engines read are not drawn on the page (outside its box, "
                "or invisible text); they are typed in grey where they sit."
            )
    engines = []
    for m in methods:
        n = int((rd["method"] == m).sum()) if len(rd) else 0
        engines.append(
            {
                "name": m,
                "readings": n,
                "geometry": m in words,
                "skipped": m not in readings.lines,
            }
        )
    return PageView(
        source=source,
        page=page_no,
        image=frames.image,
        methods=list(methods),
        min_agree=min_agree,
        key=list(key),
        cells=cells,
        rows=view_rows,
        cols=view_cols,
        ignored=ignored,
        engines=engines,
        notes=notes,
    )


def inspect_page(
    src: Path,
    page: int = 1,
    methods: list[str] | None = None,
    parse: Callable | None = None,
    key: Sequence[str] | None = None,
    min_agree: int | None = None,
    min_unopposed: int | None = None,
    families: dict[str, list[str]] | None = None,
    normalize: Callable[[str], str | None] | None = None,
    checks: Sequence[Check] = (),
    postprocess: Callable | None = None,
    columns: str = "col",
    rows: Sequence[str] | None = None,
    on_engine: Callable[[str, str, object], None] | None = None,
    n_pages: int | None = None,
    fit_boxes: bool = True,
    jobs: int = 1,
) -> PageView:
    """Vote and render one PDF or image page."""
    import pymupdf

    from ._run import _page_count
    from .pages import IMAGE_SUFFIXES
    from .rows import KEY, parse_rows

    key = list(key or KEY)
    src = Path(src)
    if n_pages is None:
        n_pages = _page_count(src, src.suffix.lower() in IMAGE_SUFFIXES)
    with tempfile.TemporaryDirectory() as tmp:
        # cut as extract --pages N cuts it
        cut = src if n_pages == 1 else _pages(src, [page], Path(tmp))
        res, readings = extract(
            cut,
            methods,
            parse=parse or parse_rows,
            key=key,
            min_agree=min_agree,
            min_unopposed=min_unopposed,
            families=families,
            normalize=normalize,
            on_engine=on_engine,
            fit_boxes=fit_boxes,
            jobs=jobs,
            return_readings=True,
        )
        if postprocess is not None:
            res = postprocess(res, cut)
        if checks:
            ok = res.status == "verified"
            res["failed"] = validate(res[ok], checks)["failed"].reindex(res.index, fill_value="")
        with pymupdf.open(stream=readings.pdf, filetype="pdf") as doc:  # what the engines read
            view = build_view(
                res,
                readings,
                doc[0],
                key,
                columns=columns,
                rows=rows,
                normalize=normalize,
                source=str(src),
                page_no=page,
                methods=methods or sorted(readings.lines),
                min_agree=min_agree,
            )
    for c in view.cells:  # the original page number, as extract's CLI writes it
        if "page" in c["key"] and str(c["key"]["page"]) == "1":
            c["key"]["page"] = page
    return view
