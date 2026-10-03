"""MoHFW State projections, Table 18."""

import re
from collections.abc import Iterable, Iterator

from pdfexorcist import total_check
from pdfexorcist.checks import Check
from pdfexorcist.rows import Page

KEY = ["year", "age", "sex"]
YEARS = (2011, 2016, 2021, 2026, 2031, 2036)
SEXES = ("Person", "Male", "Female")
AGES = [f"{a}-{a + 4}" for a in range(0, 80, 5)] + ["80+"]  # the 17 groups that sum to Total
ROW = re.compile(r"^(Total|80 ?\+|\d{1,2} ?- ?\d{1,2}) ((?:[\d,]+ ){8}[\d,]+)$")
HEADER_WORDS = {"age", "group", "agegroup"}
# Each printed figure is rounded to the nearest thousand, so a sum of n of them
# may be off by up to n/2: 1 for Person = Male + Female, 8.5 for 17 age groups.
PERSON_TOL = 1
TOTAL_TOL = len(AGES) / 2


def _years(tokens: list[str]) -> list[int] | None:
    """Extract three years from a block header."""
    words = [t for t in tokens if not t.isdigit()]
    digits = "".join(t for t in tokens if t.isdigit())
    if any(w.lower() not in HEADER_WORDS for w in words) or len(digits) != 12:
        return None
    years = [int(digits[i : i + 4]) for i in range(0, 12, 4)]
    return years if all(y in YEARS for y in years) else None


def _age(label: str) -> str:
    """Normalize spaces around age-range punctuation."""
    return label.replace(" ", "")


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield readings keyed by year, age, sex, title, and page."""
    years: list[int] | None = None
    title, after_caption = "", False
    for page_no, lines in pages:
        for cells in lines:
            tokens = [t for _, text in cells for t in text.split()]
            text = " ".join(tokens)
            if not text:
                continue
            if after_caption:
                title, after_caption = text, False
                continue
            if text.startswith("Projected Population By Age"):
                after_caption = True
                continue
            block = _years(tokens)
            if block:
                years = block
                continue
            m = ROW.match(text)
            if not (m and years):
                continue
            for i, v in enumerate(m.group(2).split()):
                yield {
                    "year": years[i // 3],
                    "age": _age(m.group(1)),
                    "sex": SEXES[i % 3],
                    "title": title,
                    "page": page_no,
                    "value": v.replace(",", ""),
                }


def checks() -> list[Check]:
    """Check table arithmetic within printed-value rounding."""
    return [
        total_check(
            "sex",
            "Person",
            ["Male", "Female"],
            by=["year", "age"],
            abs_tol=PERSON_TOL,
            name="Person = Male + Female",
        ),
        total_check(
            "age",
            "Total",
            AGES,
            by=["year", "sex"],
            abs_tol=TOTAL_TOL,
            name="Total = sum of age groups",
        ),
        total_check("age", "0-4", ["0-1"], by=["year", "sex"], op=">=", name="0-4 >= 0-1"),
    ]
