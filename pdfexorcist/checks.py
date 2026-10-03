"""Checks on extracted values."""

from collections.abc import Callable, Iterable, Sequence

import pandas as pd

Check = Callable[[pd.DataFrame], pd.Series]


def check(name: str) -> Callable[[Check], Check]:
    """Set a validation check's display name."""

    def deco(fn: Check) -> Check:
        fn.__name__ = name
        return fn

    return deco


FLOAT_NOISE = 1e-9  # relative; far below any printed rounding


def total_check(
    col: str,
    total: str,
    parts: Sequence[str] | None = None,
    by: Sequence[str] = (),
    value: str = "value",
    op: str = "==",
    rel_tol: float = 0.0,
    where: str | None = None,
    abs_tol: float = 0.0,
    name: str | None = None,
    missing: str = "skip",
) -> Check:
    """A check that each group's total row matches the sum of its parts.

    Args:
        col: Column naming totals and parts (e.g. "Sex", "State").
        total: The col value of the total row (e.g. "T").
        parts: Col values that add up to it; default every other value in the group.
        by: Columns identifying one group.
        value: The numeric column.
        op: "==", ">=" (total may exceed its parts) or "<=".
        rel_tol: Allowed relative gap, e.g. 0.02.
        where: DataFrame.query string limiting the rows checked.
        abs_tol: Allowed absolute gap, e.g. 0.05 for rounded decimals.
        name: What validate() writes into failed; default generated.
        missing: "skip" leaves a group missing its total or a part unjudged;
            "fail" fails a group whose total is present but a part is missing.
    """
    if op not in ("==", ">=", "<="):
        raise ValueError(f"op must be ==, >= or <=, got {op!r}")
    if missing not in ("skip", "fail"):
        raise ValueError(f"missing must be 'skip' or 'fail', got {missing!r}")

    def fn(full: pd.DataFrame) -> pd.Series:
        df = full.query(where) if where else full
        v = pd.to_numeric(df[value], errors="coerce")
        is_total = df[col] == total
        is_part = df[col].isin(parts) if parts is not None else ~is_total
        keys = [df[b] for b in by] if by else [pd.Series(0, index=df.index)]
        tot = v.where(is_total).groupby(keys).transform("max")
        s = v.where(is_part).groupby(keys).transform("sum", min_count=1)
        incomplete = pd.Series(False, index=df.index)
        if parts is not None:
            present = df[col].where(is_part & v.notna()).groupby(keys).transform("nunique")
            incomplete = present < len(set(parts))
            s = s.where(~incomplete)
        # + float noise: decimals summed in binary miss by ~1e-15 (65.3 + -4.0 != 61.3)
        slack = tot.abs() * rel_tol + abs_tol + tot.abs().clip(lower=1) * FLOAT_NOISE
        gap = tot - s
        ok = {"==": gap.abs() <= slack, ">=": gap >= -slack, "<=": gap <= slack}[op]
        judged = tot.notna() & s.notna() & (is_total | is_part)
        bad = judged & ~ok
        if missing == "fail":
            bad |= tot.notna() & incomplete & (is_total | is_part)
        return bad.reindex(full.index, fill_value=False)

    fn.__name__ = name or f"{total} {op} sum of {col}" + (
        f" (±{rel_tol:.0%})" if rel_tol else ""
    ) + (f" [{where}]" if where else "")
    return fn


def validate(df: pd.DataFrame, checks: Iterable[Check]) -> pd.DataFrame:
    """Add semicolon-separated failed check names to each row."""
    out = df.copy()
    failed = pd.Series("", index=df.index)
    for fn in checks:
        bad = fn(out).reindex(df.index, fill_value=False).astype(bool)
        failed = failed.where(~bad, failed + fn.__name__ + "; ")
    out["failed"] = failed.str.removesuffix("; ")
    return out
