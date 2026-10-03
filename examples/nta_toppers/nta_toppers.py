"""NEET (UG) toppers list (a scan)."""

import re
from itertools import pairwise, takewhile

import pandas as pd

from pdfexorcist import check
from pdfexorcist.cells import token_boxes

KEY = ["sr_no", "field"]
FIELDS = [
    "application_no",
    "name",
    "gender",
    "category",
    "percentile",
    "rank",
    "state",
]
GENDERS = {"Male", "Female"}
# category words, which a wrapped line may hold in lowercase
CATEGORY_WORDS = {"obc", "ncl", "obcncl", "central", "list", "general", "genews"}

_SR = re.compile(r"\d{1,3}")
_APP = re.compile(r"\d{12}(?!\d)")  # Apple Vision may add marks after it ("260410589461Íš")
_PCT = re.compile(r"\d{2}[.,]\d+")  # Apple Vision reads some points as commas
_INT = re.compile(r"\d{1,4}")


def category(text: str) -> str:
    """Return the printed category despite wrapping or spacing."""
    c = re.sub(r"[^a-z]", "", text.lower())
    if any(w in c for w in ("obc", "ncl", "central")):
        return "OBC-NCL (Central List)"
    return {"general": "General", "genews": "Gen-EWS", "sc": "SC", "st": "ST"}.get(c, text)


def words(toks: list[str]) -> str:
    """Return joined uppercase name or state tokens, dropping nonletters."""
    s = " ".join(t for t in toks if re.search(r"[A-Za-z]", t)).upper()
    return re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", s))


def _wrapped(toks: list[str]) -> bool:
    """Return whether a line can be a wrapped name, category, or state."""
    return bool(toks) and all(
        (t.upper() == t and not any(ch.isdigit() for ch in t))
        or re.sub(r"[^a-z]", "", t.lower()) in CATEGORY_WORDS
        for t in toks
    )


def _row(toks: list[tuple[float, str]], above: list[tuple[float, str]]) -> dict | None:
    """Return fields from a row's final line and preceding wraps."""
    t = [s for _, s in toks]
    if not t or not _SR.fullmatch(t[0]):
        return None
    pct = next((i for i, s in enumerate(t) if _PCT.fullmatch(s)), None)
    if pct is None or pct + 1 >= len(t) or not _INT.fullmatch(t[pct + 1]):
        return None
    row = {"sr_no": t[0], "percentile": t[pct].replace(",", "."), "rank": t[pct + 1]}
    start = 1
    if m := _APP.match(t[1]):
        row["application_no"] = m[0]
        start = 2
    g = next((i for i in range(start, pct) if t[i] in GENDERS), None)
    # States print in capitals; GLM-OCR may add cells after it ("KERALA Male General")
    state = list(takewhile(lambda s: s.upper() == s, t[pct + 2 :]))
    x_rank = toks[pct + 1][0]
    row["state"] = words([s for x, s in above if x > x_rank] + state)
    if g is None:  # name and category cannot be told apart
        return row
    x_left, x_gender, x_pct = toks[start - 1][0], toks[g][0], toks[pct][0]
    name = [s for x, s in above if x_left < x < x_gender] + t[start:g]
    cat = [s for x, s in above if x_gender < x < x_pct] + t[g + 1 : pct]
    row |= {
        "name": words(name),
        "gender": t[g],
        "category": category(" ".join(cat)),
    }
    return row


def parse(pages):
    """Yield readings keyed by serial number and field."""
    active = True
    for _, lines in pages:
        above: list[tuple[float, str]] = []
        for cells in lines:
            toks = [((b[0] + b[2]) / 2 if b else x, s) for x, s, b in token_boxes(cells)]
            text = " ".join(s for _, s in toks)
            if re.search(r"\blist of\b", text, re.I):
                active = bool(re.search(r"\btop\s+\d+\s+candidates\b", text, re.I))
            if not active:
                continue
            row = _row(toks, above)
            if row is None and _wrapped([s for _, s in toks]):
                above += toks
                continue
            above = []
            if row is None:
                continue
            sr = str(int(row.pop("sr_no")))
            for f in FIELDS:
                if row.get(f):
                    yield {"sr_no": sr, "field": f, "value": row[f]}


@check("NEET rank rises with Sr. No.")
def rank_rises(df: pd.DataFrame) -> pd.Series:
    """Flag adjacent ranks that do not rise; mark both rows."""
    return _order(df, "rank", lambda prev, cur: cur > prev)


@check("percentile does not rise with Sr. No.")
def percentile_falls(df: pd.DataFrame) -> pd.Series:
    """Flag adjacent percentiles that rise; mark both rows."""
    return _order(df, "percentile", lambda prev, cur: cur <= prev)


def _order(df: pd.DataFrame, field: str, ok) -> pd.Series:
    """Fail the cells of field where consecutive agreed rows break ok(prev, cur)."""
    d = df[df.field == field]
    v = pd.to_numeric(d.value, errors="coerce")
    s = v.groupby(d.sr_no.astype(int)).first().dropna().sort_index()
    bad = {sr for (p, a), (q, b) in pairwise(s.items()) if not ok(a, b) for sr in (p, q)}
    return (df.field == field) & df.sr_no.astype(int).isin(bad)
