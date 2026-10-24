"""Checks for the NACO State/UT tables: totals and estimate intervals."""

import re

import pandas as pd
from naco_states import TOTAL

from pdfexorcist import check
from pdfexorcist.checks import Check

BOUND = re.compile(r"_(lower|upper)$")


def number(printed: pd.Series) -> pd.Series:
    """Printed values as floats; "≥95" and ">=95" are 95, a placeholder is NaN."""
    return pd.to_numeric(printed.astype(str).str.lstrip("+≥≤<>="), errors="coerce")


def _decimals(printed: pd.Series) -> int:
    return int(printed.astype(str).str.extract(r"\.(\d+)$")[0].str.len().fillna(0).max())


@check("States/UTs = India")
def states_add_up(df: pd.DataFrame) -> pd.Series:
    """Fail a column whose States/UTs do not add up to the India row.

    Only count columns are checked (India above 100 and at least every State/UT). Each
    value may be off by half its last printed digit. Bounds are not summed.
    """
    bad = pd.Series(False, index=df.index)
    cols = df[~df["col"].astype(str).str.contains(BOUND)]
    for _, g in cols.groupby(["table", "col"]):
        v = number(g["value"])
        is_total = g["state"] == TOTAL
        if is_total.sum() != 1 or (~is_total).sum() < 3:
            continue
        total, parts = v[is_total].iloc[0], v[~is_total]
        if not total > 100 or parts.isna().all() or total < parts.max():
            continue
        places = _decimals(g["value"])
        slack = 0.5 * 10**-places * len(parts)
        slack += 1e-9 * total
        if abs(parts.sum() - total) > slack:
            bad[g.index] = True
    return bad


@check("lower <= estimate <= upper")
def inside_interval(df: pd.DataFrame) -> pd.Series:
    """Fail an estimate that is not inside its printed interval."""
    col = df["col"].astype(str)
    base = col.str.replace(BOUND, "", regex=True)
    part = col.str.extract(BOUND)[0].fillna("value")
    w = df.assign(base=base, part=part, v=number(df["value"]))
    wide = w.pivot_table(
        index=["table", "state", "base"], columns="part", values="v", aggfunc="first"
    )
    if not {"lower", "upper", "value"} <= set(wide.columns):
        return pd.Series(False, index=df.index)
    wide = wide.dropna(subset=["lower", "upper", "value"])
    out = (wide["lower"] > wide["value"]) | (wide["value"] > wide["upper"])
    bad = set(wide.index[out])
    keys = zip(df["table"], df["state"], base, strict=True)
    return pd.Series([k in bad for k in keys], index=df.index)


def checks() -> list[Check]:
    """The recipe's checks."""
    return [states_add_up, inside_interval]
