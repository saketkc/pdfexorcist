"""IIPS district projections (1_3.pdf)."""

import re
from collections.abc import Iterable, Iterator

from pdfexorcist import total_check
from pdfexorcist.checks import Check
from pdfexorcist.rows import Page

KEY = ["page", "block", "year", "sex", "age"]
AGES = [str(a) for a in range(15)] + [f"{a}-{a + 4}" for a in range(15, 80, 5)] + ["80+"]
TOTAL = "All ages"
SEXES = ("Males", "Females")
YEAR = re.compile(r"^20[123]\d$")
NUMBER = re.compile(r"^-?\d+$")
DISTRICT = re.compile(r"District\s*:\s*(.+?)\s*(?:\(\d+\)\)?)?\s*$")
TITLE = re.compile(r"Age and Sex of (.+?) district of")
# (title district, "District:" header, printed years, [(age, ten values)])
Block = tuple[str | None, str | None, tuple[str, ...], list[tuple[str, list[str]]]]


def _tokens(cells: list[tuple]) -> list[str]:
    """All whitespace-separated tokens of a line, left to right."""
    return [t for _, text in sorted(cells, key=lambda c: c[0]) for t in text.split()]


def _row(toks: list[str]) -> tuple | None:
    """Return an age and ten values, or None for a non-data line."""
    if toks[:2] == ["All", "ages"]:
        age, vals = TOTAL, toks[2:]
    elif toks and toks[0] in AGES:
        age, vals = toks[0], toks[1:]
    else:
        return None
    if len(vals) != 2 * 5 or not all(NUMBER.match(v) for v in vals):
        return None
    return age, vals


def _district(text: str) -> str | None:
    """'State: Delhi (07) District: West (07)' -> 'West'."""
    m = DISTRICT.search(text)
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else None


def _blocks(lines: list[list]) -> list[Block]:
    """Return page blocks in reading order."""
    blocks: list[Block] = []
    title: str | None = None
    header: str | None = None
    for cells in lines:
        toks = _tokens(cells)
        text = " ".join(toks)
        m = TITLE.search(text)
        title = m.group(1) if m else title
        if "District" in text:
            header = _district(text) or header
        yrs = [t for t in toks if YEAR.match(t)]
        if len(yrs) == 5 and len(yrs) == len([t for t in toks if t not in ("Single", "ages")]):
            blocks.append((title, header, tuple(yrs), []))
            continue
        row = _row(toks) if blocks else None
        if row is not None:
            blocks[-1][3].append(row)
    out: list[Block] = []
    for b in blocks:
        same = [i for i, o in enumerate(out) if o[2:] == b[2:]]
        if same:  # keep the title from whichever copy has it
            out[same[0]] = (out[same[0]][0] or b[0], *out[same[0]][1:])
        elif b[3]:
            out.append(b)
    return out


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield printed values keyed with their block district."""
    for page_no, lines in pages:
        for block, (title, header, years, rows) in enumerate(_blocks(lines)):
            for age, vals in rows:
                for i, v in enumerate(vals):
                    yield {
                        "page": page_no,
                        "block": block,
                        "year": years[i // 2],
                        "sex": SEXES[i % 2],
                        "age": age,
                        "district": title or header,
                        "header": header,
                        "value": v,
                    }


# Each of the 29 age groups is rounded to a whole person, so their sum may miss
# the (also rounded) All ages by up to 29 x 0.5. A misread hundreds digit or a
# dropped row still fails.
ROUNDING = 0.5 * len(AGES)


def checks() -> list[Check]:
    """Check each sex's All ages total against its 29 age groups."""
    return [
        total_check(
            "age",
            TOTAL,
            AGES,
            by=["page", "block", "year", "sex"],
            abs_tol=ROUNDING,
            name="All ages = sum of ages",
        )
    ]
