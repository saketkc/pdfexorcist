"""The district table's columns in each Kerala daily report layout, and the layout a page prints.

Engines split the sideways disease headings into letters in any order. So a layout is told by
the sorted letters under each column (read once per page with pdfplumber) and by the number of
counts in the TOT row.
"""

import re
from collections import Counter
from functools import cache
from itertools import pairwise
from pathlib import Path

Column = tuple[str, str, str]  # disease, subgroup, measure

DISTRICTS = {
    "TVM": "Thiruvananthapuram",
    "KLM": "Kollam",
    "PTA": "Pathanamthitta",
    "IDK": "Idukki",
    "KTM": "Kottayam",
    "ALP": "Alappuzha",
    "EKM": "Ernakulam",
    "TSR": "Thrissur",
    "PKD": "Palakkad",
    "MPM": "Malappuram",
    "KKD": "Kozhikode",
    "WYD": "Wayanad",
    "KNR": "Kannur",
    "KSD": "Kasaragod",
}
TOTAL = "TOT"


def _three(disease: str) -> list[Column]:
    return [(disease, "", m) for m in ("suspected", "confirmed", "deaths")]


def _one(disease: str) -> list[Column]:
    return [(disease, "", "confirmed")]


def _cat(*parts: list[Column]) -> list[Column]:
    return [c for part in parts for c in part]


COMMON = _cat(
    [("Fever", "OP", "cases"), ("Fever", "IP", "cases")],
    _three("Chikungunya"),
    _three("Dengue"),
    _three("Leptospirosis"),
    [("ADD", "", "cases"), ("Chickenpox", "", "cases"), ("Hepatitis A", "", "confirmed")],
)


def _four(disease: str) -> list[Column]:
    return [(disease, "", m) for m in ("suspected", "suspected_deaths", "confirmed", "deaths")]


CHOLERA = _four("Cholera")
MALARIA = [
    *(
        ("Malaria", f"{species} {origin}", "confirmed")
        for species in ("PV", "PF", "Mixed")
        for origin in ("imported", "indigenous")
    ),
    ("Malaria", "", "deaths"),
]


def _sc(disease: str) -> list[Column]:
    return [(disease, "", "suspected"), (disease, "", "confirmed")]


HEP_B = _one("Hepatitis B")
KFD = _four("KFD")
TYPHOID_2016 = _cat(COMMON, HEP_B, CHOLERA, _sc("JE"), MALARIA, _one("Typhoid"), _one("H1N1"))
KFD_2016 = _cat(TYPHOID_2016, KFD)  # Kyasanur forest disease, early 2016
SCRUB_2020 = _cat(COMMON, HEP_B, CHOLERA, _sc("JE"), MALARIA, _one("Scrub typhus"), _one("H1N1"))
COVID_2022 = _cat(SCRUB_2020, [("Covid-19", "", "cases"), ("Covid-19", "", "deaths")])
SCRUB_2023 = _cat(COMMON, HEP_B, CHOLERA, _sc("JE"), MALARIA, _one("Scrub typhus"))  # Mar 2023
AESJE_2023 = _cat(
    COMMON, HEP_B, CHOLERA, _sc("AES/JE"), MALARIA, _one("Scrub typhus"), _one("H1N1")
)
AESJE_2024 = _cat(COMMON, CHOLERA, _sc("AES/JE"), MALARIA, _one("Scrub typhus"), _one("H1N1"))
AES_JE = _cat(COMMON, CHOLERA, [("AES", "", "confirmed"), ("JE", "", "confirmed")], MALARIA)
INFLUENZA_2025 = _cat(AES_JE, _one("Scrub typhus"), _one("Influenza"))
MEASLES_2026 = _cat(AES_JE, _one("Scrub typhus"), _one("Measles"), _one("Influenza"))
LAYOUTS = {
    "kfd_2016": KFD_2016,
    "typhoid_2016": TYPHOID_2016,
    "scrub_2020": SCRUB_2020,
    "covid_2022": COVID_2022,
    "scrub_2023": SCRUB_2023,
    "aesje_2023": AESJE_2023,
    "aesje_2024": AESJE_2024,
    "influenza_2025": INFLUENZA_2025,
    "measles_2026": MEASLES_2026,
}


def _has(bag: str, word: str) -> bool:
    """Whether a column's letters hold every letter of a word."""
    return not Counter(word) - Counter(bag)


def pick(bags: list[str]) -> str | None:
    """The layout of a table with these column letters, or None for one not known."""
    n = len(bags)
    tail = bags[-4:]
    if n == 34:
        return "kfd_2016"
    if n == 32:
        return "covid_2022"
    aesje = any("/" in b and _has(b, "ej") for b in bags)
    if n == 30:
        if any(_has(b, "aeelmss") for b in tail):
            return "measles_2026"
        if any(_has(b, "dhiopty") for b in tail):
            return "typhoid_2016"
        return "aesje_2023" if aesje else "scrub_2020"
    if n == 29:
        if any(_has(b, "aefilnnuz") for b in tail):
            return "influenza_2025"
        if aesje:
            return "aesje_2024"
        return "scrub_2023" if any(b == "cejs" for b in bags) else None
    return None


def bags(words: list[dict]) -> list[str] | None:
    """The sorted letters printed above each count of the TOT row (pdfplumber words)."""
    tot = next((w for w in words if w["text"] == TOTAL), None)
    first = next((w for w in words if w["text"].rstrip(":") == "TVM"), None)
    if tot is None or first is None or first["top"] > tot["top"]:
        return None
    row = sorted(
        (w for w in words if abs(w["top"] - tot["top"]) < 3 and w["x0"] > tot["x1"]),
        key=lambda w: w["x0"],
    )
    mids = [(w["x0"] + w["x1"]) / 2 for w in row]
    edges = [-1e9, *((a + b) / 2 for a, b in pairwise(mids)), 1e9]
    heads = [w for w in words if first["top"] - 130 < w["top"] < first["top"] - 2]
    out = []
    for lo, hi in pairwise(edges):
        text = "".join(w["text"] for w in heads if lo <= (w["x0"] + w["x1"]) / 2 < hi)
        out.append("".join(sorted(re.sub(r"[^a-z0-9/]", "", text.lower()))))
    return out


def page_layout(pdf: Path, page_no: int) -> str | None:
    """The layout of the district table on a page (1-based), or None."""
    st = pdf.stat()  # keyed by size and time too: a temporary path can be reused
    return _layout(str(pdf), st.st_size, st.st_mtime_ns, page_no)


@cache
def _layout(pdf: str, _size: int, _mtime: int, page_no: int) -> str | None:
    import pdfplumber  # only for reports with a district table

    with pdfplumber.open(pdf) as doc:
        if not 1 <= page_no <= len(doc.pages):
            return None
        b = bags(doc.pages[page_no - 1].extract_words())
    return pick(b) if b else None
