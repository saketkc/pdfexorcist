"""IDSP reports read through their drawn cells: every layout, 2009 on.

Before 2017 the State (often District) cell merges over a state's rows. Each outbreak is
a drawn cell in the Cases column; every other column takes the cell over its middle
(grid.Table.at), and each engine's words are placed into those cells.

Rows are keyed by position ("3.0.4": page, table, row). Needs engines that give word boxes
(pdfplumber, pymupdf, pdfium); idsp_outbreaks.parse falls back to the text parser for the others.
"""

import math
import re
from collections.abc import Iterable, Iterator

from pdfexorcist import grid
from pdfexorcist.cells import Box, _inside, token_boxes

HEADER = [  # column -> header pattern; first match wins, so "cases/deaths" before either
    ("id", re.compile(r"unique|^s\.?\s*n|^s[lr]\.?(\s*no)?|serial", re.I)),
    ("state", re.compile(r"state", re.I)),
    ("district", re.compile(r"district", re.I)),
    ("disease", re.compile(r"disease|illness", re.I)),
    ("cases_deaths", re.compile(r"cases\s*/.*deaths", re.I)),
    ("cases", re.compile(r"cases", re.I)),
    ("deaths", re.compile(r"deaths?|eaths", re.I)),
    ("start", re.compile(r"start|onset", re.I)),
    ("reported", re.compile(r"report", re.I)),
    ("status", re.compile(r"status", re.I)),
    ("comment", re.compile(r"comment|action", re.I)),
]
LATE = re.compile(r"reported\s+late|previous\s+weeks?\s+reported", re.I)
# PDFium reads one heading as "FOLLOW UP OFDISEASE OUTBREAKS"
FOLLOW_UP = re.compile(r"FOLLOW[- ]?UP ?(OF ?)?(DISEASE ?)?(ALERTS/)?OUTBREAKS")
OTHER_TABLE = re.compile(r"name\s+of\s+(state|district)|unique\s+id", re.I)
# "12", "39 / 0", "97 (11 lab confirmed cases)", or a count not known: "-------", "NA", "Nil"
COUNT = re.compile(r"^\s*(\d[\d,]*(\s|$|[(/*])|[-\u2013\u2014]+\s*$|n\.?a\.?\s*$|nil\s*$)", re.I)
COUNT_MAX = 60  # longer text in the Cases column is another table's prose


def _is_count(text: str) -> bool:
    return bool(COUNT.match(text)) and len(text) <= COUNT_MAX


NUMERAL = re.compile(r"^\(?[ivxlc]+[.)]$", re.I)
# a cell may also open with an undotted "vii", in lower case ("vii Acute", 2012)
NUMERAL_LEAD = re.compile(r"^\s*(?:\(?(?i:[ivxlc]+)[.)]|[ivxlc]+(?=\s))\s*")
SKIP = {"comment"}

Word = tuple[str, Box, int]  # text, box, line number on the page


def parse(pages: Iterable) -> Iterator[dict]:
    """Yield each outbreak's cells keyed by its position in the drawn table."""
    tables = grid.tables(grid.current_pdf())
    columns: dict[str, float] | None = None
    section = "week"  # then "late", and "follow_up" (updates on earlier outbreaks, left out)
    rows: list[dict] = []
    for page_no, lines in pages:
        words = [
            (t, tb, i)
            for i, line in enumerate(lines)
            for _, t, tb in token_boxes(line)
            if tb is not None
        ]
        by_line: dict[int, list[Word]] = {}
        for w in words:
            by_line.setdefault(w[2], []).append(w)
        headings = []
        for ws in by_line.values():
            text = " ".join(w[0] for w in ws)
            kind = "follow_up" if FOLLOW_UP.search(text) else "late" if LATE.search(text) else None
            if kind:
                top = min(w[1][1] for w in ws)  # text top: banners sit in the rule
                headings.append((top, kind))
        headings.sort()
        for t_no, table in enumerate(tables.get(page_no, [])):
            x0, top, x1, _ = table.bbox
            if x1 - x0 < 300:  # a header fragment, not the outbreak table
                continue
            section = _section(headings, top + 5, section)
            inside = [w for w in words if _inside(table.bbox, *w[1])]
            lines = {c: _text(inside, c) for c in table.cells}
            flat = {c: " ".join(w for ws in t for w in ws) for c, t in lines.items()}
            head = _header(table, inside, flat)
            data_top = top
            if head is not None:
                columns, data_top = head
            elif OTHER_TABLE.search(" ".join(w[0] for w in inside if _mid(w) < top + 30)):
                columns = None
            if columns is None and (got := _infer(table, flat)) is not None:
                columns, data_top = got  # a header printed as loose glyphs
            if columns is not None and section != "follow_up":
                rows += _rows(
                    page_no, t_no, table, lines, flat, columns, section, data_top, headings
                )
        section = _section(headings, math.inf, section)
    _fill(rows)
    for r in rows:
        # key by Unique ID, as the text parser does, joining a wrapped one first
        uid = re.sub(r"\s+", "", r["cells"].pop("serial", "") or "")
        if UID.match(uid):
            r["key"] = uid
        elif uid:
            r["cells"]["serial"] = uid
        for col, v in r["cells"].items():
            if v:
                yield {
                    "id": r["key"],
                    "col": col,
                    "value": v,
                    "table": r["table"],
                    "page": r["page"],
                }


def _mid(w: Word) -> float:
    return (w[1][1] + w[1][3]) / 2


def _section(headings: list[tuple[float, str]], y: float, default: str) -> str:
    """The kind of the last heading above y, or default."""
    return ([kind for top, kind in headings if top < y] or [default])[-1]


def _text(words: list[Word], box: Box) -> list[list[str]]:
    """The words in box, one list per line, top to bottom."""
    by_line: dict[int, list[tuple[float, str]]] = {}
    for t, tb, i in words:
        if _inside(box, *tb):
            by_line.setdefault(i, []).append((tb[0], t))
    return [[t for _, t in sorted(ws)] for _, ws in sorted(by_line.items())]


def _header(
    table: grid.Table, words: list[Word], flat: dict[Box, str]
) -> tuple[dict[str, float], float] | None:
    """Column centres named by the header cells, and the header's bottom.

    "District" turns up in comments too ("District RRT visited"), so each is tried from the
    top until one sits in a row of column-sized cells that names the columns.
    """
    width = table.bbox[2] - table.bbox[0]

    def small(c: Box) -> bool:
        return c[2] - c[0] < 0.4 * width and c[3] - c[1] < 120

    for _, tb, _ in sorted(
        (w for w in words if re.search(r"district", w[0], re.I)), key=lambda w: w[1][1]
    ):
        cell = table.at((tb[0] + tb[2]) / 2, (tb[1] + tb[3]) / 2)
        if cell is None or not small(cell):
            continue
        if cell[1] > table.bbox[1] + 60:  # a header opens its table (after a banner)
            break
        beside = [c for c in table.cells if c[1] < cell[3] and c[3] > cell[1] and small(c)]
        top, bottom = min(c[1] for c in beside), max(c[3] for c in beside)
        spans: dict[tuple[int, int], list[str]] = {}  # stacked label cells: "No." "of" "Cases"
        for c in sorted(table.cells, key=lambda c: c[1]):
            in_band = c[1] >= top - 1 and c[3] <= bottom + 1 and c[2] - c[0] < 0.4 * width
            if in_band and (text := flat[c]):
                spans.setdefault((round(c[0]), round(c[2])), []).append(text)
        named: dict[str, float] = {}
        for (a, b), texts in sorted(spans.items()):
            text = " ".join(texts)
            glued = text.replace(" ", "")  # "Case" / "s" stacked in two cells
            if re.search(r"unique", text, re.I):  # 2025 week 22 prints S.No. and Unique ID
                named["id"] = (a + b) / 2
                continue
            for name, pat in HEADER:
                if name not in named and (pat.search(text) or pat.search(glued)):
                    named[name] = (a + b) / 2
                    break
        if {"state", "district", "disease"} <= named.keys() and (
            "cases" in named or "cases_deaths" in named
        ):
            return named, bottom
    return None


UID = re.compile(r"^[A-Z]{2,3}/[A-Z]{2,5}/\d{4}/\d+/\s*\d+")
DATE = re.compile(r"^\d{1,2}[-./]\d{1,2}[-./]\d{2,4}$")
STATUS = re.compile(r"under|control|surveillance|contained|investigation", re.I)


def _infer(table: grid.Table, flat: dict[Box, str]) -> tuple[dict[str, float], float] | None:
    """Column centres read off the rows, for a header printed as loose glyphs (2025 week 17).

    Only for reports with Unique IDs: each row starts with one, and its cells come in a fixed
    order (state, district, disease, cases, deaths, start, reported, status, comment).
    """
    starts = [c for c in table.cells if UID.match(flat[c])]
    if len(starts) < 2:
        return None
    votes: dict[str, list[float]] = {}
    for s in starts:
        mid = (s[1] + s[3]) / 2
        row = sorted(
            {c for c in table.cells if c[1] <= mid <= c[3] and flat[c]}, key=lambda c: c[0]
        )
        texts, counts, dates = [], [], []
        for c in row:
            t, x = flat[c], (c[0] + c[2]) / 2
            if c == s:
                votes.setdefault("id", []).append(x)
            elif _is_count(t):
                counts.append(x)
            elif DATE.match(t.replace(" ", "")):
                dates.append(x)
            elif STATUS.match(t) and len(t) < 30:
                votes.setdefault("status", []).append(x)
            elif c[2] - c[0] > 150:
                votes.setdefault("comment", []).append(x)
            else:
                texts.append(x)
        for name, x in [
            *zip(["state", "district", "disease"], texts, strict=False),
            *zip(["cases", "deaths"], counts, strict=False),
            *zip(["start", "reported"], dates, strict=False),
        ]:
            votes.setdefault(name, []).append(x)
    columns = {k: sorted(v)[len(v) // 2] for k, v in votes.items() if len(v) * 2 >= len(starts)}
    if not {"state", "district", "disease", "cases"} <= columns.keys():
        return None
    return columns, min(s[1] for s in starts) - 1


def _rows(
    page_no: int,
    t_no: int,
    table: grid.Table,
    lines: dict[Box, list[list[str]]],
    flat: dict[Box, str],
    columns: dict[str, float],
    section: str,
    data_top: float,
    headings: list[tuple[float, str]],
) -> list[dict]:
    cx = columns.get("cases", columns.get("cases_deaths"))
    anchors = sorted(
        {
            c
            for c in table.cells
            if c[0] <= cx <= c[2] and c[1] >= data_top - 1 and _is_count(flat[c])
        },
        key=lambda c: c[1],
    )
    out = []
    for i, a in enumerate(anchors):
        mid = (a[1] + a[3]) / 2
        cells: dict[str, str] = {}
        boxes: dict[str, Box | None] = {}
        for name, x in columns.items():
            box = table.at(x, mid)
            boxes[name] = box
            if name in SKIP or box is None:
                continue
            cells.update(_cell(name, lines[box]))
        out.append(
            {
                "key": f"{page_no}.{t_no}.{i}",
                "page": page_no,
                "boxes": boxes,
                # a banner can open the late table inside the same ruled box (2023)
                "table": _section(headings, a[1], section),
                "cells": cells,
            }
        )
    return out


def _cell(name: str, lines: list[list[str]]) -> dict[str, str]:
    """One drawn cell's text as column values; split "39 / 0" and lift the "iv." numeral."""
    out: dict[str, str] = {}
    if name == "disease":
        nums = [w for ws in lines for w in ws if NUMERAL.match(w)]
        lines = [[w for w in ws if not NUMERAL.match(w)] for ws in lines]
        text = _join([ws for ws in lines if ws])
        if lead := NUMERAL_LEAD.match(text):
            nums.append(lead.group().strip())
            text = text[lead.end() :]
        if nums:
            out["numeral"] = nums[0].lower()
        out["disease"] = text
        return out
    text = _join(lines)
    if name == "cases_deaths":
        m = re.match(r"^\s*(\d[\d,]*)\s*/\s*(\d+)", text)
        if m:
            return {"cases": m[1], "deaths": m[2]}
        return {"cases": text}
    if name in ("start", "reported"):
        return {name: text.replace(" ", "")}
    if name == "id":  # before Unique IDs this column numbers states; "id" is the row key
        return {"serial": text}
    return {name: text}


def _join(lines: list[list[str]]) -> str:
    """A cell's lines as one text, gluing words broken across lines.

    "Maharashtr" "a" and "Crimean-" "Congo" are one word; "Fever with" "rash" is two.
    """
    out = ""
    for ws in lines:
        part = " ".join(ws)
        if not out:
            out = part
            continue
        last = out.split()[-1]
        glue = (
            part[0].islower() and last[0].isupper() and len(last) >= 6 and last.isalpha()
        ) or last.endswith("-")
        out = f"{out}{part}" if glue else f"{out} {part}"
    return re.sub(r"\s+", " ", out).strip()


def _fill(rows: list[dict]) -> None:
    """Names a merged cell printed on one side of a page break, or beside another row.

    A blank State or District cell that ends a page takes the text of the one starting the
    next, and the reverse; before Unique IDs, rows sharing a state number share the state.
    """
    for box, col in (("id", "serial"), ("state", "state"), ("district", "district")):
        groups: list[list[dict]] = []
        for r in rows:
            if (
                groups
                and groups[-1][0]["page"] == r["page"]
                and groups[-1][0]["boxes"].get(box) == r["boxes"].get(box)
            ):
                groups[-1].append(r)
            else:
                groups.append([r])
        for i, g in enumerate(groups):
            if any(r["cells"].get(col) for r in g):
                continue
            page = g[0]["page"]
            donor = None
            if i + 1 < len(groups) and groups[i + 1][0]["page"] == page + 1:
                donor = groups[i + 1]  # last on its page, the next page's first
            elif i > 0 and groups[i - 1][0]["page"] == page - 1:
                donor = groups[i - 1]  # first on its page, the previous page's last
            if donor and col != "serial":  # a different state number: a different state
                mine, theirs = _first(g, "serial"), _first(donor, "serial")
                donor = None if mine and theirs and mine != theirs else donor
            if text := _first(donor or [], col):
                for r in g:
                    r["cells"][col] = text
    serial = None
    by_serial: dict[tuple[str, str], str] = {}
    keys = []
    for r in rows:
        sid = r["cells"].get("serial", "")
        if re.fullmatch(r"\d+\.?", sid):
            serial = sid
        elif sid:
            serial = None
        keys.append((r["table"], serial))
        if serial and r["cells"].get("state"):
            by_serial.setdefault((r["table"], serial), r["cells"]["state"])
    for r, k in zip(rows, keys, strict=True):
        if k[1] and not r["cells"].get("state") and k in by_serial:
            r["cells"]["state"] = by_serial[k]


def _first(group: list[dict], col: str) -> str | None:
    """The first non-blank text of col among the group's rows."""
    return next((r["cells"][col] for r in group if r["cells"].get(col)), None)
