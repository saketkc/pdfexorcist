"""MCCD Tables 2 and 4."""

import re
import statistics
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator
from functools import cache
from itertools import pairwise
from pathlib import Path

import pandas as pd

from pdfexorcist import EXTRACTORS, fit_page_boxes
from pdfexorcist.rows import Page, is_value

KEY = ["page", "code", "pocc", "sex", "col"]
SEXES = ("M", "F", "T")
CODE = re.compile(r"\(\s*([A-Z]\s*\d[^()]*)")  # a long list may lose its ")"
TITLE_WORDS = re.compile(r"TABLE|DURING|ACCORDING|REVISION", re.I)

# canonical name: header spellings in Tables 2 and 4, 2008-2024 (mccdindia's alias table, trimmed)
STATES = {
    "All States (Total)": ["All States (Total)"],
    "Andaman & Nicobar Islands": ["A & N Islands"],
    "Andhra Pradesh": [],
    "Arunachal Pradesh": [],
    "Assam": [],
    "Bihar": [],
    "Chandigarh": [],
    "Chhattisgarh": ["Chattisgarh"],
    "Dadra & Nagar Haveli": ["D & N Haveli"],
    "Dadra & Nagar Haveli & Daman & Diu": ["D & N Haveli & Daman & Diu"],  # from 2020
    "Daman & Diu": [],
    "Delhi": [],
    "Goa": [],
    "Gujarat": ["Gujrat"],
    "Haryana": [],
    "Himachal Pradesh": [],
    "Jammu & Kashmir": [],
    "Jharkhand": [],
    "Karnataka": [],
    "Kerala": [],
    "Ladakh": [],  # from 2021
    "Lakshadweep": ["Lakshawdeep"],
    "Madhya Pradesh": [],
    "Maharashtra": [],
    "Manipur": [],
    "Meghalaya": [],
    "Mizoram": [],
    "Nagaland": [],
    "Odisha": ["Orissa"],
    "Puducherry": [],
    "Punjab": [],
    "Rajasthan": [],
    "Sikkim": [],
    "Tamil Nadu": [],
    "Telangana": [],
    "Tripura": [],
    "Uttar Pradesh": [],
    "Uttarakhand": [],
    "West Bengal": [],
}


def words_key(name: str) -> str:
    """Return a spelling-, case-, and word-order-insensitive name key."""
    return " ".join(sorted(re.findall(r"[a-z]+", re.sub(r"&|\band\b", "", name.lower()))))


KNOWN = {words_key(v): c for c, vs in STATES.items() for v in [c, *vs]}


def code_key(code: str) -> str:
    """Return an ICD list's first two codes despite wrapping or overprint."""
    codes = re.sub(r"[^A-Z0-9.\-,]", "", code.upper().replace("&", ",")).strip(".,").split(",")
    return ",".join(codes[:2])


def _split(cells: list) -> tuple[str, list[str], str | None]:
    """Split a line into label, longest value run, and adjacent sex marker."""
    toks = [t for _, text in cells for t in text.split()]
    a = b = i = 0
    while i < len(toks):
        j = i
        while j < len(toks) and is_value(toks[j]):
            j += 1
        if j - i > b - a:
            a, b = i, j
        i = max(j, i + 1)
    left, vals, right = toks[:a], toks[a:b], toks[b:]
    sex = left.pop() if vals and left and left[-1] in SEXES else None
    if vals and right and right[0] in SEXES:
        sex, right = sex or right[0], right[1:]
    return " ".join(left or right), vals, sex


def _is_column_numbers(label: str, vals: list[str]) -> bool:
    """Return whether a row is the header's column-number row."""
    n = [int(v) for v in vals if v.isdigit()]
    return (
        not label and len(n) == len(vals) >= 3 and all(0 <= b - a <= 1 for a, b in pairwise(n[:3]))
    )


def _block_key(text: str) -> str:
    codes = CODE.findall(text)
    if codes:
        return code_key(codes[0])
    return "ALL" if "ALLCAUSES" in re.sub(r"[^A-Z]", "", text.upper()) else ""


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield one keyed record per engine value."""
    for page_no, lines in pages:
        split = [_split(c) for c in lines]
        counts = Counter(len(v) for _, v, sex in split if sex and len(v) >= 3)
        if not counts:
            continue
        ncols = counts.most_common(1)[0][0]
        blocks: list[dict] = []
        cur: dict | None = None
        pending: list[str] = []
        for text, vals, sex in split:
            if sex is None and _is_column_numbers(text, vals):
                pending = []  # title and header above the column numbers
                continue
            if sex is None and len(vals) != ncols:
                if text:
                    own = " ".join(cur["text"]) if cur else ""
                    late_code = CODE.search(text) and not CODE.search(own)
                    open_code = re.search(r"\([^)]*$", own)
                    after_t = cur is None or (
                        "T" in cur["rows"] and not late_code and not open_code
                    )
                    (pending if after_t else cur["text"]).append(text)
                continue
            if sex is None:  # a value row printed without its marker: the next sex
                last = list(cur["rows"]) if cur else []
                sex = "M" if not last or "T" in last else SEXES[SEXES.index(last[-1]) + 1]
            if cur is None or sex == "M" or sex in cur["rows"] or "T" in cur["rows"]:
                cur, pending = {"text": pending, "rows": {}}, []
                blocks.append(cur)
            if text:
                cur["text"].append(text)
            cur["rows"][sex] = vals if len(vals) == ncols else []
        seen: Counter = Counter()
        for b in blocks:
            code = _block_key(" ".join(b["text"]))
            seen[code] += 1
            for sex, vals in b["rows"].items():
                for col, v in enumerate(vals):
                    yield {
                        "page": page_no,
                        "code": code,
                        "pocc": seen[code],
                        "sex": sex,
                        "col": col,
                        "value": v,
                    }


def _column_xs(lines: list) -> list[float]:
    """Return median x positions from complete M/F/T rows."""
    rows = []
    for cells in lines:
        _, vals, sex = _split(cells)
        xs = [x for x, t in cells if is_value(t)]
        if sex and len(vals) >= 3 and len(xs) == len(vals):
            rows.append(xs)
    if not rows:
        return []
    n = Counter(len(r) for r in rows).most_common(1)[0][0]
    return [statistics.median(r[i] for r in rows if len(r) == n) for i in range(n)]


def _segment(words: list[str], n: int) -> list[str] | None:
    """Split header words, in column order, into exactly n known names (longest first)."""

    @cache
    def go(i: int, k: int) -> tuple | None:
        if i == len(words) or k == 0:
            return () if i == len(words) and k == 0 else None
        for j in range(len(words), i, -1):
            span = words[i:j]  # a name wrapped mid-word reads "Lakshawdee p" (2013 Table 2)
            name = KNOWN.get(words_key(" ".join(span))) or KNOWN.get(words_key("".join(span)))
            rest = go(j, k - 1) if name else None
            if rest is not None:
                return (name, *rest)
        return None

    found = go(0, n)
    return list(found) if found else None


def _page_states(page, xs: list[float]) -> list[str] | None:
    """Return header column names left to right, or None when unread."""
    import pymupdf

    spacing = min(b - a for a, b in pairwise(xs))
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_MEDIABOX_CLIP
    lines = [ln for b in page.get_text("dict", flags=flags)["blocks"] for ln in b.get("lines", [])]
    band = max(
        (ln["bbox"][3] for ln in lines if round(ln["dir"][1])), default=0
    )  # rotated names end here
    rotated, flat = [], []  # (x centre, text)
    for ln in lines:
        x0, _, x1, y1 = ln["bbox"]
        text = "".join(s["text"] for s in ln["spans"]).strip()
        xc = (x0 + x1) / 2
        if (
            text
            and y1 <= band
            and xs[0] - 1.5 * spacing <= xc <= xs[-1] + 1.5 * spacing
            and not text.isdigit()
            and not TITLE_WORDS.search(text)
            and words_key(text) != "sex"
        ):
            (rotated if round(ln["dir"][1]) else flat).append((xc, text))
    for pieces in (rotated, rotated + flat):
        names = _segment(" ".join(t for _, t in sorted(pieces)).split(), len(xs))
        if names:
            return names
    return None


def header_states(pdf: Path) -> dict[tuple[int, int], str | None]:
    """Return each page column's canonical state, or None when unread."""
    import pymupdf

    out: dict[tuple[int, int], str | None] = {}
    with tempfile.TemporaryDirectory() as tmp:
        pdf = fit_page_boxes(Path(pdf), Path(tmp))
        pages = dict(EXTRACTORS["pymupdf"](pdf))
        with pymupdf.open(pdf) as doc:
            for page_no, page in enumerate(doc, start=1):
                xs = _column_xs(pages.get(page_no, []))
                names = _page_states(page, xs) if len(xs) >= 3 else None
                out.update({(page_no, c): names[c] if names else None for c in range(len(xs))})
    return out


def name_states(cells: pd.DataFrame, pdf: Path) -> pd.DataFrame:
    """Add states read from page headers; unread columns receive None."""
    states = header_states(pdf)
    return cells.assign(
        state=[states.get((int(p), int(c))) for p, c in zip(cells.page, cells.col, strict=True)]
    )
