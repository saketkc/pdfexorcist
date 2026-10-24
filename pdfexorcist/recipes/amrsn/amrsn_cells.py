"""One AMRSN cell's text as values ("172/542 (31.7)" -> r, n, pct), and the check on them."""

import re
from collections.abc import Iterator

import pandas as pd

BLANK = {"-", "–", "NA", "NT", "ND"}  # a value not given ("Rifampicin -")
RANK = re.compile(r"R\d+")  # 2023 Table 1.2 ranks each organism
# one entry of a cell: "erm A : 35/145 (24.1%)", "172/542 (31.7)", "2134 (18)"
PART = re.compile(
    r"(?P<pre>[A-Za-z][^:()]*?)\s*:"  # "vanC1/C2:" names an entry too
    r"|(?<![A-Za-z\d.])(?P<frac>\*?\d[\d,]*\s*/\s*\d[\d,]*)"
    r"|(?<![A-Za-z\d.])(?P<range>\d+(?:\.\d+)?-\d+(?:\.\d+)?)"
    r"|(?P<pct>\(\s*(?:-|\d+(?:\.\d+)?)\s*%?\s*\)|\d+(?:\.\d+)?\s*\(%\))"
    r"|(?<![A-Za-z\d.])(?P<int>\*?\d[\d,]*(?:\.\d+)?)(?![\d.])"
)


def _cell(texts: list[str]) -> Iterator[tuple[str, str, str]]:
    """(entry, field, value) of one cell: r and n of "r/n", pct, and the rank.

    A cell holds one entry, or several each named before a colon ("mecA: 102/105 (97.1%)").
    A count broken after its slash's digits ("101/10" "1") is joined.
    """
    rank = [t[1:] for t in texts if RANK.fullmatch(t)]
    text = " ".join(t for t in texts if not RANK.fullmatch(t) and t != "-")
    entries: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for m in PART.finditer(text):
        kind = m.lastgroup
        if kind == "pre":
            if cur:
                entries.append(cur)
            cur = {"entry": re.sub(r"\s+", "", m["pre"])}
        elif kind in ("frac", "int"):
            num = m[kind].lstrip("*").replace(",", "")
            if kind == "int" and "n" in cur and "pct" not in cur:
                cur["n"] += num  # the count's last digits, wrapped
                continue
            if "r" in cur:
                entries.append(cur)
                cur = {}
            cur["r"], *n = re.split(r"\s*/\s*", num)
            if n:
                cur["n"] = n[0]
        elif kind == "range":
            cur["range"] = m["range"]
        else:
            cur["pct"] = re.sub(r"[\s()%]", "", m["pct"])
    if cur:
        entries.append(cur)
    if not entries and (blank := [t for t in texts if t in BLANK]):
        yield "", "value", blank[0]  # "Rifampicin -": not tested
        return
    if not any(e.keys() - {"entry"} for e in entries) and text.strip():
        yield "", "text", re.sub(r"\s+", " ", text).strip()  # "Np", "ST85", "gyrA (S83F)"
        return
    for i, e in enumerate(entries):
        name = e.pop("entry", "" if len(entries) == 1 else str(i))
        if e.keys() == {"r"}:  # a number alone (45.8, a Range(%) of 100): not a count
            e = {"value": e["r"]}
        for field in ("r", "n", "pct", "range", "value"):
            if field in e:
                yield name, field, e[field]
    if rank:
        yield "", "rank", rank[0]


def pct_matches(df: pd.DataFrame) -> pd.Series:
    """Check each percentage against 100 * r / n, to the precision printed.

    Rounded and cut digits both pass (72/145 = 49.66 printed 49.6).
    """
    key = ["id", "col", "entry"]
    w = df.pivot_table(index=key, columns="field", values="value", aggfunc="first")
    if not {"r", "n", "pct"} <= set(w.columns):
        return pd.Series(False, index=df.index)
    r, n, pct = (pd.to_numeric(w[c], errors="coerce") for c in ("r", "n", "pct"))
    unit = 10.0 ** -w.pct.astype(str).str.extract(r"\.(\d+)$")[0].str.len().fillna(0)
    exact = 100 * r / n
    rounded = (pct - exact).abs() <= unit / 2 + 1e-9
    cut = (exact - pct >= -1e-9) & (exact - pct < unit + 1e-9)
    off = ~(rounded | cut) & (n > 0) & pct.notna()
    bad = set(off[off].index)
    return pd.Series([k in bad for k in zip(df.id, df.col, df.entry, strict=True)], index=df.index)
