"""NCVBDC Monthly Malaria Situation (MMIS) report: the tables under the trend graphs."""

import re
from collections.abc import Iterable, Iterator
from itertools import pairwise

import pandas as pd

from pdfexorcist import check
from pdfexorcist.cells import Box, token_boxes
from pdfexorcist.rows import Page, _column, is_value

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
KEY = ["page", "block", "series", "month"]
TITLE = re.compile(r"GRAPH (\d+): MONTH WISE TREND OF (\w+) IN (.+)$")
# to 2024: BSE/TPC/TPR/PF, current and 3-year average; 2025 on: Tested/Positive/TPR/Pf and last year
ROW = re.compile(  # searched: OCR reads the legend's line sample as stray letters before it
    r"(?<![A-Za-z])(BSE|TPC|TPR|PF|Tested|Positive|Pf) "
    r"(Current Year|Last Year|3 Year Average|Avg Last 3 Years)$"
)
SERIES = {
    "Current Year": "current",
    "Last Year": "last_year",
    "3 Year Average": "avg3",
    "Avg Last 3 Years": "avg3",
}
ROLE = {"TESTED": "BSE", "POSITIVE": "TPC"}  # same counts under the 2025 names
ROLE_WORDS = {"BSE", "TPC", "TPR", "PF", *ROLE}  # y-axis titles
X_TOL = 0.25  # of the month spacing
AREA_TAIL = re.compile(r"^[A-Z][A-Z&.()/ -]*$")


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield values keyed by graph position, series and month, with the graph's title.

    The title ("GRAPH 2: MONTH WISE TREND OF TPC IN CHHATTISGARH") gives area and
    indicator as extra columns: camelot reads the table without it, so keying on
    them would leave camelot out of every vote. A graph is counted by its month row.
    """
    for page_no, lines in pages:
        block, title, graph, heads, wrapped = 0, None, None, None, False
        for cells in lines:
            toks = list(token_boxes(cells))
            words = [t for _, t, _ in toks]
            text = " ".join(words)
            if m := TITLE.search(text):
                title, wrapped = m, True
                continue
            if wrapped and AREA_TAIL.match(text) and text.upper() not in ROLE_WORDS:
                title = TITLE.search(f"{title.group(0)} {text}")  # a title wrapped onto 2 lines
            wrapped = False
            if _is_month_row(words):
                block, graph, title = block + 1, title, None  # a title belongs to one graph
                heads = _centres(toks)
            elif block:
                i = len(words)
                while i and is_value(words[i - 1]):
                    i -= 1
                row = ROW.search(" ".join(words[:i]))
                if not row or not 0 < len(words) - i <= 12:
                    continue
                for col, v in _place(toks[i:], heads):
                    yield {
                        "page": page_no,
                        "block": block,
                        "series": SERIES[row.group(2)],
                        "month": MONTHS[col],
                        "value": v,
                        "area": graph and graph.group(3).strip(),
                        "indicator": graph and graph.group(2),
                        "printed": row.group(1),
                        "graph": graph and graph.group(0),
                    }


def _is_month_row(words: list[str]) -> bool:
    """Jan ... Dec, allowing OCR slips ("Now", "Dec:") in up to two of them."""
    if len(words) != 12:
        return False
    return sum(w.strip(".:,;").title() == m for w, m in zip(words, MONTHS, strict=True)) >= 10


def _centres(toks: list[tuple[float, str, Box | None]]) -> list[float] | None:
    """Each token's x-centre (its x without a box); None unless all differ."""
    xs = [(b[0] + b[2]) / 2 if b else x for x, _, b in toks]
    return xs if len(set(xs)) == len(xs) else None


def _place(vals: list[tuple[float, str, Box | None]], heads: list[float] | None) -> list:
    """(month index, value) for one row, by x where each value sits under its own month.

    A month can be blank mid-row (Manipur's April and May 2023), and OCR drops values,
    so order alone shifts the rest. Where x is unclear (pdftotext's character columns
    drift; tokens sharing a cell share x) values go by order: Jan, Feb, ...
    """
    words = [t for _, t, _ in vals]
    xs = _centres(vals)
    if heads is None or xs is None:
        return list(enumerate(words))
    within = X_TOL * min(b - a for a, b in pairwise(heads))
    cols = [_column(x, heads, within) for x in xs]
    if None in cols or len(set(cols)) < len(cols):
        return list(enumerate(words))
    return list(zip(cols, words, strict=True))


def _role(df: pd.DataFrame) -> pd.Series:
    """Each indicator under its pre-2025 name."""
    return df.indicator.str.upper().replace(ROLE)


def _wide(df: pd.DataFrame) -> pd.DataFrame:
    """Indicators as columns, one row per area, series and month."""
    v = pd.to_numeric(df.value, errors="coerce")
    return df.assign(v=v, indicator=_role(df)).pivot_table(
        index=["area", "series", "month"], columns="indicator", values="v", aggfunc="first"
    )


def _flag(df: pd.DataFrame, bad: pd.Series, cols: Iterable[str]) -> pd.Series:
    """Mark the cells of bad (area, series, month) rows in the given indicators."""
    hit = {(*k, c) for k in bad[bad].index for c in cols}
    keys = zip(df.area, df.series, df.month, _role(df), strict=True)
    return pd.Series([k in hit for k in keys], index=df.index)


@check("TPR = 100 * TPC / BSE")
def tpr(df: pd.DataFrame) -> pd.Series:
    """Check each month's positivity rate against its cases and slides, to 2 decimals.

    A 3-year average is printed as a whole number, so its TPC and BSE may each be
    off by 0.5: Meghalaya's August prints 0.39 for 100 * 160 / 41562 = 0.385.
    From 2025 (Tested/Positive) the average TPR is not from the printed averages
    (Jharkhand's December 2025 prints 0.95 for 100 * 5479 / 532187 = 1.03), so
    those rows are left out.
    """
    renamed = df.area.isin(df.area[df.indicator.str.upper().isin(ROLE)])
    kept = df[~(renamed & (df.series == "avg3"))]
    w = _wide(kept)
    if not {"TPR", "TPC", "BSE"} <= set(w.columns):
        return pd.Series(False, index=df.index)
    d = pd.Series(w.index.get_level_values("series") == "avg3", index=w.index) * 0.5
    lo = 100 * (w.TPC - d) / (w.BSE + d)
    # an average printed as 0 slides may be 0.33 (Ladakh's: 0 slides, 0 cases, TPR 100.00)
    hi = (100 * (w.TPC + d) / (w.BSE - d)).where(d < w.BSE, float("inf"))
    half = 0.005 + 1e-9  # TPR is printed to 2 decimals
    bad = ~w.TPR.between(lo - half, hi + half)
    return _flag(kept, bad, ("TPR", "TPC", "BSE")).reindex(df.index, fill_value=False)


@check("PF <= TPC")
def pf_within_tpc(df: pd.DataFrame) -> pd.Series:
    """Check falciparum cases do not exceed all positive cases."""
    w = _wide(df)
    if not {"PF", "TPC"} <= set(w.columns):
        return pd.Series(False, index=df.index)
    return _flag(df, w.PF > w.TPC, ("PF", "TPC"))


@check("row label matches the graph title")
def label_matches_title(df: pd.DataFrame) -> pd.Series:
    """Flag a table whose rows name another indicator than its graph."""
    printed, indicator = df.printed.str.upper(), df.indicator.str.upper()
    return printed.notna() & indicator.notna() & (printed != indicator)
