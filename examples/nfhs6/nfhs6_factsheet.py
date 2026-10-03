"""NFHS-6 fact sheets."""

import re
import statistics
from collections import Counter
from collections.abc import Iterable, Iterator

import pandas as pd

from pdfexorcist import check
from pdfexorcist.cells import token_boxes
from pdfexorcist.checks import Check
from pdfexorcist.rows import Page, is_value

KEY = ["page", "indicator_no", "column"]
STATE_COLUMNS = ("nfhs6_urban", "nfhs6_rural", "nfhs6_total", "nfhs5_total")
DISTRICT_COLUMNS = ("nfhs6_total", "nfhs5_total")
N_INDICATORS = {"state": 101, "district": 93}
TFR = 18  # state sheet: Total fertility rate (children per woman), the one non-%
HEADER = re.compile(r"([A-Za-z][^#|]*?)\s*-\s*Key\s+Indicators", re.I)
NUMBERED = re.compile(r"^(\d{1,3})\s*\.\s*(?=[^\d\s.])")  # "10. Households", "10.Households"
BARE = re.compile(r"^(\d{1,3})$")  # "85": the rest of the label is graphics
# a value as printed: 12.3, 12, (45.6), * (OCR engines may add a stray space or bar)
PRINTED = re.compile(r"^(\(?\d+(\.\d+)?\)?|\*)$")

Token = tuple[float, str]


def _tokens(cells: list) -> list[Token]:
    """Yield each whitespace token with its cell's x position."""
    return [(x, t) for x, t, _ in token_boxes(sorted(cells, key=lambda c: c[0]))]


def _trailing_values(toks: list[Token]) -> list[Token]:
    """Return trailing value tokens."""
    i = len(toks)
    while i and is_value(toks[i - 1][1]):
        i -= 1
    return toks[i:]


def _label_start(toks: list[Token]) -> str:
    return " ".join(t for _, t in toks).lstrip("#*|- ").strip()


def _layout(lines: list[list[Token]]) -> tuple[int, float] | None:
    """Return value-column count and label boundary for a page."""
    runs = [_trailing_values(t) for t in lines if NUMBERED.match(_label_start(t))]
    counts = Counter(len(r) for r in runs if 1 <= len(r) <= len(STATE_COLUMNS))
    if not counts:
        return None
    ncols = counts.most_common(1)[0][0]
    if ncols == 3:
        return None  # no such layout
    full = [r for r in runs if len(r) == ncols]
    first = statistics.median(r[0][0] for r in full)
    gaps = [
        g
        for i in range(1, ncols)
        if (
            g := statistics.median(r[i][0] for r in full)
            - statistics.median(r[i - 1][0] for r in full)
        )
        > 0
    ]
    # A lone column: labels run close to it, so allow only 5% of its x.
    tol = min(gaps) / 2 if gaps else 0.05 * abs(first) or 0.5
    return ncols, first - tol


def geography(lines: Iterable[list[Token]]) -> str:
    """Return title geography or an empty string."""
    for toks in lines:
        m = HEADER.search(" ".join(t for _, t in toks))
        if m:
            return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


def _done(cur: list) -> tuple[int, list[str] | None]:
    """Return a number and values, or None unless ncols values were read."""
    no, acc, ncols = cur
    return no, [t for _, t in sorted(acc, key=lambda v: v[0])] if len(acc) == ncols else None


def _rows(lines: list[list[Token]], ncols: int, left: float, level: str) -> Iterator:
    """Yield indicator numbers and printed values in page order."""
    cur: list | None = None  # [number, [(x, value)], ncols]
    for toks in lines:
        label_toks = [(x, t) for x, t in toks if x < left or not is_value(t)]
        values = [(x, t) for x, t in toks if x >= left and is_value(t)]
        label = _label_start(label_toks)
        expected = cur[0] + 1 if cur else None
        m = NUMBERED.match(label)
        no = int(m.group(1)) if m else None
        if no is None and label:
            first = label.split()[0]
            if BARE.match(first) and int(first) == expected:
                no = expected  # label drawn as graphics: only its number is text
        if no is not None and (no > N_INDICATORS[level] or (cur and no <= cur[0])):
            no = None  # not a row number: a page number, a footnote, a repeat
        if no is not None:
            if cur is not None:
                yield _done(cur)
            cur = [no, [], ncols]
        if values and cur is not None and len(cur[1]) < ncols:
            cur[1].extend(values)
    if cur is not None:
        yield _done(cur)


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield printed values keyed with level and geography."""
    for page_no, raw in pages:
        lines = [_tokens(cells) for cells in raw]
        lines = [t for t in lines if t]
        layout = _layout(lines)
        if layout is None:
            continue
        ncols, left = layout
        level = "state" if ncols == len(STATE_COLUMNS) else "district"
        cols = STATE_COLUMNS if level == "state" else DISTRICT_COLUMNS[:ncols]
        geo = geography(lines)
        for no, values in _rows(lines, ncols, left, level):
            for col, v in zip(cols, values or [], strict=False):
                if PRINTED.match(v):
                    yield {
                        "page": page_no,
                        "indicator_no": no,
                        "column": col,
                        "level": level,
                        "geo": geo,
                        "value": v,
                    }


def number(printed: pd.Series) -> pd.Series:
    """Convert printed numbers and placeholders to floats or NaN."""
    return pd.to_numeric(printed.astype(str).str.strip("()"), errors="coerce")


@check("percentage over 100")
def at_most_100(df: pd.DataFrame) -> pd.Series:
    """Flag percentages except State total fertility rates."""
    pct = ~((df.level == "state") & (df.indicator_no == TFR))
    return pct & (number(df.value) > 100)


@check("NFHS-6 Total not between Urban and Rural")
def total_between_urban_and_rural(df: pd.DataFrame) -> pd.Series:
    """Flag numeric State totals outside Urban and Rural values; skip TFR."""
    s = df[(df.level == "state") & (df.indicator_no != TFR)]
    w = s.assign(v=number(s.value)).pivot_table(
        index=["page", "indicator_no"], columns="column", values="v", aggfunc="first"
    )
    need = ["nfhs6_urban", "nfhs6_rural", "nfhs6_total"]
    if not set(need) <= set(w.columns):
        return pd.Series(False, index=df.index)
    w = w[need].dropna()
    lo = w[["nfhs6_urban", "nfhs6_rural"]].min(axis=1)
    hi = w[["nfhs6_urban", "nfhs6_rural"]].max(axis=1)
    bad = set(w.index[(w.nfhs6_total < lo) | (w.nfhs6_total > hi)])
    return pd.Series(
        [
            (p, n) in bad and c in need
            for p, n, c in zip(df.page, df.indicator_no, df.column, strict=True)
        ],
        index=df.index,
    )


def checks() -> list[Check]:
    """Return checks for printed fact-sheet values."""
    return [at_most_100, total_between_urban_and_rural]
