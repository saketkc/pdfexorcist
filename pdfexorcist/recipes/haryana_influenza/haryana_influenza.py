"""Haryana daily influenza A (H1N1 and H3N2) surveillance report: cases by district.

A row is a district (or Total) and six counts: for H1N1 then H3N2, cases on the day, cases
since 1 January and deaths since 1 January. The state status table above it is left out.
"""

import re
from collections.abc import Iterable, Iterator

from pdfexorcist.rows import Page, split_values

SUBTYPES = ("H1N1", "H3N2")
MEASURES = ("day_cases", "cum_cases", "cum_deaths")
COLUMNS = [(s, m) for s in SUBTYPES for m in MEASURES]
# "11. Yamunanagar", "Charkhi Dadri", "Total"; engines may split off or drop the serial
LABEL = re.compile(r"^(?:\d+\s*\.?\s+)?([A-Za-z][A-Za-z .]*?)\.?$")


def district(label: str) -> str | None:
    """The district name in a row label, without its serial number."""
    m = LABEL.match(label.strip())
    return re.sub(r"\s+", " ", m.group(1)) if m else None


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each count keyed by subtype, district and column."""
    for page_no, lines in pages:
        started = False
        for cells in lines:
            text = " ".join(t for _, t in cells)
            # the status table's rows ("Deaths 0 1 0 0") never reach six counts, but a
            # row of the district table always comes after its heading
            started = started or "district" in text.lower()
            label, values = split_values(cells)
            name = district(label) if started else None
            if not name or len(values) != len(COLUMNS):
                continue
            for (subtype, col), value in zip(COLUMNS, values, strict=True):
                yield {
                    "subtype": subtype,
                    "district": name,
                    "col": col,
                    "value": value,
                    "page": page_no,
                }
