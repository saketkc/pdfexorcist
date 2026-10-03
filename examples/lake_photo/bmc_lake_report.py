"""BMC daily lake-level report."""

import re
from collections import Counter

KEY = ["lake", "year", "field"]

# (name, FSL useful content in ML), top to bottom as printed
LAKES = [
    ("Upper Vaitarna", 227047),
    ("Modak Sagar", 128925),
    ("Tansa", 145080),
    ("Middle Vaitarna", 193530),
    ("Bhatsa", 717037),
    ("Vihar", 27698),
    ("Tulsi", 8046),
]
TOTAL_CAPACITY = 1447363
BLOCKS = list(LAKES)
BLOCKS.insert(4, ("subtotal", sum(cap for _, cap in LAKES[:4])))  # printed after Middle Vaitarna
BLOCKS.append(("total", TOTAL_CAPACITY))

# Values after the YEAR cell, left to right (the lake's capacity is dropped first).
CURRENT = [
    "level",
    "rise_fall_24h",
    "useful_content_ml",
    "pct_useful_content",
    "today_rain_mm",
    "total_rain_mm",
]
PRIOR = [f for f in CURRENT if f != "rise_fall_24h"]  # rise/fall printed for the current year only
TOTALS = ["useful_content_ml", "pct_useful_content"]

_NUM = re.compile(r"-?\d+(?:\.\d+)?")
_SPECK = re.compile(r"^[·•∙]+|[·•∙]+$")  # scan specks read as dots: "·141.90", "•"
ROW_PCT_TOL = 0.05  # % points a row may be off useful/capacity (printed to 2 decimals)


def fields(name: str, yr: str, current: str) -> list:
    """Return values following a block row's YEAR cell."""
    return TOTALS if name in ("subtotal", "total") else CURRENT if yr == current else PRIOR


def parse(pages):
    """Yield readings keyed by lake, year, and field."""
    lines = [[t for _, t in ln] for _, page in pages for ln in page]
    text = " ".join(" ".join(ln) for ln in lines)
    # the date from the title line only; table-only reads (Chandra) never see it
    if m := re.search(r"lake\s*l\w+s\b.*?(\d{2})[-/.](\d{2})[-/.](\d{4})", text, re.I):
        yield {
            "lake": "",
            "year": "",
            "field": "report_date",
            "value": f"{m[3]}-{m[2]}-{m[1]}",
        }
    # the current year is the latest one in the YEAR column. A value can look like a
    # year (useful content 2076); real years repeat, once per block of rows
    counts = Counter(int(t) for ln in lines for t in ln if re.fullmatch(r"20\d\d", t))
    year = max((y for y, n in counts.items() if n >= 3), default=max(counts, default=None))
    if year is None:
        return
    years = [str(year - k) for k in range(3)]
    block = -1
    for toks in lines:
        if re.match(r"\s*remarks?\b", " ".join(toks), re.I):  # "REMARK" in 2024
            break
        at = next((i for i, t in enumerate(toks) if t in years), None)
        if at is None:
            continue
        yr = toks[at]
        block += yr == years[0]
        if not 0 <= block < len(BLOCKS):
            continue
        name, cap = BLOCKS[block]
        fs = fields(name, yr, years[0])
        vals = [v for t in toks[at + 1 :] if (v := _SPECK.sub("", t.strip()))]
        if not all(_NUM.fullmatch(t) for t in vals):
            continue  # a garbled token ("3605.0ął"); dropping it would shift the rest
        uc = fs.index("useful_content_ml")
        if len(vals) > uc + 1 and float(vals[uc + 1]) == cap:
            del vals[uc + 1]  # the lake's capacity, printed in one of its rows
        if len(vals) != len(fs):
            continue
        row = dict(zip(fs, (float(v) + 0.0 for v in vals), strict=True))  # + 0.0: "-0.00" == "0.00"
        if abs(100 * row["useful_content_ml"] / cap - row["pct_useful_content"]) > ROW_PCT_TOL:
            continue  # a shifted or misread row: its % is not useful content / capacity
        for f, v in row.items():
            yield {"lake": name, "year": yr, "field": f, "value": repr(v)}
