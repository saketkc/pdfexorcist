"""Checks for the NHA recipe: State ratios and the key indicators against each other.

Each ratio is checked within the rounding of its printed figure; a failure marks the
ratio and its amounts.
"""

import re
from collections.abc import Callable

import pandas as pd

from pdfexorcist import check

KEY = ["table", "item", "col"]

# (ratio, numerator, denominator, scale, allowed gap): ratio = numerator / denominator * scale
# population is in crores (thousands for the UTs), so per capita = amount / population
RATIOS = [
    ("the_pct_gsdp", "the_cr", "gsdp_cr", 100, 0.06),
    ("ghe_pct_gsdp", "ghe_cr", "gsdp_cr", 100, 0.06),
    ("oope_pct_gsdp", "oope_cr", "gsdp_cr", 100, 0.06),
    ("ghe_pct_the", "ghe_cr", "the_cr", 100, 0.06),
    ("oope_pct_the", "oope_cr", "the_cr", 100, 0.06),
    ("ghe_pct_gge", "ghe_cr", "gge_cr", 100, 0.06),
    ("oope_pct_gge", "oope_cr", "gge_cr", 100, 0.06),
    ("the_pc", "the_cr", "population_cr", 1, 0.6),
    ("ghe_pc", "ghe_cr", "population_cr", 1, 0.6),
    ("oope_pc", "oope_cr", "population_cr", 1, 0.6),
    ("ghe_pc", "ghe_000", "population_000", 1, 0.6),
]

# key indicator rows, found by their printed name (the Sl. No. differs between reports)
ROWS = {
    "the_gdp": ("rounds", r"\(THE\) as percent of GDP"),
    "the_pc": ("rounds", r"per capita \(Rs\.\)(\*| at current)"),
    "che_the": ("rounds", r"\(CHE\) as percent of THE"),
    "ghe_the": ("rounds", r"\(GHE\) (as )?percent of THE"),
    "oope_the": ("rounds", r"\(OOPE\) as percent of THE"),
    "oope_che": ("che", r"\(OOPE\) as percent of CHE"),
    "k_the_gdp": ("key", r"\(THE\) as % GDP"),
    "k_the_pc": ("key", r"^THE per capita"),
    "k_che_the": ("key", r"\(CHE\) as % of THE"),
    "k_capital_the": ("key", r"^Capital Health Expenditure as % of THE"),
    "k_ghe_the": ("key", r"\(GHE\) as % of THE"),
    "k_ghe_pc": ("key", r"^Per capita Government Health"),
    "k_union_ghe": ("key", r"^Union Government Health Expenditure as % of GHE"),
    "k_state_ghe": ("key", r"^State ?Government Health Expenditure as % of GHE"),
    "k_oope_the": ("key", r"^OOPE as % of THE"),
    "k_oope_pc": ("key", r"^Per capita OOPE"),
}


def _mark(df: pd.DataFrame, bad: pd.DataFrame) -> pd.Series:
    """True for the cells of df that bad (indexed by table and item, columns col) flags."""
    hit = bad.stack()
    at = pd.MultiIndex.from_frame(df[KEY]).isin(hit[hit].index)
    return pd.Series(at, index=df.index)


def _wide(df: pd.DataFrame) -> pd.DataFrame:
    v = pd.to_numeric(df.value, errors="coerce")
    return df.assign(v=v).pivot_table(
        index=["table", "item"], columns="col", values="v", aggfunc="first"
    )


@check("State ratio does not match its amounts")
def state_ratios(df: pd.DataFrame) -> pd.Series:
    """Each % of GSDP, THE or GGE and each per capita value against the amounts it divides."""
    sub = df[df.table.isin(["states", "states_ghe", "uts_ghe"])]
    if sub.empty:
        return pd.Series(False, index=df.index)
    w = _wide(sub)
    bad = pd.DataFrame(False, index=w.index, columns=w.columns)
    for out, num, den, scale, tol in RATIOS:
        if {out, num, den} <= set(w.columns):
            off = (w[num] / w[den] * scale - w[out]).abs() > tol  # NaN: not flagged
            for c in (out, num, den):
                bad[c] |= off
    return _mark(df, bad)


def _rows(df: pd.DataFrame) -> dict[str, tuple[str, str]]:
    """The (table, item) of each named indicator row found in df."""
    labels = df.drop_duplicates(["table", "item"]).set_index(["table", "item"])["label"]
    found = {}
    for name, (table, pattern) in ROWS.items():
        for (t, item), label in labels.items():
            if t == table and re.search(pattern, " ".join(str(label).split()), re.I):
                found[name] = (t, item)
                break
    return found


# (rows, gap of their values, allowed gap); None: the gap of a 0.1 share times per capita THE
RULES: list[tuple[tuple[str, ...], Callable[..., pd.Series], float | None]] = [
    (("k_union_ghe", "k_state_ghe"), lambda u, s: u + s - 100, 0.11),
    (("k_che_the", "k_capital_the"), lambda c, k: c + k - 100, 0.11),
    (("the_gdp", "k_the_gdp"), lambda a, b: a - b, 0.051),
    (("the_pc", "k_the_pc"), lambda a, b: a - b, 0),
    (("che_the", "k_che_the"), lambda a, b: a - b, 0.051),
    (("ghe_the", "k_ghe_the"), lambda a, b: a - b, 0.051),
    (("oope_the", "k_oope_the"), lambda a, b: a - b, 0.051),
    (("oope_che", "k_oope_the", "k_che_the"), lambda c, o, t: c - o / t * 100, 0.15),
    (("k_ghe_pc", "k_the_pc", "k_ghe_the"), lambda p, t, s: p - t * s / 100, None),
    (("k_oope_pc", "k_the_pc", "k_oope_the"), lambda p, t, s: p - t * s / 100, None),
]


@check("key indicators do not agree")
def key_indicators(df: pd.DataFrame) -> pd.Series:
    """Shares that add to 100, one indicator printed in two tables, per capita = THE x share."""
    sub = df[df.table.isin(["rounds", "che", "key"])]
    if sub.empty:
        return pd.Series(False, index=df.index)
    w, at = _wide(sub), _rows(sub)
    bad = pd.DataFrame(False, index=w.index, columns=w.columns)
    for names, gap, tol in RULES:
        if not all(n in at for n in names):
            continue
        vals = [pd.Series(w.loc[at[n]]) for n in names]
        limit = vals[1] * 0.00051 + 1 if tol is None else tol
        off = gap(*vals).abs() > limit
        for n in names:
            bad.loc[at[n]] |= off.fillna(False)
    return _mark(df, bad)


CHECKS = [state_ratios, key_indicators]
