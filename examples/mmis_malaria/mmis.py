"""NCVBDC Monthly Malaria Situation (MMIS) report: the tables under the trend graphs."""

import re
from collections.abc import Iterable, Iterator

import pandas as pd

from pdfexorcist import check
from pdfexorcist.rows import Page, is_value

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
KEY = ["page", "block", "series", "month"]
TITLE = re.compile(r"GRAPH (\d+): MONTH WISE TREND OF (\w+) IN (.+)$")
ROW = re.compile(r"^(BSE|TPC|TPR|PF) (Current Year|3 Year Average)$")
SERIES = {"Current Year": "current", "3 Year Average": "avg3"}


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield values keyed by graph position, series and month, with the graph's title.

    The title ("GRAPH 2: MONTH WISE TREND OF TPC IN CHHATTISGARH") gives area and
    indicator as extra columns: camelot reads the table without it, so keying on
    them would leave camelot out of every vote. A graph is counted by its month row.
    """
    for page_no, lines in pages:
        block, title, graph = 0, None, None
        for cells in lines:
            toks = [t for _, s in cells for t in s.split()]
            text = " ".join(toks)
            if m := TITLE.search(text):
                title = m
            elif toks == MONTHS:
                block, graph, title = block + 1, title, None  # a title belongs to one graph
            elif block:
                i = len(toks)
                while i and is_value(toks[i - 1]):
                    i -= 1
                row = ROW.match(" ".join(toks[:i]))
                if not row or not 0 < len(toks) - i <= 12:
                    continue
                # values sit under Jan, Feb, ...; only trailing months are ever missing
                for month, v in zip(MONTHS, toks[i:], strict=False):
                    yield {
                        "page": page_no,
                        "block": block,
                        "series": SERIES[row.group(2)],
                        "month": month,
                        "value": v,
                        "area": graph and graph.group(3).strip(),
                        "indicator": graph and graph.group(2),
                        "printed": row.group(1),
                        "graph": graph and graph.group(0),
                    }


def _wide(df: pd.DataFrame) -> pd.DataFrame:
    """Indicators as columns, one row per area, series and month."""
    v = pd.to_numeric(df.value, errors="coerce")
    return df.assign(v=v).pivot_table(
        index=["area", "series", "month"], columns="indicator", values="v", aggfunc="first"
    )


def _flag(df: pd.DataFrame, bad: pd.Series, cols: Iterable[str]) -> pd.Series:
    """Mark the cells of bad (area, series, month) rows in the given indicators."""
    hit = {(*k, c) for k in bad[bad].index for c in cols}
    keys = zip(df.area, df.series, df.month, df.indicator, strict=True)
    return pd.Series([k in hit for k in keys], index=df.index)


@check("TPR = 100 * TPC / BSE")
def tpr(df: pd.DataFrame) -> pd.Series:
    """Check each month's positivity rate against its cases and slides, to 2 decimals.

    A 3-year average is printed as a whole number, so its TPC and BSE may each be
    off by 0.5: Meghalaya's August prints 0.39 for 100 * 160 / 41562 = 0.385.
    """
    w = _wide(df)
    if not {"TPR", "TPC", "BSE"} <= set(w.columns):
        return pd.Series(False, index=df.index)
    d = pd.Series(w.index.get_level_values("series") == "avg3", index=w.index) * 0.5
    lo, hi = 100 * (w.TPC - d) / (w.BSE + d), 100 * (w.TPC + d) / (w.BSE - d)
    half = 0.005 + 1e-9  # TPR is printed to 2 decimals
    bad = ~w.TPR.between(lo - half, hi + half)
    return _flag(df, bad, ("TPR", "TPC", "BSE"))


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
    return df.printed.notna() & df.indicator.notna() & (df.printed != df.indicator)
