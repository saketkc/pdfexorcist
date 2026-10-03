"""NFHS-5 fact sheets."""

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
STATE_COLUMNS = ("nfhs5_urban", "nfhs5_rural", "nfhs5_total", "nfhs4_total")
DISTRICT_COLUMNS = ("nfhs5_total", "nfhs4_total")
N_INDICATORS = {"state": 131, "district": 104}
# Indicators that are not percentages: sex ratios (females per 1,000 males),
# State TFR, adolescent fertility rate (per 1,000 women), the three child
# mortality rates (per 1,000 live births), out-of-pocket cost of a delivery (Rs.)
NOT_PERCENT = {"state": {3, 4, 22, 24, 25, 26, 27, 47}, "district": {3, 4, 39}}
# State rates from a life table or summed over ages: TFR and NNMR, IMR, U5MR.
# Not ratios of sums, so their Total need not lie between Urban and Rural.
NOT_A_MEAN = {22, 25, 26, 27}
HEADER = re.compile(r"([A-Za-z][^#|]*?)\s*[-\u2013]\s*Key\s+Indicators", re.I)  # "-" or en dash
NUMBERED = re.compile(r"^(\d{1,3})\s*\.\s*(?=[^\d\s.])")  # "10. Households", "10.Households"
# a compendium's contents page ("Content  Page No.") has numbered rows too:
# "1. North Goa  7"
CONTENTS = re.compile(r"\bPage\s+No\b", re.I)
BARE = re.compile(r"^(\d{1,3})$")  # "85": the rest of the label read apart
# a value as printed: 12.3, 12, 1,037 (or 1037: Gondiya's NFHS-4 sex ratio), (45.6), *, na
PRINTED = re.compile(r"^(\(?\d[\d,]*(\.\d+)?\)?|\*|na)$")

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


def _layout(lines: list[list[Token]]) -> tuple[int, float, float] | None:
    """Return value-column count and label/table x boundaries for a page."""
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
    last = statistics.median(r[-1][0] for r in full)
    return ncols, first - tol, last + tol


def geography(lines: list[list[Token]]) -> str:
    """Return title geography or an empty string; join wrapped titles."""
    texts = [" ".join(t for _, t in toks) for toks in lines]
    for i, text in enumerate(texts):
        m = HEADER.search(text)
        if m:
            geo = m.group(1)
            if i and texts[i - 1].rstrip().endswith((",", " and")):
                geo = f"{texts[i - 1]} {geo}"
            return re.sub(r"\s+,", ",", re.sub(r"\s+", " ", geo)).strip()
    return ""


def _done(cur: list) -> tuple[int, list[str] | None]:
    """Return a number and values, or None unless ncols values were read."""
    no, acc, ncols = cur
    return no, [t for _, t in sorted(acc, key=lambda v: v[0])] if len(acc) == ncols else None


def _rows(lines: list[list[Token]], layout: tuple[int, float, float], level: str) -> Iterator:
    """Yield indicator numbers and printed values in page order."""
    ncols, left, right = layout
    cur: list | None = None  # [number, [(x, value)], ncols]
    held: list[Token] = []
    for toks in lines:
        toks = [(x, t) for x, t in toks if x <= right]
        label_toks = [(x, t) for x, t in toks if x < left or not is_value(t)]
        values = [(x, t) for x, t in toks if x >= left and is_value(t)]
        label = _label_start(label_toks)
        expected = cur[0] + 1 if cur else None
        m = NUMBERED.match(label)
        no = int(m.group(1)) if m else None
        if no is None and label:
            first = label.split()[0]
            if BARE.match(first) and int(first) == expected:
                no = expected  # the number read apart from its label
        if no is not None and (no > N_INDICATORS[level] or (cur and no <= cur[0])):
            no = None  # not a row number: a page number, a footnote, a repeat
        if no is not None:
            if cur is not None:
                yield _done(cur)
            cur, held = [no, held, ncols], []
        elif label:
            held = []
        if values and cur is not None and len(cur[1]) < ncols:
            cur[1].extend(values)
        elif values and not label and len(values) < ncols:
            held = values
    if cur is not None:
        yield _done(cur)


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield printed values keyed with level and geography."""
    for page_no, raw in pages:
        lines = [_tokens(cells) for cells in raw]
        lines = [t for t in lines if t]
        if any(CONTENTS.search(" ".join(t for _, t in toks)) for toks in lines):
            continue
        layout = _layout(lines)
        if layout is None:
            continue
        ncols = layout[0]
        level = "state" if ncols == len(STATE_COLUMNS) else "district"
        cols = STATE_COLUMNS if level == "state" else DISTRICT_COLUMNS[:ncols]
        geo = geography(lines)
        for no, values in _rows(lines, layout, level):
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
    s = printed.astype(str).str.strip("()").str.replace(",", "", regex=False)
    return pd.to_numeric(s, errors="coerce")


@check("percentage over 100")
def at_most_100(df: pd.DataFrame) -> pd.Series:
    """Flag percentages except indicators in NOT_PERCENT."""
    pct = pd.Series(
        [
            n not in NOT_PERCENT.get(lv, set())
            for lv, n in zip(df.level, df.indicator_no, strict=True)
        ],
        index=df.index,
        dtype=bool,
    )
    return pct & (number(df.value) > 100)


@check("NFHS-5 Total not between Urban and Rural")
def total_between_urban_and_rural(df: pd.DataFrame) -> pd.Series:
    """Flag numeric State totals outside Urban and Rural values; skip NOT_A_MEAN."""
    s = df[(df.level == "state") & ~df.indicator_no.isin(NOT_A_MEAN)]
    w = s.assign(v=number(s.value)).pivot_table(
        index=["page", "indicator_no"], columns="column", values="v", aggfunc="first"
    )
    need = ["nfhs5_urban", "nfhs5_rural", "nfhs5_total"]
    if not set(need) <= set(w.columns):
        return pd.Series(False, index=df.index)
    w = w[need].dropna()
    lo = w[["nfhs5_urban", "nfhs5_rural"]].min(axis=1)
    hi = w[["nfhs5_urban", "nfhs5_rural"]].max(axis=1)
    bad = set(w.index[(w.nfhs5_total < lo) | (w.nfhs5_total > hi)])
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
