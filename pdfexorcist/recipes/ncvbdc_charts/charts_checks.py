"""Checks on the chart values of NCVBDC's Monthly Malaria Situation report."""

from collections.abc import Iterable

import pandas as pd

from pdfexorcist import check

KEY = ["area", "which", "category"]


def _parts(df: pd.DataFrame) -> pd.DataFrame:
    """df with indicator and area from the chart title, and which series (current, avg3 or NaN)."""
    m = df.title.str.extract(r"TREND OF (\w+) IN (.+?)\s*$")
    which = df.series.map({"Current Year": "current", "Average 3 years": "avg3"})  # [charts] names
    return df.assign(indicator=m[0], area=m[1], which=which)


def _wide(df: pd.DataFrame) -> pd.DataFrame:
    """Indicators as columns, one row per area, series and month."""
    if not {"title", "series", "category"} <= set(df.columns):  # no chart read
        return pd.DataFrame()
    return _parts(df).pivot_table(index=KEY, columns="indicator", values="value", aggfunc="first")


def _flag(df: pd.DataFrame, bad: pd.Series, cols: Iterable[str]) -> pd.Series:
    """Mark the values of bad (area, which, month) rows in the given indicators."""
    hit = {(*k, c) for k in bad[bad].index for c in cols}
    d = _parts(df)
    keys = zip(d.area, d.which, d.category, d.indicator, strict=True)
    return pd.Series([k in hit for k in keys], index=df.index)


@check("TPR = 100 * TPC / BSE")
def tpr(df: pd.DataFrame) -> pd.Series:
    """Check each month's positivity rate against its cases and slides, to 2 decimals.

    A 3-year average is printed as a whole number, so its TPC and BSE may each be off by 0.5.
    """
    w = _wide(df)
    if not {"TPR", "TPC", "BSE"} <= set(w.columns):
        return pd.Series(False, index=df.index)
    d = pd.Series(w.index.get_level_values("which") == "avg3", index=w.index) * 0.5
    lo, hi = 100 * (w.TPC - d) / (w.BSE + d), 100 * (w.TPC + d) / (w.BSE - d)
    half = 0.005 + 1e-9  # TPR is printed to 2 decimals
    bad = w.TPR.notna() & w.TPC.notna() & w.BSE.notna() & ~w.TPR.between(lo - half, hi + half)
    return _flag(df, bad, ("TPR", "TPC", "BSE"))


@check("PF <= TPC")
def pf_within_tpc(df: pd.DataFrame) -> pd.Series:
    """Check falciparum cases do not exceed all positive cases."""
    w = _wide(df)
    if not {"PF", "TPC"} <= set(w.columns):
        return pd.Series(False, index=df.index)
    return _flag(df, w.PF > w.TPC, ("PF", "TPC"))
