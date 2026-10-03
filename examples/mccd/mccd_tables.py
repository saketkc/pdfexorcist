"""MCCD Tables 5 and 9."""

import re
from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path

import pandas as pd

from pdfexorcist.rows import Page, is_value

KEY = ["page", "group", "sex", "col"]
SEXES = ("M", "F", "T")
ALL = "ALL"  # the ALL CAUSES block
ROMAN = re.compile(r"^(?=[IVX])X{0,3}(IX|IV|V?I{0,3})\.?$")
AGE = re.compile(r"^(<1|\d{1,2}-\d{1,2}|\d{1,2}\+|N\.S\.|TOTAL)$")
YEAR = re.compile(r"^(19|20)\d\d$")


def _split(cells: list) -> tuple[list[str], list[str], str | None]:
    """Split a line into label tokens, longest value run, and preceding sex marker."""
    toks = [t for _, text in cells for t in text.split()]
    a = b = i = 0
    while i < len(toks):
        j = i
        while j < len(toks) and is_value(toks[j]):
            j += 1
        if j - i > b - a:
            a, b = i, j
        i = max(j, i + 1)
    label, vals = toks[:a] + toks[b:], toks[a:b]
    sex = label.pop(a - 1) if vals and a and toks[a - 1] in SEXES else None
    return label, vals, sex


def _group(lines: list[list[str]]) -> str | None:
    """Return a block's leading Roman numeral or ALL for ALL CAUSES."""
    for words in lines:
        if words and ROMAN.match(words[0]):
            return words[0].rstrip(".")
    return ALL if "ALLCAUSES" in "".join(w for ws in lines for w in ws).upper() else None


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield one keyed record per engine value."""
    for page_no, lines in pages:
        split = [_split(c) for c in lines]
        counts = Counter(len(v) for _, v, sex in split if sex and len(v) >= 3)
        if not counts:
            continue
        ncols = counts.most_common(1)[0][0]
        blocks: list[dict] = []
        pending: list[list[str]] = []
        for label, vals, sex in split:
            if sex is None:
                pending = [] if vals else [*pending, label]
                continue
            cur = blocks[-1] if blocks else None
            if cur is None or sex == "M" or sex in cur["rows"] or "T" in cur["rows"]:
                cur = {"lines": [], "rows": {}}
                blocks.append(cur)
            cur["lines"] += [*pending, label]
            pending = []
            cur["rows"][sex] = vals if len(vals) == ncols else []
        for b in blocks:
            group = _group(b["lines"])
            if group is None:
                continue
            for sex, vals in b["rows"].items():
                for col, v in enumerate(vals):
                    yield {"page": page_no, "group": group, "sex": sex, "col": col, "value": v}


def _header(page, label: re.Pattern) -> list[str]:
    """Return the first matching header's words from left to right."""
    lines: dict[int, list[tuple[float, str]]] = {}
    for x0, y0, _, y1, word, *_ in page.get_text("words"):
        if label.match(word):
            lines.setdefault(round((y0 + y1) / 2), []).append((x0, word))
    for _, words in sorted(lines.items()):
        if len(words) >= 5:
            return [w for _, w in sorted(words)]
    return []


def _name_columns(cells: pd.DataFrame, pdf: Path, label: re.Pattern, name: str) -> pd.DataFrame:
    """Add printed column names; unmatched headings yield None."""
    import pymupdf

    with pymupdf.open(pdf) as doc:
        heads = {n: _header(page, label) for n, page in enumerate(doc, start=1)}
    voted = cells[cells.status == "verified"] if "status" in cells else cells
    ncols = voted.groupby("page").col.max() + 1  # unresolved readings may run longer
    names = []
    for p, c in zip(cells.page, cells.col, strict=True):
        h = heads.get(int(p), [])
        names.append(h[int(c)] if len(h) == ncols.get(p) and int(c) < len(h) else None)
    return cells.assign(**{name: names})


def name_ages(cells: pd.DataFrame, pdf: Path) -> pd.DataFrame:
    """Add Table 5 age-group headings to each column."""
    return _name_columns(cells, pdf, AGE, "age")


def name_years(cells: pd.DataFrame, pdf: Path) -> pd.DataFrame:
    """Add Table 9 year headings to each column."""
    return _name_columns(cells, pdf, YEAR, "year")
