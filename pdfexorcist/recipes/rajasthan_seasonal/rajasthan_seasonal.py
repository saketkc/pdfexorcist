"""Rajasthan seasonal disease status (Medical, Health and Family Welfare): counts by district.

A district may print a blank ("Jaipur 2" in a scrub typhus report) and its name may end in a
digit, so a count's column comes from its x: the median x of that count over the full rows.
"""

import re
import statistics
from collections.abc import Iterable, Iterator
from itertools import pairwise

from pdfexorcist.cells import token_boxes
from pdfexorcist.rows import Page, _column, is_value

# printed name -> output name, in the order they are searched for
DISEASES = {
    "scrub typhus": "Scrub Typhus",
    "h1n1": "H1N1",
    "leptospirosis": "Leptospirosis",
    "brucellosis": "Brucellosis",
    "dengue": "Dengue",
    "malaria": "Malaria",
    "chikungunya": "Chikungunya",
}
MEASURES = {"positive": "positive", "death": "deaths", "deaths": "deaths"}
SERIAL = re.compile(r"^\d{1,2}\.?$")
TOL = 0.45  # of the spacing between column centres


def _diseases(text: str) -> list[str]:
    """Disease names in a line, in printed order."""
    low = text.lower()
    found = [(low.find(k), v) for k, v in DISEASES.items() if k in low]
    return [v for _, v in sorted(found)]


def _tokens(cells: list) -> list[tuple[float, str]]:
    """(x centre, token) left to right; a token's own box where the engine gives one."""
    out = []
    for x, t, box in token_boxes(cells):
        out.append(((box[0] + box[2]) / 2 if box else x, t))
    return sorted(out, key=lambda p: p[0])


def _trailing(toks: list[tuple[float, str]]) -> list[tuple[float, str]]:
    i = len(toks)
    while i and is_value(toks[i - 1][1]):
        i -= 1
    return toks[i:]


def _columns(lines: list[list], start: int) -> tuple[list[str], list[str]] | None:
    """Disease and measure of each count column, from the measures line at start."""
    measures = [MEASURES[t.lower()] for t in lines[start] if t.lower() in MEASURES]
    names: list[str] = []
    for line in reversed(lines[:start]):
        names = _diseases(" ".join(line))
        if names:
            break
    if not names or len(measures) % len(names):
        return None
    per = len(measures) // len(names)
    return [names[i // per] for i in range(len(measures))], measures


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each count keyed by disease, district and column."""
    for page_no, lines in pages:
        toks = [_tokens(cells) for cells in lines]
        words = [[t for _, t in line] for line in toks]
        head = next(
            (i for i, w in enumerate(words) if any(t.lower() == "positive" for t in w)), None
        )
        if head is None or (cols := _columns(words, head)) is None:
            continue
        diseases, measures = cols
        n = len(measures)
        body = [line for line in toks[head + 1 :] if line]
        full = [_trailing(line) for line in body]
        full = [v for v in full if len(v) == n]
        if not full:
            continue
        centres = [statistics.median(v[i][0] for v in full) for i in range(n)]
        within = TOL * (min((b - a for a, b in pairwise(centres)), default=1.0) or 1.0)
        for line in body:
            yield from _row(line, centres, within, diseases, measures, page_no)


def _row(
    line: list[tuple[float, str]],
    centres: list[float],
    within: float,
    diseases: list[str],
    measures: list[str],
    page_no: int,
) -> Iterator[dict]:
    """The counts of one row, placed by x; tokens left of them are its label."""
    placed: dict[int, str] = {}
    i = len(line)
    while i and is_value(line[i - 1][1]):
        x, t = line[i - 1]
        c = _column(x, centres, within)
        if c is None or c in placed:
            break
        placed[c] = t
        i -= 1
    label = [t for _, t in line[:i]]
    if label and SERIAL.match(label[0]):
        label = label[1:]
    name = re.sub(r"\s+", " ", " ".join(label)).strip()
    if not placed or not re.match(r"^[A-Za-z]", name):
        return
    if name.lower() == "total":
        name = "Total"
    for c, value in sorted(placed.items()):
        yield {
            "disease": diseases[c],
            "district": name,
            "col": measures[c],
            "value": value,
            "page": page_no,
        }
