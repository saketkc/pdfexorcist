"""Karnataka daily dengue and chikungunya report, scanned (most from late 2023 on).

OCR engines skip blank cells and a scan has no ruling lines, so a row's values are named by
their count. A row with any other count, or a token that is not a whole number, is left to
the other engines. Names snap to the printed ones, so a misread name still votes.
"""

import difflib
import re
from collections.abc import Iterable, Iterator

from karnataka_dengue import TESTS, district

AREA = ["blocks", "taluks", "phc", "villages", "population"]
DAY = [f"day_{t}" for t in TESTS]
CUM = [f"cum_{t}" for t in TESTS]
# as printed in the text reports, so both recipes give one name per district
NAMES = [
    "Bagalkote", "Ballari", "Bangaluru (R)", "Bangaluru (U)", "Bangaluru City (BBMP)",
    "Belagavi", "Bidar", "Chamarajanagar", "Chikkaballapura", "Chikkamagaluru",
    "Chitradurga", "Dakshina Kannada", "Davanagere", "Dharwada", "Gadag", "Hassan",
    "Haveri", "Kalaburagi", "Kodagu", "Kolar", "Koppal", "Mandya", "Mysuru", "Raichur",
    "Ramanagar", "Shivamogga", "Total", "Tumakuru", "Udupi", "Uttara kannada",
    "Vijaya nagar", "Vijayapura", "Yadageri",
]  # fmt: skip
BBMP = "Bangaluru City (BBMP)"
NUMBER = re.compile(r"^[0-9]+$")  # not \d, which takes a Thai seven
DIGIT = re.compile(r"[0-9]")
DISEASE = re.compile(r"\b(dengue|chikungunya)\b", re.IGNORECASE)
DATE = re.compile(r"date\W*(\d{1,2})\W+(\d{1,2})\W+(\d{4})", re.IGNORECASE)
CUM_YEAR = re.compile(r"from\W*0?1\W+0?1\W+(\d{4})", re.IGNORECASE)


def _key(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


KEYS = {_key(n): n for n in NAMES}


def snap(label: str) -> str | None:
    """The printed district name closest to an OCR'd label; None when none is close."""
    hit = difflib.get_close_matches(_key(label), KEYS, n=1, cutoff=0.8)
    return KEYS[hit[0]] if hit else None


def columns(name: str, n: int, disease: str) -> list[str] | None:
    """The columns of a row of n values; None when n fits no layout.

    The area columns come first, then the day and cumulative values. The day cells are
    either all blank or all printed, so a row may hold only the cumulative ones.
    """
    area = AREA[1:] if name == BBMP else AREA  # BBMP prints no block count
    other = "ns1" if disease == "Dengue" else "others"
    for cols in (area + DAY + CUM, area + CUM):
        if len(cols) == n:
            return [c.replace("ns1", other) for c in cols]
    return None


def row(tokens: list[str], disease: str) -> Iterator[dict]:
    """The values of one line, if it is a district row whose layout is clear."""
    tokens = [t.strip(" |[]{}") for t in tokens]
    tokens = [t for t in tokens if t]  # some engines give a blank cell as ""
    while tokens and not DIGIT.search(tokens[-1]):
        tokens.pop()  # a note printed sideways in the margin, read into the first row
    if tokens and NUMBER.match(tokens[0]):
        tokens = tokens[1:]  # the serial number
    at = next((i for i, t in enumerate(tokens) if NUMBER.match(t)), None)
    if not at:
        return
    name = snap(district(" ".join(tokens[:at])))
    values = tokens[at:]
    if name is None or not all(NUMBER.match(v) for v in values):
        return
    cols = columns(name, len(values), disease)
    if cols is None:
        return
    for c, v in zip(cols, values, strict=True):
        yield {"disease": disease, "district": name, "col": c, "value": v}


def parse(pages: Iterable) -> Iterator[dict]:
    """Yield each count keyed by disease, district and column, then the report date."""
    meta = {}
    for _, lines in pages:
        texts = [[t for _, t in ln] for ln in lines]
        page = " ".join(" ".join(t) for t in texts)
        found = DISEASE.search(page)
        if found is None:
            continue
        disease = found.group(1).capitalize()
        if (m := DATE.search(page)) and "report_date" not in meta:
            meta["report_date"] = f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"
        if (m := CUM_YEAR.search(page)) and "cum_year" not in meta:
            meta["cum_year"] = m[1]
        seen = set()
        for tokens in texts:
            for r in row(tokens, disease):
                if (r["district"], r["col"]) not in seen:  # a name read twice keeps the first
                    seen.add((r["district"], r["col"]))
                    yield r
    for col, value in meta.items():
        yield {"disease": "", "district": "", "col": col, "value": value}
