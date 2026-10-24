"""NACO HIV tables by State/UT: Sankalak and the India HIV Estimates.

A row is a line whose label names a State/UT (naco_states.py). "0.62 (0.53-0.74)" gives
the column, "<column>_lower" and "<column>_upper". Rows under a figure caption are skipped.
"""

import re
import statistics
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from naco_states import JK_LADAKH, state

from pdfexorcist.cells import token_boxes
from pdfexorcist.rows import Page

CAPTION = re.compile(r"^(Table|Annexure|Figure)\.?$", re.I)
# a running head an engine joins to the start of a caption line ("70 | India HIV ...")
HEAD = re.compile(r"^(\d+|\||India|HIV)$")
CAPTION_NO = re.compile(r"^(\d+(?:\.\d+)*)[.:]?$")
CONTINUED = re.compile(r"\(?\b(contd|continued)\b", re.I)
NUM = r"[-+]?(?:[≥≤<>]=?)?\d[\d,]*(?:\.\d+)?%?"
INTERVAL = re.compile(rf"^({NUM})\(({NUM})(?:-|,|to)({NUM})\)$")
PLAIN = re.compile(rf"^{NUM}$")
# an Excel error printed in a cell (#DIV/0!) is kept: the lossy check fails it
EXCEL = r"#DIV/0!|#N/A|#REF!|#VALUE!"
PLACEHOLDER = re.compile(rf"^(-|NA|N\.A\.|ND|NR|\*|{EXCEL})$", re.I)
# a token of a value: "1,22,433", "(0.53-0.74)", "≥95", "(134.99-", "-"
VALUEISH = re.compile(
    rf"^([(]?[-+]?(?:[≥≤<>]=?)?\d[\d,.%()≥≤<>-]*|-|NA|N\.A\.|ND|NR|to|{EXCEL})$", re.I
)
# HIV Estimates tables whose columns get names: (caption, column count, names)
KEY = ("prevalence", "plhiv", "incidence", "new_infections", "new_infections_change")
NAMED = [
    (r"key indicators", (*KEY, "mortality", "deaths", "deaths_change", "evth_need")),
    (r"adult hiv prevalence and plhiv", KEY[:2]),
    (r"incidence rate, annual new infections", KEY[2:]),
    (r"aids-related mortality rate", ("mortality", "deaths", "deaths_change")),
    (r"^pmtct need by", ("pmtct_need",)),
]
YEAR = re.compile(r"^(?:19|20)\d\d(?:-\d\d)?$")

Token = tuple[float, str]


def _dashes(text: str) -> str:
    return re.sub(r"[–—−]", "-", text)


@dataclass
class Row:
    state: str
    items: list[tuple[float, str, str, str]]  # (x, value, lower, upper)


@dataclass
class Segment:
    """The rows of one table on one page."""

    table: str
    title: str
    page: int
    header: list[list[Token]] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)


def _items(tokens: list[Token]) -> list[tuple[float, str, str, str]] | None:
    """Group value tokens into (x, value, lower, upper); None if they do not parse.

    An interval runs to its ")" or, when the ")" is not printed, to the next value.
    """
    out: list[tuple[float, str, str, str]] = []
    i = 0
    while i < len(tokens):
        x, text = tokens[i]
        j = i + 1
        if "(" in text or (PLAIN.match(text) and j < len(tokens) and tokens[j][1][0] == "("):
            while j < len(tokens) and not text.endswith(")"):
                unclosed = ")" not in text and PLAIN.match(tokens[j][1])
                if unclosed and INTERVAL.match(text + ")"):
                    break  # "(134.99-186.68" then the next value
                text += tokens[j][1]
                j += 1
            if not text.endswith(")"):
                text += ")"
        m = INTERVAL.match(text)
        if m:
            out.append((x, *(v.replace(",", "") for v in m.groups())))
        elif PLAIN.match(text):
            out.append((x, text.replace(",", ""), "", ""))
        elif PLACEHOLDER.match(text):
            out.append((x, text, "", ""))
        else:
            return None
        i = j
    return out


def _split(line: list[Token]) -> tuple[list[Token], list[Token]]:
    """Split a line into its label tokens and its trailing value tokens."""
    i = len(line)
    while i and VALUEISH.match(line[i - 1][1]):
        i -= 1
    return line[:i], line[i:]


def _label(tokens: list[Token]) -> str:
    return " ".join(t for _, t in tokens)


def _caption(line: list[Token]) -> tuple[str, str] | None:
    """(table, title) for a caption line ("Table 2. Adult HIV ..."), else None."""
    words = [t for _, t in line]
    for i in range(min(3, len(words) - 1)):
        m = CAPTION_NO.match(words[i + 1])
        if CAPTION.match(words[i]) and m:
            return f"{words[i].rstrip('.').title()} {m.group(1)}", " ".join(words[i + 2 :])
        if not HEAD.match(words[i]):
            return None
    return None


def _rows(lines: list[list[Token]], seg_of: list[Segment | None]) -> None:
    """Fill each segment's header and rows from the lines of one page."""
    prev_label: list[Token] = []  # the line above, when it held only a label
    skip = False
    for n, line in enumerate(lines):
        seg = seg_of[n]
        if skip or seg is None:
            skip, prev_label = False, []
            continue
        label, values = _split(line)
        items = _items(values) if values else None
        nxt = lines[n + 1] if n + 1 < len(lines) else []
        nxt_label, nxt_values = _split(nxt)
        name = state(_label(label)) if label else None
        if items and name is None:
            if label and prev_label:
                name = state(_label(prev_label + label))
            if name is None and label and nxt_label and not nxt_values:
                name = state(_label(label + nxt_label))
                skip = name is not None
            if name is None and not label and prev_label:
                name = state(_label(prev_label))
                # a serial number printed beside the values: left of the name
                left = prev_label[0][0]
                while items and items[0][0] < left - 1 and re.match(r"^\d{1,2}$", items[0][1]):
                    items = items[1:]
        if items and name:
            last = Row(name, items)
            seg.rows.append(last)
            prev_label = []
            # one cell over two rows: "Jammu & Kashmir" above "(and) Ladakh"
            below = state(_label(nxt_label)) if nxt_label and not nxt_values else None
            if name == "Jammu & Kashmir" and below in ("Ladakh", JK_LADAKH):
                last.state, skip = JK_LADAKH, True
            continue
        if not seg.rows:
            seg.header.append(line)
        prev_label = label if label and not values else []


def _names(seg: Segment, ncols: int) -> list[str]:
    """Column names: NAMED, the years of one header line, else 1, 2, ..."""
    for pattern, names in NAMED:
        if re.search(pattern, seg.title, re.I) and len(names) == ncols:
            return list(names)
    for line in reversed(seg.header):
        years = [t for _, t in line if YEAR.match(t)]
        if len(years) == ncols and len(set(years)) == ncols:
            return years
    return [str(i + 1) for i in range(ncols)]


def _cells(seg: Segment) -> Iterator[dict]:
    """Yield the cells of one segment.

    A row with fewer values than most rows places each in the nearest column; a row with
    more is not read.
    """
    if not seg.rows:
        return
    ncols = Counter(len(r.items) for r in seg.rows).most_common(1)[0][0]
    full = [r for r in seg.rows if len(r.items) == ncols]
    centres = [statistics.median(r.items[i][0] for r in full) for i in range(ncols)]
    names = _names(seg, ncols)
    seen: set[str] = set()
    for row in seg.rows:
        if len(row.items) > ncols or row.state in seen:
            continue
        seen.add(row.state)
        if len(row.items) == ncols:
            cols = list(range(ncols))
        else:
            cols = [min(range(ncols), key=lambda i: abs(centres[i] - it[0])) for it in row.items]
            if len(set(cols)) < len(cols):
                continue
        for c, (_, value, lower, upper) in zip(cols, row.items, strict=True):
            base = {"table": seg.table, "title": seg.title, "state": row.state, "page": seg.page}
            yield {**base, "col": names[c], "value": _dashes(value)}
            if lower:
                yield {**base, "col": f"{names[c]}_lower", "value": _dashes(lower)}
                yield {**base, "col": f"{names[c]}_upper", "value": _dashes(upper)}


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each value of the State/UT tables keyed by table, State/UT and column."""
    table, title = "", ""
    seen: set[tuple[str, str, str]] = set()
    for page_no, raw in pages:
        lines = [
            [(x, _dashes(t)) for x, t, _ in token_boxes(sorted(cells, key=lambda c: c[0]))]
            for cells in raw
        ]
        lines = [line for line in lines if line]
        segments: list[Segment] = []
        seg_of: list[Segment | None] = []
        seg: Segment | None = None
        for line in lines:
            cap = _caption(line)
            if cap is not None:
                if not (cap[0] == table and CONTINUED.search(cap[1])):
                    table, title = cap[0], CONTINUED.split(cap[1])[0].strip(" .:")
                seg = None
                seg_of.append(None)
                continue
            if seg is None:
                seg = Segment(table, title, page_no)
                segments.append(seg)
            seg_of.append(seg)
        _rows(lines, seg_of)
        for seg in segments:
            if seg.table.startswith("Figure"):
                continue  # State names printed in a chart
            cells = list(_cells(seg))
            keys = {(c["table"], c["state"], c["col"]) for c in cells}
            if keys & seen:
                continue  # the same table and columns again: a chart's labels
            seen |= keys
            yield from cells
