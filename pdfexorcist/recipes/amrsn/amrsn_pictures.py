"""AMRSN tables printed as pictures (Excel screenshots, mostly 2018-2022), read by OCR.

It reads the lines from a "Table N" caption to the next figure, caption or footer.
Each line is a row.
"""

import logging
import re
from collections.abc import Iterable, Iterator, Sequence
from difflib import get_close_matches
from functools import lru_cache
from pathlib import Path
from typing import Any

from amrsn_common import CAPTION, END, FOOT, chunks, cx
from amrsn_words import WORDS

from pdfexorcist.cells import BoxCell, cell_box, token_boxes, union
from pdfexorcist.pages import format_pages
from pdfexorcist.rows import is_value, parse_by_columns

logger = logging.getLogger(__name__)
# "Table 4 . 4". OCR can read a digit of the number as a letter ("Tablez.2.2").
OCR_CAPTION = re.compile(
    r"^\s*(?i:table)\s*((?=[\dzZlIoOS.\s]*\d)[\dzZlIoOS]+(?:\s*\.\s*[\dzZlIoOS]+)*[A-Za-z]?)\b"
)
DIGIT_LOOKALIKES = str.maketrans("zZlIoOS", "2211005")
# a data bar's edge read as a mark before a number ("_77", "|45") or after one ("78)")
SPECK = re.compile(r"(?<!\S)[_~|•«»]+(?=\d)")
TRAIL = re.compile(r"(?<=\d)[)\]|}]+$")
CENTRE = re.compile(r"\bRC[Il1]?\s+(\d{1,2})\b")  # "RC 01": the number names the centre
# An "R/n" count ("5887/8595"). A "*" before it marks a small n. OCR can read it as a quote.
RATIO = re.compile(r"^[*\"'“”]?\d+/\d+$")
PCT = re.compile(r"^\((?:\d+(?:\.\d+)?|-|–)\)$")  # the "(%)" printed under an "R/n"
PROSE = 6  # a line with this many words is prose
LABEL_WORD = re.compile(r"RC\d{1,2}|[A-Za-z][A-Za-z.\-/]+")  # words of a row label in a pair table
COL_GAP = 20  # points between the centres of two columns of centred values


def _is_val(tok: str) -> bool:
    """A value in a picture table: what is_value takes, an "R/n" count, or "(-)" (no %)."""
    return is_value(tok) or bool(RATIO.match(tok)) or tok in ("(-)", "(–)")


def _clean(cell: Sequence) -> BoxCell:
    """A cell without the marks OCR reads off a data bar around a number."""
    words = [SPECK.sub("", w) for w in str(cell[1]).split(" ")]
    words = [w if "(" in w else TRAIL.sub("", w) for w in words]  # "(97)" keeps its ")"
    return BoxCell(cell[0], CENTRE.sub(r"RC\1", " ".join(words)), cell_box(cell))


def _cells(line: list) -> list[BoxCell]:
    """A line's cleaned cells, with "RC" and its number read as two cells joined."""
    out: list[BoxCell] = []
    for c in map(_clean, line):
        if out and re.fullmatch(r"RC[Il1]?", out[-1][1]) and re.fullmatch(r"\d{1,2}", c[1]):
            out[-1] = BoxCell(out[-1][0], "RC" + c[1], union([cell_box(out[-1]), cell_box(c)]))
        else:
            out.append(c)
    return out


def _row_key(label: str) -> str:
    """A label's letters, and the digits of its first two words: "RC01", "ecoli". A word
    misread by one engine takes the nearest word of the antibiograms ("mipenem")."""
    head = "".join(re.findall(r"\d", "".join(label.split()[:2])))
    return "".join(_snap(w) for w in re.findall(r"[a-z]+", label.lower())) + head


@lru_cache(maxsize=4096)
def _snap(word: str) -> str:
    if len(word) < 4 or word in WORDS:
        return word
    return next(iter(get_close_matches(word, WORDS, n=1, cutoff=0.8)), word)


def _region(page_no: int, region: list, num: str, title: str | None) -> Iterator[dict]:
    """The table's values: rows keyed by _row_key, columns by number, with their headings.

    A table of mostly full rows places values by parse_by_columns. Where many cells are
    blank, a value's column comes from its right edge (Excel sets numbers flush right).
    """
    lines = [_cells(line) for line in region]
    toks_by_line = [[(t, b) for _, t, b in token_boxes(line) if b is not None] for line in lines]
    # a row has two values, or one in a table with a single column of values
    need = 2 if any(sum(_is_val(t) for t, _ in toks) >= 2 for toks in toks_by_line) else 1
    rows, heads = [], []
    for toks in toks_by_line:
        vals = [(t, b) for t, b in toks if _is_val(t)]
        if len(vals) >= need:
            rows.append((" ".join(t for t, _ in toks if not _is_val(t)), vals))
        elif not rows:
            heads.append(chunks(toks))
    # an "R/n" over "(%)" table: most rows hold a count (one misread "2083/61" does not count)
    if sum(any(RATIO.match(t) for t, _ in vals) for _, vals in rows) * 2 >= len(rows) > 0:
        yield from _pairs_region(page_no, num, title, toks_by_line, heads)
        return
    counts = [len(vals) for _, vals in rows]
    full = counts and counts.count(max(counts)) >= 0.6 * len(counts)
    cells = parse_by_columns([(page_no, lines)], min_values=2) if full else _by_edges(rows)
    seen: dict[str, int] = {}
    last, key = None, ""
    for c in cells:
        if c["row"] != last:
            last = c["row"]
            key = _row_key(c["label"])
            seen[key] = seen.get(key, 0) + 1
        yield {
            "page": page_no, "table": num, "title": title, "row": f"{key}#{seen[key]}",
            "col": c["col"], "column": _heading(heads, cx(c["box"])) if c.get("box") else "",
            "label": c["label"], "field": "value", "value": c["value"],
        }  # fmt: skip


def _field(tok: str) -> str:
    """ "pct" for the "(%)" under a count, "value" for anything else."""
    return "pct" if PCT.match(tok) else "value"


def _pairs_region(page_no: int, num: str, title: str | None, toks_by_line: list,
                  heads: list) -> Iterator[dict]:  # fmt: skip
    """An "R/n" over "(%)" table (2018). A count line opens a row. The "(%)" line and a
    centred label join this row. Each column is a cluster of value centres."""
    rows: list[tuple[list, list]] = []  # (label words, [(t, b)])
    for toks in toks_by_line[len(heads) :]:
        if _prose(" ".join(t for t, _ in toks)):
            break  # the text under the table
        vals = [(t, b) for t, b in toks if _is_val(t)]
        words = [t for t, _ in toks if not _is_val(t)]
        if any(RATIO.match(t) for t, _ in vals):
            rows.append((words, vals))
        elif rows:
            rows[-1][0].extend(words)
            rows[-1][1].extend(vals)
    centres = [_mid(g) for g in _groups([cx(b) for _, vals in rows for _, b in vals], COL_GAP)]
    seen: dict[str, int] = {}
    for words, vals in rows:
        # a misread count ("1933/25/2") or a speck ("g9") is not part of the agent's name
        label = " ".join(w for w in words if LABEL_WORD.fullmatch(w))
        key = _row_key(label)
        seen[key] = seen.get(key, 0) + 1
        for t, b in vals:
            col = min(range(len(centres)), key=lambda i: abs(centres[i] - cx(b)))
            yield {
                "page": page_no, "table": num, "title": title, "row": f"{key}#{seen[key]}",
                "col": col, "column": _heading(heads, centres[col]), "label": label,
                "field": _field(t), "value": t,
            }  # fmt: skip


def _groups(xs: list[float], gap: float) -> list[list[float]]:
    """Sort xs into groups. Each value is within gap points of the value before it."""
    groups: list[list[float]] = []
    for x in sorted(xs):
        if groups and x - groups[-1][-1] <= gap:
            groups[-1].append(x)
        else:
            groups.append([x])
    return groups


def _mid(group: list[float]) -> float:
    return group[len(group) // 2]


def _by_edges(rows: list) -> Iterator[dict]:
    """Values placed by their right edges, among the right edges of every row.

    A column is a right edge that most rows share. A stray edge is not a column.
    """
    groups = _groups([b[2] for _, vals in rows for _, b in vals], 4)
    need = max(2, round(0.3 * len(rows)))
    cols = [_mid(g) for g in groups if len(g) >= need] or [_mid(g) for g in groups]
    for r, (label, vals) in enumerate(rows):
        placed: dict[int, list] = {}
        for t, b in vals:
            placed.setdefault(min(range(len(cols)), key=lambda i: abs(cols[i] - b[2])), []).append(
                (t, b)
            )
        for col, tbs in sorted(placed.items()):
            value = "".join(t for t, _ in tbs)
            yield {"row": r, "col": col, "label": label, "value": value,
                   "box": union([b for _, b in tbs])}  # fmt: skip


def _heading(heads: list[list], x: float) -> str:
    """The headings over x, top to bottom ("ward / %s"): on each line the cell nearest x."""
    parts = []
    for line in heads:
        if not line:
            continue
        t, b = min(line, key=lambda c: abs(cx(c[1]) - x))
        if abs(cx(b) - x) <= 40 or b[0] - 6 <= x <= b[2] + 6:
            words = " ".join(_snap(w) for w in re.findall(r"[a-z]+|%|\d+", t.lower()))
            parts.append(words.replace("% ", "%"))
    return " / ".join(p for p in parts if p)


def parse(pages: Iterable) -> Iterator[dict]:
    """Yield each value of each captioned table, keyed by caption, row label and column."""
    carried = None  # a caption at the foot of a page, its picture on the next page
    for page_no, lines in pages:
        if lines and all(_boxless(line) for line in lines):  # a model's table cells
            yield from _model_page(page_no, lines)
            continue
        start, carried = carried, None
        for num, title, region, foot in _regions(lines, start):
            if _has_rows(region):
                yield from _region(page_no, region, num, title)
            elif foot:  # only the caption (and the rest of it, wrapped) above the footer
                rest = " ".join(" ".join(str(c[1]) for c in line) for line in region)
                carried = num, re.sub(r"\s+", " ", f"{title} {rest}").strip()


def _boxless(line: list) -> bool:
    """Whether a line came from a model that reads table cells but gives no word boxes
    (GLM-OCR, Chandra): its cells are (index, text)."""
    return all(getattr(c, "box", None) is None for c in line)


def _model_page(page_no: int, lines: list) -> Iterator[dict]:
    """A model's "R/n" over "(%)" tables, in the order of the picture captions in the text layer.
    Rows and columns get the same keys as in the word-box engines, so all readings vote."""
    captions = _picture_captions(page_no)
    tables = _model_tables(lines)
    if len(tables) != len(captions):
        logger.warning("page %d: %d tables read, %d captions", page_no, len(tables), len(captions))
    for (num, title), (heads, rows) in zip(captions, tables, strict=False):
        if not any(RATIO.match(t) for r in rows for _, c in r for t in c.split()):
            # Skip n and %S tables. Their blank cells give each engine different columns.
            continue
        maps = [dict(hr) for hr in heads]
        seen: dict[str, int] = {}
        for r in rows:
            label = r[0][1] if r[0][0] == 0 and not any(map(_is_val, r[0][1].split())) else ""
            key = _row_key(label)
            seen[key] = seen.get(key, 0) + 1
            for j, text in r:
                vals = [t for t in text.split() if _is_val(t)]
                if not vals or (label and j == 0):
                    continue
                column = _model_heading(maps, j)
                for t in vals:
                    yield {
                        "page": page_no, "table": num, "title": title,
                        "row": f"{key}#{seen[key]}", "col": j - 1 if label else j,
                        "column": column.lower(), "label": label,
                        "field": _field(t), "value": t,
                    }  # fmt: skip


def _model_heading(maps: list[dict], j: int) -> str:
    """The headings of column j in a model's table, from top to bottom."""
    return " / ".join(h for h in (m.get(j, "") for m in maps) if h)


def _model_tables(lines: list) -> list[tuple[list, list]]:
    """A model's rows split into tables: (heading rows, value rows). A row without values
    after value rows opens the next table."""
    tables: list[tuple[list, list]] = []
    heads: list = []
    rows: list = []
    for line in lines:
        cells = [(int(c[0]), str(c[1])) for c in line]
        text = " ".join(c for _, c in cells)
        # The model also reads captions and prose. A prose cell has many words.
        if CAPTION.match(text) or END.match(text) or any(_prose(c) for _, c in cells):
            if rows:
                tables.append((heads, rows))
            heads, rows = [], []
            continue
        if any(_is_val(t) for j, c in cells if j > 0 for t in c.split()):
            rows.append(cells)
            continue
        if rows:
            tables.append((heads, rows))
            heads, rows = [], []
        heads.append(cells)
    if rows:
        tables.append((heads, rows))
    return tables


def _picture_captions(page_no: int, pdf: str | None = None) -> list[tuple[str, str]]:
    """(number, caption) of each picture table on a page, from the text layer.

    A caption is above or below an image, or at the foot of the previous page.
    The default pdf is grid.current_pdf().
    """
    from pdfexorcist import grid

    try:
        pages = _doc_layout(pdf or str(grid.current_pdf()))
    except RuntimeError:  # not inside extract()
        return []
    lines, big, height = pages[page_no - 1]
    out = []
    if page_no > 1 and _opens_next(lines, big, height):
        prev, prev_big, _ = pages[page_no - 2]
        caps = [(b, t) for b, t in prev if CAPTION.match(t)]
        if caps and not any(i[1] >= caps[-1][0][3] for i in prev_big):
            out.append(caps[-1][1])
    for k, (_, t) in enumerate(lines):
        if not CAPTION.match(t):
            continue
        under, over, _ = _pictures(lines, k, big, height)
        if under or over:
            out.append(t)
    return [(re.sub(r"\s+", "", CAPTION.match(t)[1]), re.sub(r"\s+", " ", t).strip()) for t in out]


@lru_cache(maxsize=4)
def _doc_layout(pdf: str) -> list:
    import pymupdf

    with pymupdf.open(pdf) as doc:
        return [_layout(page) for page in doc]


def _caption_number(raw: str) -> str:
    """ "z.2.2" -> "2.2.2": letters OCR reads for digits, in the number (not a trailing "a")."""
    num = re.sub(r"\s+", "", raw)
    head, tail = (
        (num[:-1], num[-1]) if num[-1].isalpha() and num[-1] not in "zZlIoOS" else (num, "")
    )
    return head.translate(DIGIT_LOOKALIKES) + tail


def _prose(text: str) -> bool:
    return len(re.findall(r"[A-Za-z]{2,}", text)) >= PROSE


def _has_rows(region: list) -> bool:
    """Whether a caption's lines hold a value outside prose (a caption wrapped onto a second
    line holds none)."""
    for line in region:
        text = " ".join(str(c[1]) for c in line)
        if not _prose(text) and any(map(_is_val, text.split())):
            return True
    return False


def _regions(lines: list, start: tuple | None) -> Iterator[tuple[str, str, list, bool]]:
    """Each caption's (number, title, lines below it, whether the footer ended them).

    start is a caption from the previous page. Its lines open the page.
    """
    num, title = start or (None, None)
    region: list = []
    for line in [*lines, None]:
        text = " ".join(str(c[1]) for c in line) if line is not None else ""
        cap = OCR_CAPTION.match(text)
        foot = line is None or bool(FOOT.search(text))
        if not (foot or cap or END.match(text)):
            if num is not None:
                region.append(line)
            continue
        if num is not None:
            yield num, title, region, foot
        region, num, title = [], None, None
        if cap:
            num = _caption_number(cap[1])
            title = re.sub(r"\s+", " ", text).strip()


def picture_pages(pdf: str) -> list[int]:
    """Pages with a "Table N" caption above or below an image, and few numbers in the text layer.

    If a caption is at the foot of a page and its picture is on the next page, both pages count.
    """
    out: set[int] = set()
    pages = _doc_layout(pdf)
    for n, (lines, big, height) in enumerate(pages, start=1):
        caps = [i for i, (_, t) in enumerate(lines) if CAPTION.match(t)]
        for k, i in enumerate(caps):
            box = lines[i][0]
            under, over, bottom = _pictures(lines, i, big, height)
            if under:
                top, low = box[3], min(under, key=lambda b: b[1])[3]
            elif over:
                top, low = over[0][1], box[1]
            else:
                top, low = box[3], bottom
            if _numbers(lines, top, low) >= 6:
                continue
            if over and not under and _numbers(lines, box[3], bottom) >= 6:
                continue  # a figure above, a table in the text below
            if under or over:
                out.add(n)
            elif k == len(caps) - 1 and n < len(pages) and _opens_next(*pages[n]):
                out |= {n, n + 1}
    return sorted(out)


def _pictures(lines: list, i: int, big: list, height: float) -> tuple[list, list, float]:
    """Images below caption i, images just above it, and the bottom of the caption's region."""
    box = lines[i][0]
    bottom = next((b[1] for b, t in lines[i + 1 :] if _boundary(t)), height)
    under = [b for b in big if box[1] <= b[1] < bottom]
    return under, [b for b in big if 0 <= box[1] - b[3] < 40], bottom


def _boundary(text: str) -> bool:
    return bool(OCR_CAPTION.match(text) or END.match(text) or FOOT.search(text))


def _opens_next(lines: list, big: list, height: float) -> bool:
    """Whether the page opens with a picture of a table, before any caption or numbers."""
    first = min([b[1] for b, t in lines if CAPTION.match(t)], default=height)
    return any(b[1] < first and _numbers(lines, 0, b[1]) < 6 and not _figure(lines, b) for b in big)


def _layout(page: Any) -> tuple[list, list, float]:
    """A page's text lines (box, text) top to bottom, its large images, and its height."""
    import pymupdf

    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES  # image pixels left out
    lines = sorted(
        (
            (ln["bbox"], "".join(s["text"] for s in ln["spans"]))
            for b in page.get_text("dict", flags=flags)["blocks"]
            for ln in b.get("lines", [])
        ),
        key=lambda ln: ln[0][1],
    )
    images = [i["bbox"] for i in page.get_image_info()]
    big = [b for b in images if (b[2] - b[0]) * (b[3] - b[1]) > 20000]
    return lines, big, page.rect.height


def _figure(lines: list, image: tuple) -> bool:
    """Whether a "Figure" caption sits just under the image (a chart)."""
    return any(0 <= b[1] - image[3] < 40 and t.lstrip().startswith("Fig") for b, t in lines)


def _numbers(lines: list, top: float, bottom: float) -> int:
    """Numbers in the text lines between top and bottom, leaving out prose (6+ words)."""
    return sum(
        len(re.findall(r"\d+", t)) for b, t in lines if top <= b[1] < bottom and not _prose(t)
    )


def name_columns(cells: Any, pdf: Any) -> Any:
    """Postprocess: give a heading to each verified value that has none.

    A value gets the GLM-OCR heading if GLM-OCR read the same row label and value.
    Only GLM-OCR reads the vertical headings of 2018.
    """
    blank = (cells.status == "verified") & ~cells.column.fillna("").str.contains(r"[A-Za-z]{3}")
    if not blank.any():
        return cells
    try:
        model = dict(_model_pages(Path(pdf)))
    except (ImportError, ValueError, RuntimeError, OSError) as e:  # GLM-OCR missing or failed
        logger.warning("name_columns: no GLM-OCR reading (%s)", e)
        return cells
    heading: dict[tuple, str] = {}
    for page in {int(p) for p in cells.page[blank]}:
        lines = model.get(page)
        if not lines:
            continue
        for (num, _), (heads, rows) in zip(
            _picture_captions(page, str(pdf)), _model_tables(lines), strict=False
        ):
            maps = [dict(hr) for hr in heads]
            for r in rows:
                key = _row_key(r[0][1]) if r and r[0][0] == 0 else ""
                for j, text in r:
                    if j and heads:
                        name = _model_heading(maps, j)
                        heading[(page, num, key, j - 1, text.strip())] = name.lower()
    out = cells.copy()
    for i in out.index[blank]:
        c = out.loc[i]
        k = (int(c.page), str(c.table), str(c.row).split("#")[0], int(c.col), str(c.value).strip())
        if k in heading:
            out.at[i, "column"] = heading[k]
    return out


def _model_pages(pdf: Path) -> Iterator[tuple[int, list]]:
    from pdfexorcist._vlm_engines import glmocr_

    yield from glmocr_(pdf)  # cached per page after the first read


if __name__ == "__main__":  # prints the pages to give pictures.toml: "18-26,43,..."
    import sys

    print(format_pages(picture_pages(sys.argv[1])))
