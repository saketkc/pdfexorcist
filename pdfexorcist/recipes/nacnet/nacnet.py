"""NCDC NAC-NET antimicrobial consumption reports: printed chart values and tables.

postprocess adds each bar's drawn length (`estimate`, `pm`) and a row, status `estimated`, for
every bar that prints no label. Table rows and columns come from pdfplumber's words.
"""

import re
from collections.abc import Iterable, Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

import nacnet_bars as nb
import nacnet_ocr
import nacnet_pies as npie
import nacnet_pixels as npx
import pandas as pd

from pdfexorcist import check, grid
from pdfexorcist.cells import Box, token_boxes

FIG = re.compile(r"^(Figure|Fig\.|Table)\s*(\d+[a-z]?(?:\s*&\s*\d+[a-z]?)?)", re.I)


def _fig(title: str) -> str:
    m = FIG.match(title)
    return f"{m[1].title()} {m[2].replace(' ', '')}" if m else title[:30]


def _words(lines: Iterable) -> list[tuple[str, Box]]:
    return [(t, tb) for line in lines for _, t, tb in token_boxes(line) if tb is not None]


def _in(b: Box, box: Box, pad: float) -> bool:
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return box[0] - pad <= cx <= box[2] + pad and box[1] - pad <= cy <= box[3] + pad


def _is_tick(b: Box, ticks: list) -> bool:
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return any(
        abs(cx - (t[0] + t[2]) / 2) < 3 and abs(cy - (t[1] + t[3]) / 2) < 3 for _, t in ticks
    )


def parse(pages: Iterable) -> Iterator[dict]:
    """Yield each chart label in its bar's slot, each pie label, and each table cell."""
    yield from _parse(pages, nb.page_charts, text=True)


def parse_pictures(pages: Iterable) -> Iterator[dict]:
    """The same for bar charts pasted as pictures (OCR engines' words)."""
    yield from _parse(pages, npx.page_charts, text=False)


def _parse(pages: Iterable, charts: Any, text: bool) -> Iterator[dict]:
    pdf = str(grid.current_pdf())
    for page_no, lines in pages:
        ws = _words(lines)
        for ch in charts(pdf, page_no):
            for t, b in ws:
                if not nb.NUM.fullmatch(t) or not _in(b, ch.box, nb.NEAR) or _is_tick(b, ch.ticks):
                    continue
                bar = nb.owner(ch, b)
                if bar is not None:
                    yield {
                        "page": page_no,
                        "item": _fig(ch.title),
                        "chart": ch.no,
                        "slot": bar.slot,
                        "series": bar.series,
                        "field": "label",
                        "value": t,
                    }
        if text:
            yield from _pie_labels(pdf, page_no, ws)
            yield from _tables(pdf, page_no, ws)


def _pie_labels(pdf: str, page_no: int, ws: list[tuple[str, Box]]) -> Iterator[dict]:
    """Numbers printed on or beside each pie wedge. "55.1, 42%" is one label: the words of a
    label on one line go to one wedge, as "value" and "pct"."""
    for pie in npie.page_pies(pdf, page_no):
        w, h = pie.box[2] - pie.box[0], pie.box[3] - pie.box[1]
        # an engine can glue the heading to the label beside it ("201743%"): cut the heading off
        ws = [
            (t[len(pie.heading) :], b)
            if pie.heading
            and t.startswith(pie.heading)
            and nb.NUM.fullmatch(t[len(pie.heading) :].rstrip(","))
            else (t, b)
            for t, b in ws
        ]
        near = [
            (t.rstrip(","), b)
            for t, b in ws
            if nb.NUM.fullmatch(t.rstrip(","))
            and t != pie.heading
            and abs((b[0] + b[2] - pie.box[0] - pie.box[2]) / 2) < w
            and abs((b[1] + b[3] - pie.box[1] - pie.box[3]) / 2) < h
        ]
        groups: list[list[tuple[str, Box]]] = []
        for t, b in sorted(near, key=lambda x: (round(x[1][1]), x[1][0])):
            last = groups[-1][-1][1] if groups else None
            if last and abs(b[1] - last[1]) < 2 and 0 <= b[0] - last[2] < 6:
                groups[-1].append((t, b))
            else:
                groups.append([(t, b)])
        for g in groups:
            box = (
                min(b[0] for _, b in g),
                min(b[1] for _, b in g),
                max(b[2] for _, b in g),
                max(b[3] for _, b in g),
            )
            wedge = npie.owner(pie, box)
            if wedge is None:
                continue
            for t, _ in g:
                yield {
                    "page": page_no,
                    "item": _fig(pie.title),
                    "chart": f"pie{pie.no}",
                    "slot": pie.heading,
                    "series": wedge.series,
                    "field": "pct" if t.endswith("%") else "value",
                    "value": t,
                }


TABLE_END = 18.0  # a vertical gap this wide ends a table


Cell = tuple[float, float, float, float, str]


def _joined(line: list[tuple[str, Box]]) -> list[list[Any]]:
    out: list[list[Any]] = []
    for t, b in line:
        if out and b[0] - out[-1][2] < 6:
            out[-1][2] = b[2]
            out[-1][4] += " " + t
        else:
            out.append([b[0], b[1], b[2], b[3], t])
    return out


def _read_table(lines: list, head: list[Cell]) -> tuple[list[Cell], list[tuple[Cell, str]]]:
    """(header cells, data cells with their section) from the lines under a caption, or from the
    top of a page that continues a table (head: the header from the page before)."""
    data: list[tuple[Cell, str]] = []
    section = ""
    own = not head  # the header is on this page (not carried from the page before)
    bottom = lines[0][0][1][1] if lines else 0.0
    for line in lines:
        if line[0][1][1] - bottom > TABLE_END or nb.CAPTION.match(line[0][0]):
            break
        cells = _joined(line)
        digits = any(re.fullmatch(r"[\d.,%<>-]+", c[4]) for c in cells)  # a cell that is a number
        if any(len(c[4].split()) > 6 for c in cells):
            if data:
                break  # a note or prose after the table
            continue
        if len(cells) == 1 and not digits:
            if (
                own
                and head
                and not data
                and any(h[0] < cells[0][2] and cells[0][0] < h[2] for h in head)
            ):
                head = [
                    (h[0], h[1], max(h[2], cells[0][2]), h[3], f"{h[4]} {cells[0][4]}")
                    if h[0] < cells[0][2] and cells[0][0] < h[2]
                    else h
                    for h in head
                ]  # a wrapped heading
            else:
                section = cells[0][4].rstrip("*")  # a heading across the table ("G-SACNET SITES*")
        elif not digits and not data:
            head = [tuple(c) for c in cells]  # type: ignore[misc]
        else:
            data += [(tuple(c), section) for c in cells]  # type: ignore[misc]
        bottom = max(b[3] for _, b in line)
    return head, data


@lru_cache(maxsize=64)
def _layout(pdf: str, page_no: int) -> list[tuple[str, list[Cell], list[tuple[Cell, str]]]]:
    """Per table on the page: (caption, header cells, data cells with section) from pdfplumber.
    A page without a caption whose top lines are table rows continues the table before."""
    import pdfplumber

    with pdfplumber.open(pdf) as doc:
        ws = nb.words(doc.pages[page_no - 1])
    lines = nb._lines(ws)
    out = []
    for i, line in enumerate(lines):
        text = " ".join(t for t, _ in line)
        if re.match(r"^Table\s*\d+\s*:", text) and not re.search(r"\.{5,}", text):
            head, data = _read_table(lines[i + 1 :], [])
            out.append((text, head, data))
    if not out and page_no > 1 and lines:
        before = _layout(pdf, page_no - 1)
        if before and before[-1][2]:
            head, data = _read_table(lines, before[-1][1])
            if len({round(c[1]) for c, _ in data}) >= 3:
                out.append((before[-1][0], head, data))
    return out


def _tables(pdf: str, page_no: int, ws: list[tuple[str, Box]]) -> Iterator[dict]:
    """Each engine's words placed in the cells of each table, keyed by row (its position, first
    cell and section) and column heading. The words of one cell join left to right."""
    for caption, head, data in _layout(pdf, page_no):
        if not data:
            continue
        cells = [c for c, _ in data]
        section = {round(c[1]): s for c, s in data}
        rows = sorted(section)
        cols = _columns(cells + list(head))
        names = {_col(cols, c): c[4] for c in head}
        got: dict[tuple[int, int], list[tuple[float, str]]] = {}
        for t, b in ws:
            if not any(
                c[0] - 2 <= (b[0] + b[2]) / 2 <= c[2] + 2
                and c[1] - 2 <= (b[1] + b[3]) / 2 <= c[3] + 2
                for c in cells
            ):
                continue
            row = min(rows, key=lambda r: abs(r - b[1]))
            if abs(row - b[1]) <= 4:
                got.setdefault((row, _col(cols, (b[0], b[1], b[2], b[3], t))), []).append((b[0], t))
        for (row, col), parts in got.items():
            label = " ".join(c[4] for c in cells if round(c[1]) == row and _col(cols, c) == 0)
            yield {
                "page": page_no,
                "item": _fig(caption),
                "chart": row,
                "slot": f"{section[row]} {label}".strip(),
                "series": names.get(col, str(col)),
                "field": "cell",
                "value": " ".join(t for _, t in sorted(parts)),
            }


def _columns(cells: list) -> list[tuple[float, float]]:
    spans: list[list[float]] = []
    for c in sorted(cells, key=lambda c: c[0]):
        if spans and c[0] < spans[-1][1] + 2:
            spans[-1][1] = max(spans[-1][1], c[2])
        else:
            spans.append([c[0], c[2]])
    return [(a, b) for a, b in spans]


def _col(cols: list[tuple[float, float]], c: tuple) -> int:
    mid = (c[0] + c[2]) / 2
    return min(
        range(len(cols)),
        key=lambda i: (
            0
            if cols[i][0] <= mid <= cols[i][1]
            else min(abs(mid - cols[i][0]), abs(mid - cols[i][1]))
        ),
    )


def postprocess(cells: pd.DataFrame, pdf: Any) -> pd.DataFrame:
    """Name each chart value's category, add the drawn estimate, and add unlabelled bars."""
    return _post(cells, pdf, nb.page_charts)


def postprocess_pictures(cells: pd.DataFrame, pdf: Any) -> pd.DataFrame:
    return _post(cells, pdf, npx.page_charts)


def _post(cells: pd.DataFrame, pdf: Any, charts: Any) -> pd.DataFrame:
    path = str(Path(pdf))
    out = cells.copy()
    for col in ("title", "category", "category_from", "estimate", "pm"):
        out[col] = None
    extra = []
    import pdfplumber

    with pdfplumber.open(path) as doc:
        n_pages = len(doc.pages)
    for page in range(1, n_pages + 1):
        for ch in charts(path, page):
            fig = _fig(ch.title)
            read = nacnet_ocr.categories(path, ch) if any(not b.category for b in ch.bars) else {}
            for bar in ch.bars:
                cat, src = (
                    (bar.category, "text")
                    if bar.category
                    else (_site(read.get(bar.slot, "")), "ocr")
                )
                src = src if cat else ""
                hit = (
                    (out.page.astype(int) == page)
                    & (out.field == "label")
                    & (out.chart.astype(str) == str(ch.no))
                    & (out.slot.astype(str) == str(bar.slot))
                    & (out.series == bar.series)
                )
                if hit.any():
                    out.loc[hit, ["title", "category", "category_from", "estimate", "pm"]] = [
                        ch.title,
                        cat,
                        src,
                        bar.value,
                        bar.pm,
                    ]
                else:
                    extra.append(
                        {
                            "page": page,
                            "item": fig,
                            "chart": ch.no,
                            "slot": bar.slot,
                            "series": bar.series,
                            "field": "label",
                            "value": "",
                            "title": ch.title,
                            "category": cat,
                            "category_from": src,
                            "estimate": bar.value,
                            "pm": bar.pm,
                            "status": "estimated",
                        }
                    )
    pie = out.chart.astype(str).str.startswith("pie")
    out.loc[pie, "category"] = out.loc[pie, "slot"]
    out.loc[pie, "category_from"] = "text"
    for (page, chart), g in out[pie].groupby(["page", "chart"]):
        titles = [p.title for p in npie.page_pies(path, int(page)) if f"pie{p.no}" == chart]
        out.loc[g.index, "title"] = titles[0] if titles else ""
    tab = out.field == "cell"
    out.loc[tab, "category"] = out.loc[tab, "slot"]
    out.loc[tab, "category_from"] = "text"
    return pd.concat([out, pd.DataFrame(extra)], ignore_index=True) if extra else out


def _site(text: str) -> str:
    """Site codes as the report prints them in text: "NAC 7", "GJ19", "KL3"."""
    m = re.fullmatch(r"(NAC|GJ|KL)\s*(\d+)", text.strip(), re.I)
    if not m:
        return text
    return f"NAC {m[2]}" if m[1].upper() == "NAC" else f"{m[1].upper()}{m[2]}"


@check("pie percentages do not add to 100")
def pie_total(df: pd.DataFrame) -> pd.Series:
    """A pie's printed percentages (rounded) more than 2 points from 100."""
    pct = df.field == "pct"
    v = pd.to_numeric(df.value.astype(str).str.rstrip("%"), errors="coerce")
    total = v.where(pct).groupby([df.page, df.chart]).transform("sum")
    return pct & ((total - 100).abs() > 2)


@check("label off its bar")
def label_off_bar(df: pd.DataFrame) -> pd.Series:
    """A printed label more than 2 pm plus half its last digit from its bar's drawn length."""
    v = pd.to_numeric(df.value.astype(str).str.rstrip("%"), errors="coerce")
    est = pd.to_numeric(df.get("estimate"), errors="coerce")
    pm = pd.to_numeric(df.get("pm"), errors="coerce")
    dec = df.value.astype(str).str.extract(r"\.(\d+)")[0].str.len().fillna(0)
    half = 0.5 * 10.0 ** (-dec)
    return (df.field == "label") & v.notna() & est.notna() & ((v - est).abs() > 2 * pm + half)
