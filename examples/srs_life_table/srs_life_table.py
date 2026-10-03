"""SRS abridged life tables."""

import re
from collections.abc import Iterable, Iterator

import pandas as pd

from pdfexorcist import check
from pdfexorcist.rows import Page, split_values

COLS = [f"{s}_{m}" for s in ("total", "male", "female") for m in ("nqx", "lx", "nlx", "ex")]
KEY = ["page", "category", "age", "col"]
AGES = ["0-1", "1-5"] + [f"{a}-{a + 5}" for a in range(5, 85, 5)] + ["85+"]
AGE = re.compile(r"^(\d{1,2})[-+](\d{1,2})$|^\d{2}\+$")
TITLE = re.compile(r"^(.+?),?\s*(19|20)\d\d\s*-\s*\d\d$")
CATEGORIES = ("Total", "Rural", "Urban")
# report spellings used on these pages (srsindia maps them via R/utils.R .state_aliases)
STATE_NAMES = {
    "uttrakhand": "Uttarakhand",
    "odissa": "Odisha",
    "telengana": "Telangana",
    "nct of delhi": "Delhi",
}


def age_key(label: str) -> str | None:
    """Normalize the 2010-14 80+85 misprint to 80-85."""
    m = AGE.match(label)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}" if m.group(1) else label


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield values keyed with page-title state, or None before one is seen."""
    for page_no, lines in pages:
        state: str | None = None
        category: str | None = None
        for cells in lines:
            label, vals = split_values(cells)
            label = label.strip()
            m = TITLE.match(label)
            if m and not vals:
                name = re.sub(r"\s+", " ", m.group(1)).strip()
                state, category = STATE_NAMES.get(name.lower(), name), None
                continue
            if label in CATEGORIES and not vals:
                category = label
                continue
            age = age_key(label)
            if category and age and len(vals) == len(COLS):
                for col, v in zip(COLS, vals, strict=True):
                    yield {
                        "page": page_no,
                        "category": category,
                        "age": age,
                        "col": col,
                        "state": state,
                        "value": v,
                    }


@check("l(x+n) = l(x) * (1 - nqx)")
def survivorship(df: pd.DataFrame) -> pd.Series:
    """Check survivors from prior lx and nqx with a tolerance of three."""
    v = pd.to_numeric(df.value, errors="coerce")
    w = df.assign(v=v).pivot_table(
        index=["page", "category", "age"], columns="col", values="v", aggfunc="first"
    )
    bad = set()
    for sex in ("total", "male", "female"):
        lx, nqx = f"{sex}_lx", f"{sex}_nqx"
        if lx not in w or nqx not in w:
            continue
        for (pg, cat), g in w.groupby(level=[0, 1]):
            g = g.droplevel([0, 1]).reindex(AGES)
            off = (g[lx] - (g[lx] * (1 - g[nqx])).shift(1)).abs() > 3
            for age in off[off].index:
                prev = AGES[AGES.index(age) - 1]
                bad |= {(pg, cat, age, lx), (pg, cat, prev, lx), (pg, cat, prev, nqx)}
    return pd.Series(
        [k in bad for k in zip(df.page, df.category, df.age, df.col, strict=True)], index=df.index
    )
