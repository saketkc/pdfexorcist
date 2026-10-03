"""CRS State Tables 1-4."""

import re
from collections.abc import Iterable, Iterator

from pdfexorcist import total_check
from pdfexorcist.checks import Check
from pdfexorcist.rows import Page, split_values

AREAS = ("Rural", "Urban", "Total")
SEXES = ("Male", "Female", "Person")
COLS = [f"{a}_{s}" for a in AREAS for s in SEXES]
KEY = ["page", "state", "col"]


def _key(name: str) -> str:
    """Return a spacing- and punctuation-insensitive state key."""
    return re.sub(r"[^a-z]", "", name.lower())


def _unbold(label: str) -> str:
    """Collapse repeated overprinted letters in a label."""
    if (
        len(label) >= 8
        and len(label) % 4 == 0
        and all(len(set(label[i : i + 4])) == 1 for i in range(0, len(label), 4))
    ):
        return label[::4]
    return label


def _rows(lines: list) -> Iterator[tuple[str, list[str]]]:
    """Yield each data row's label and nine values in reading order."""
    split = [split_values(cells) for cells in lines]
    for i, (label, vals) in enumerate(split):
        if len(vals) != len(COLS):
            continue
        if not label:  # a name wrapped around its row
            above = split[i - 1] if i > 0 else ("", [1])
            below = split[i + 1] if i + 1 < len(split) else ("", [1])
            if not above[1] and not below[1]:
                label = f"{above[0]} {below[0]}"
        yield " ".join(_unbold(w) for w in label.split()), vals


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield values keyed by page, state, column, area, and sex."""
    for page_no, lines in pages:
        seen: set[str] = set()
        for label, vals in _rows(lines):
            state = _key(label)
            if not state or state in seen:
                continue
            seen.add(state)
            for col, v in zip(COLS, vals, strict=True):
                area, sex = col.split("_")
                yield {
                    "page": page_no,
                    "state": state,
                    "col": col,
                    "label": label,
                    "area": area,
                    "sex": sex,
                    "value": v,
                }


def checks() -> list[Check]:
    """Person >= Male + Female in each area, Total >= Rural + Urban for each sex."""
    return [
        total_check(
            "sex",
            "Person",
            ["Male", "Female"],
            by=["page", "state", "area"],
            op=">=",
            name="Person >= Male + Female",
        ),
        total_check(
            "area",
            "Total",
            ["Rural", "Urban"],
            by=["page", "state", "sex"],
            op=">=",
            name="Total >= Rural + Urban",
        ),
    ]
