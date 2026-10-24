"""AMRSN tables printed as pictures (Excel screenshots, mostly 2018-2022), read by OCR.

It reads the lines from a "Table N" caption to the next figure, caption or footer.
Each line is a row.
"""

import logging
import re
from collections.abc import Iterable, Iterator, Sequence
from difflib import SequenceMatcher, get_close_matches
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
# "Table 4.11 depicts sample-wise ...": a sentence about a table, not its caption
CAPTION_IN_PROSE = re.compile(
    r"^\s*(?i:table)\s*[\d.\s]+\s(?i:depicts|shows?|showed|presents?|gives)\b"
)
# a data bar's edge read as a mark before a number ("_77", "|45") or after one ("78)")
SPECK = re.compile(r"(?<!\S)[_~|•«»]+(?=\d)")
# also "1479D", "746I", "773_"; not "-", which ends half of a split range ("89.9-" "100")
TRAIL = re.compile(r"(?<=\d)(?:[)\]|}_.€DIlOoS]|[^\x00-\x7f])+$")  # and "116ął"
CENTRE = re.compile(r"\bRC[Il1]?\s+(\d{1,2})\b")  # "RC 01": the number names the centre
# "RCC04", "RCO05", "RC05 O", "RC113 3131": the centre is RC and the next two digits
RC_KEY = re.compile(r"^\s*R\s*C+\s*[IOo]?\s*(\d)(\d)?")
# An "R/n" count ("5887/8595"). A "*" before it marks a small n. OCR can read it as a quote.
RATIO = re.compile(r"^[*\"'“”]?\d+/\d+$")
PCT = re.compile(r"^\((?:\d+(?:\.\d+)?%?|-|–)\)$")  # the "(%)" under an "R/n"; "(61.4%)" in 2018
RANGE = re.compile(r"^\d+(?:\.\d+)?-\d+(?:\.\d+)?$")  # a "%Range" across centres (2018)
OPEN_RANGE = re.compile(r"^\d+(?:\.\d+)?-$")  # its first half, wrapped: "87.7-" over "99.8"
PROSE = 6  # a line with this many words is prose
LABEL_WORD = re.compile(r"RC\d{1,2}|[A-Za-z][A-Za-z.\-/]+")  # words of a row label in a pair table
COL_GAP = 20  # points between the centres of two columns of centred values
COUNT = re.compile(r"(?<=\d)\s+(?=\(\d+/\d+\))")  # "97.1 (68/70)": a % and its count, one cell


def _is_val(tok: str) -> bool:
    """A value in a picture table: what is_value takes, an "R/n" count, a "%Range", or "(-)"."""
    return is_value(tok) or bool(RATIO.match(tok) or RANGE.match(tok)) or tok in ("(-)", "(–)")


def _clean(cell: Sequence) -> BoxCell:
    """A cell without the marks OCR reads off a data bar around a number."""
    text = re.sub(r"\)(?=\d)", ") ", str(cell[1]))  # "(91.3)93.9": a (%) and the next value
    text = COUNT.sub("", text)
    words = [SPECK.sub("", w) for w in text.split(" ")]
    words = [w if "(" in w else TRAIL.sub("", w) for w in words]  # "(97)" keeps its ")"
    return BoxCell(cell[0], CENTRE.sub(r"RC\1", " ".join(words)), cell_box(cell))


def _cells(line: list) -> list[BoxCell]:
    """A line's cleaned cells, with "RC" and its number read as two cells joined."""
    out: list[BoxCell] = []
    for c in map(_clean, line):
        if out and re.fullmatch(r"RC[Il1]?", out[-1][1]) and re.fullmatch(r"\d{1,2}", c[1]):
            out[-1] = BoxCell(out[-1][0], "RC" + c[1], union([cell_box(out[-1]), cell_box(c)]))
        elif out and re.search(r"\d$", out[-1][1]) and re.fullmatch(r"\(\d+/\d+\)", c[1]):
            box = union([cell_box(out[-1]), cell_box(c)])
            out[-1] = BoxCell(out[-1][0], out[-1][1] + c[1], box)
        else:
            out.append(c)
    return out


def _row_key(label: str) -> str:
    """A label's letters, and the digits of its first two words: "RC01", "ecoli". A word
    misread by one engine takes the nearest word of the antibiograms ("mipenem")."""
    if m := RC_KEY.match(label):
        return f"rc{int(m[1] + (m[2] or '')):02d}"
    label = re.sub(r"(?<!\S)[OoIl|](?!\S)", " ", label)  # a data bar's edge read as "O" ("SHV O O")
    head = "".join(re.findall(r"\d", "".join(label.split()[:2])))
    return "".join(_snap(w) for w in re.findall(r"[a-z]+", label.lower())) + head


def _keys(labels: list[str]) -> list[str]:
    """Row keys: _row_key and the label's count so far ("caspofungin#2").

    Where labels repeat, a group printed once beside its block of rows joins the key: a label
    ending in the same word as labels with other words before it opens a group ("Essential
    agreement (%) Fluconazole", "Major errors (n) Fluconazole"; 2020 p65). An engine that
    misses a row then shifts only the rows of its group.
    """
    words = [lab.split() for lab in labels]
    groups: dict[str, set] = {}
    for w in words:
        if len(w) > 1:
            groups.setdefault(_row_key(w[-1]), set()).add(_row_key(" ".join(w[:-1])))
    repeats = len({_row_key(lab) for lab in labels}) < len(labels)
    group, out, seen = "", [], {}
    for lab, w in zip(labels, words, strict=True):
        key = _row_key(lab)
        if repeats and len(w) > 1 and len(groups.get(_row_key(w[-1]), ())) > 1:
            group, key = _row_key(" ".join(w[:-1])), _row_key(w[-1])
        key = f"{group}:{key}" if group else key
        seen[key] = seen.get(key, 0) + 1
        out.append(f"{key}#{seen[key]}")
    return out


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
    # an "R/n" over "(%)" table: a third of the rows hold a count, and counts and their (%)
    # lines make most rows (wrapped "%Range" halves and a "n=4609" line are the rest; 2018 p74)
    ratio = sum(any(RATIO.match(t) for t, _ in vals) for _, vals in rows)
    pct = sum(any(PCT.match(t) for t, _ in vals) for _, vals in rows)
    if rows and ratio * 3 >= len(rows) and ratio + pct >= 0.7 * len(rows):
        yield from _pairs_region(page_no, num, title, toks_by_line, heads)
        return
    counts = [len(vals) for _, vals in rows]
    full = counts and counts.count(max(counts)) >= 0.6 * len(counts)
    found = parse_by_columns([(page_no, lines)], min_values=2) if full else _by_edges(rows)
    cells = list(found)
    labels = {c["row"]: c["label"] for c in reversed(cells)}  # each row's first label
    order = list(dict.fromkeys(c["row"] for c in cells))
    keys = dict(zip(order, _keys([labels[r] for r in order]), strict=True))
    for c in cells:
        yield {
            "page": page_no, "table": num, "title": title, "row": keys[c["row"]],
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
        vals = [(t, b) for t, b in toks if _is_val(t) or OPEN_RANGE.match(t)]
        words = [t for t, _ in toks if not (_is_val(t) or OPEN_RANGE.match(t))]
        if any(RATIO.match(t) for t, _ in vals):
            rows.append((words, vals))
        elif rows:
            rows[-1][0].extend(words)
            rows[-1][1].extend(_close_ranges(rows[-1][1], vals))
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


def _close_ranges(above: list, vals: list) -> list:
    """vals of a line, with the second half of a range wrapped from the line above ("87.7-"
    over "99.8") joined to it in above. Returns the vals that are not such halves."""
    rest = []
    for t, b in vals:
        opens = [
            i
            for i, (u, c) in enumerate(above)
            if OPEN_RANGE.match(u) and abs(cx(c) - cx(b)) <= COL_GAP
        ]
        if opens and is_value(t):
            i = opens[0]
            above[i] = (above[i][0] + t, union([above[i][1], b]))
        else:
            rest.append((t, b))
    return rest


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


def _model_page(page_no: int, lines: list, pdf: str | None = None) -> Iterator[dict]:
    """A model's "R/n" over "(%)" tables, in the order of the picture captions in the text layer.
    Rows and columns get the same keys as in the word-box engines, so all readings vote."""
    captions = _picture_captions(page_no, pdf)
    tables = _model_tables(lines)
    if len(tables) != len(captions):
        logger.warning("page %d: %d tables read, %d captions", page_no, len(tables), len(captions))
    for (num, title), (heads, rows) in zip(captions, tables, strict=False):
        ratios = any(RATIO.match(t) for r in rows for _, c in r for t in c.split())
        if not ratios and len({max(j for j, _ in r) for r in rows}) > 1:
            # An n and %S table read with blank cells dropped: its columns shift row to row.
            # OXR keeps a blank as an empty cell, so its rows are all one width.
            continue
        if not ratios and heads and _drifts(heads[-1], rows):
            continue
        maps = [dict(hr) for hr in heads]
        # Columns are counted over those holding a value, as the box engines count them. A model
        # gives a data bar its own empty column ("324", "", "24"); that column is not counted.
        used = sorted(
            {
                j
                for r in rows
                for j, c in r
                if (all if j == 0 else any)(map(_is_val, c.split())) and c
            }
        )  # not "RC 01"
        labels = []
        for r in rows:
            # the cells before the first value: a group spanning rows ("Essential agreement
            # (%)") and the row's own label (2020 p65); "RC 01" is a label
            lead = []
            for j, c in r:
                if c and all(map(_is_val, COUNT.sub("", c).split())):
                    break
                lead.append((j, c))
            labels.append((" ".join(c for _, c in lead if c), {j for j, _ in lead}))
        keys = _keys([lab for lab, _ in labels])
        for (label, skip), key, r in zip(labels, keys, rows, strict=True):
            for j, text in r:
                text = re.sub(r"(?<=\d)-\s+(?=\d)", "-", text)  # a range wrapped in its cell
                text = COUNT.sub("", text)
                vals = [t for t in text.split() if _is_val(t)]
                if not vals or j in skip:
                    continue
                column = _model_heading(maps, j)
                for t in vals:
                    yield {
                        "page": page_no, "table": num, "title": title,
                        "row": key, "col": used.index(j),
                        "column": column.lower(), "label": label,
                        "field": _field(t), "value": t,
                    }  # fmt: skip


def _drifts(bottom: list, rows: list) -> bool:
    """Whether a value of a model's n / %S table sits under no "n" or "%S" of the bottom heading
    row. OXR can drop a data bar's empty cell in some rows only (2022 p90): the row's later
    values move one column left, under the blank heading over a bar."""
    named = [x for x, h in bottom if h]
    if len(named) < 4:  # no "n %S n %S" row to hold the columns to
        return False
    return any(
        min(abs(x - j) for x in named) > 0.5
        for r in rows
        for j, c in r
        if j > 0 and any(map(_is_val, c.split()))
    )


def _model_heading(maps: list[dict], j: int) -> str:
    """The headings of column j in a model's table, from top to bottom. A heading spanning
    columns sits at their middle ("Amikacin" over n and %S at 1.5); a column takes the nearest
    heading of each row (the label column's only for itself)."""
    out = []
    for m in maps:
        near = [(abs(x - j), h) for x, h in m.items() if h and (x > 0) == (j > 0)]
        if near:
            out.append(min(near)[1])
    return " / ".join(out)


def _model_tables(lines: list) -> list[tuple[list, list]]:
    """A model's rows split into tables: (heading rows, value rows). A row without values
    after value rows opens the next table."""
    tables: list[tuple[list, list]] = []
    heads: list = []
    rows: list = []
    for line in lines:
        if not line:  # OXR: the next picture
            if rows:
                tables.append((heads, rows))
            heads, rows = [], []
            continue
        # "4467/7274/(61.4%)": a model joins the two lines of a cell with "/"
        cells = [(int(c[0]), re.sub(r"(?<=\d)/\s*(?=\()", " ", str(c[1]))) for c in line]
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
        if rows and not any(c for j, c in cells if j > 0):
            continue  # a centre with no isolates ("RC 02"), or a spacer row: the table goes on
        if rows:
            tables.append((heads, rows))
            heads, rows = [], []
        heads.append([(float(c[0]), str(c[1])) for c in line])  # a spanning heading at 1.5
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


def _same_title(title: str | None, text: str) -> bool:
    """Whether two captions read alike after their numbers. Letters only: docTR can join the
    words ("Resultofdirect-antifungal")."""
    a, b = (re.sub(r"[^a-z]", "", OCR_CAPTION.sub("", str(t)).lower())[:40] for t in (title, text))
    return len(a) >= 10 and SequenceMatcher(None, a, b).ratio() >= 0.8


def _regions(lines: list, start: tuple | None) -> Iterator[tuple[str, str, list, bool]]:
    """Each caption's (number, title, lines below it, whether the footer ended them).

    start is a caption from the previous page. Its lines open the page.
    """
    num, title = start or (None, None)
    region: list = []
    for line in [*lines, None]:
        text = " ".join(str(c[1]) for c in line) if line is not None else ""
        cap = None if CAPTION_IN_PROSE.match(text) else OCR_CAPTION.match(text)
        if cap and num is not None and not _has_rows(region) and _same_title(title, text):
            continue  # the picture's own caption under the report's ("Table 4." under "Table 2.10")
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
    """Postprocess: a verified value takes a model's headings where a model read it, in an
    "R/n" table or where the vote gave it none.

    The word-box engines read the headings of the 2018 "R/n" pictures a column off (Table 6.2)
    or not at all (vertical); the models read those tables as a grid. Over an n / %S table a
    model can take a chart above for headings (2020 p84), so there the vote's headings stay.
    OXR is used first, then GLM-OCR.
    """
    heading: dict[tuple, str] = {}
    for engine in ("glmocr", "oxr"):  # OXR last, so its heading wins
        try:
            pages = dict(_model_pages(Path(pdf), engine))
        except (ImportError, ValueError, RuntimeError, OSError) as e:  # model missing or failed
            logger.warning("name_columns: no %s reading (%s)", engine, e)
            continue
        for page in {int(p) for p in cells.page}:
            for c in _model_page(page, pages.get(page) or [], str(pdf)):
                if c["column"]:
                    k = (page, c["table"], c["row"], c["col"], c["field"], c["value"])
                    heading[k] = c["column"]
    out = cells.copy()
    ratio = out.value.astype(str).str.match(RATIO.pattern)
    rn = ratio.groupby([out.page, out.table]).transform("any")
    blank = ~out.column.fillna("").str.contains(r"[A-Za-z]{3}")
    ok = (out.status == "verified") & (rn | blank)
    v = out[ok]
    keys = zip(v.page.astype(int), v.table.astype(str), v.row.astype(str), v.col.astype(int),
               v.field.astype(str), v.value.astype(str), strict=True)  # fmt: skip
    named = [heading.get(k) for k in keys]
    out.loc[ok, "column"] = [n or c for n, c in zip(named, out.column[ok], strict=True)]
    return out


def _model_pages(pdf: Path, engine: str) -> Iterator[tuple[int, list]]:
    from pdfexorcist._vlm_engines import glmocr_, oxr_

    yield from (oxr_ if engine == "oxr" else glmocr_)(pdf)  # cached per page after the first read


if __name__ == "__main__":  # prints the pages to give pictures.toml: "18-26,43,..."
    import sys

    print(format_pages(picture_pages(sys.argv[1])))
