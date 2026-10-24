"""Checks on the RHS staff tables: vacant = S - P, shortfall = R - P.

"*" marks a surplus, NA or N App a missing part. All India is left out: it sums only
the gaps.
"""

import pandas as pd

from pdfexorcist import check

SURPLUS = {"*", "**"}


def _wide(df: pd.DataFrame) -> pd.DataFrame:
    """One row per table and State row, a column per printed value."""
    rows = df[df["sno"] != "total"]
    return rows.pivot_table(index=["table", "sno"], columns="col", values="value", aggfunc="first")


def _flag(df: pd.DataFrame, bad: pd.Series, cols: tuple[str, ...]) -> pd.Series:
    """Mark the cells of the failing (table, sno) rows in cols."""
    hit = {(*k, c) for k in bad[bad].index for c in cols}
    keys = zip(df["table"], df["sno"], df["col"], strict=True)
    return pd.Series([k in hit for k in keys], index=df.index)


def _gap(df: pd.DataFrame, gap: str, whole: str, part: str) -> pd.Series:
    """Fail a row where gap is not whole - part, or "*" where part does not exceed whole."""
    w = _wide(df)
    if not {gap, whole, part} <= set(w.columns):
        return pd.Series(False, index=df.index)
    g, a, b = (pd.to_numeric(w[c], errors="coerce") for c in (gap, whole, part))
    surplus = w[gap].isin(SURPLUS)
    bad = (g.notna() & a.notna() & b.notna() & (g != a - b)) | (
        surplus & a.notna() & b.notna() & (b < a)
    )
    return _flag(df, bad, (gap, whole, part))


@check("vacant = sanctioned - in position")
def vacant(df: pd.DataFrame) -> pd.Series:
    """Check each State's vacancies against its sanctioned and in-position posts."""
    return _gap(df, "vacant", "sanctioned", "in_position")


@check("shortfall = required - in position")
def shortfall(df: pd.DataFrame) -> pd.Series:
    """Check each State's shortfall against its required and in-position posts."""
    return _gap(df, "shortfall", "required", "in_position")


CHECKS = [vacant, shortfall]
