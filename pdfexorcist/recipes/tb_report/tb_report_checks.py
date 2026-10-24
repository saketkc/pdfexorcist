"""Checks on the agreed cells of the TB Report annexures."""

import pandas as pd
from tb_report_names import INDIA

KEY = ["table", "state", "col"]


def _wide(df: pd.DataFrame) -> pd.DataFrame:
    """value and pct side by side, one row per table, State and column, as numbers."""
    w = df.pivot_table(index=KEY, columns="field", values="value", aggfunc="first")
    out = pd.DataFrame(index=w.index)
    for field in ("value", "pct"):
        text = w[field] if field in w else pd.Series(None, index=w.index, dtype=object)
        out[field] = pd.to_numeric(text, errors="coerce")
        out[f"{field}_text"] = text
    out["kind"] = df.groupby(KEY)["kind"].first()
    return out


def _denominators(w: pd.DataFrame) -> pd.Series:
    """What each percentage is a share of, by the table's kind; NaN where it is not printed.

    * outcome: the nearest column to its left without a %, the patients in the cohort.
    * notification: the target three columns to its left.
    * pregnancy: the patients identified (columns 3-5) as a share of those screened (0-2).
    """
    out = pd.Series(float("nan"), index=w.index)
    for table, t in w.groupby(level="table"):
        kind = t["kind"].iloc[0]
        with_pct = set(t[t["pct"].notna()].index.get_level_values("col"))
        cols = sorted(set(t.index.get_level_values("col")), key=int)
        if kind == "outcome":
            plain = [c for c in cols if c not in with_pct]
            pairs = {c: max((p for p in plain if int(p) < int(c)), key=int, default=None)
                     for c in cols if c in with_pct}  # fmt: skip
        elif kind in ("notification", "pregnancy"):
            pairs = {c: str(int(c) - 3) for c in cols if int(c) >= 3}
        else:
            continue
        value = t["value"].droplevel("table")
        for state, c in t.index.droplevel("table"):
            b = pairs.get(c)
            if b is not None and (state, b) in value.index:
                out[(table, state, c)] = value[(state, b)]
    return out


def _group_sums(df: pd.DataFrame, w: pd.DataFrame) -> pd.Series:
    """For characteristics tables: the sum of the values under each column's top heading."""
    heads = df.groupby(KEY)["column"].first().str.split(" / ").str[0]
    sub = w[w["kind"] == "characteristics"]
    if sub.empty:
        return pd.Series(dtype=float)
    group = heads.loc[sub.index]
    keys = [sub.index.get_level_values("table"), sub.index.get_level_values("state"), group]
    sums = sub["value"].groupby(keys).transform("sum")
    return pd.Series(sums.to_numpy(), index=sub.index)


def pct_matches(df: pd.DataFrame) -> pd.Series:
    """Check each percentage against 100 * value / its denominator, to the precision printed.

    Rounded and cut digits both pass. A pct whose denominator is not in the table is skipped.
    """
    if "kind" not in df or df.empty:
        return pd.Series(False, index=df.index)
    df = df.assign(col=df.col.astype(str))  # numbers after the vote; the keys below are text
    w = _wide(df)
    base = _denominators(w)
    groups = _group_sums(df, w)
    base.loc[groups.index] = groups
    unit = 10.0 ** -w["pct_text"].astype(str).str.extract(r"\.(\d+)$")[0].str.len().fillna(0)
    exact = 100 * w["value"] / base
    rounded = (w["pct"] - exact).abs() <= unit / 2 + 1e-9
    cut = (exact - w["pct"] >= -1e-9) & (exact - w["pct"] < unit + 1e-9)
    off = ~(rounded | cut) & (base > 0) & w["pct"].notna() & exact.notna()
    bad = set(off[off].index)
    keys = zip(df.table, df.state, df.col, strict=True)
    return pd.Series([k in bad and f == "pct" for k, f in zip(keys, df.field, strict=True)],
                     index=df.index)  # fmt: skip


def _counts(df: pd.DataFrame) -> pd.DataFrame:
    """The whole-number values: no decimals (rates), no NA or "-"."""
    v = df[(df.field == "value") & df.value.astype(str).str.fullmatch(r"\d+")]
    return v.assign(n=v.value.astype(int))


def states_sum_to_india(df: pd.DataFrame) -> pd.Series:
    """Check that the States add up to the India row, in each column of whole numbers.

    Only columns where every State row is a whole number are checked. The India cell fails.
    """
    fails = pd.Series(False, index=df.index)
    if df.empty:
        return fails
    v = _counts(df)
    values = df[(df.field == "value") & (df.state != INDIA)]
    printed = values.groupby(["table", "col"]).size()  # State rows, whole numbers or not
    for key, g in v.groupby(["table", "col"]):
        india = g[g.state == INDIA]
        states = g[g.state != INDIA]
        if india.empty or len(states) != printed.get(key, 0):
            continue
        if states.n.sum() != india.n.iloc[0]:
            fails[india.index] = True
    return fails


def parts_sum_to_total(df: pd.DataFrame) -> pd.Series:
    """Check that Public + Private = Total under each heading that prints all three."""
    fails = pd.Series(False, index=df.index)
    v = _counts(df)
    if v.empty:
        return fails
    head = v.column.str.extract(r"^(.*?)\s*/\s*(Public|Private|Total)$")
    v = v.assign(group=head[0], part=head[1]).dropna(subset=["part"])
    for _, g in v.groupby(["table", "state", "group"]):
        parts = dict(zip(g.part, g.n, strict=True))
        whole = {"Public", "Private", "Total"} <= parts.keys()
        if whole and parts["Public"] + parts["Private"] != parts["Total"]:
            fails[g[g.part == "Total"].index] = True
    return fails
