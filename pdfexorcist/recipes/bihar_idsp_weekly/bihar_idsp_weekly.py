"""State Health Society Bihar weekly infectious disease bulletin (IDSP), state level.

One row per disease, four counts: the week last year and this year, then the cumulative
counts to that week in both years. Lab-confirmed diseases print "tested/positive" ("74/13").
"""

import re
from collections.abc import Iterable, Iterator

from pdfexorcist.rows import Page

COLS = ("prev_week", "week", "prev_cum", "cum")
# (pattern on the lower-cased label, disease); order matters: meningococcal before meningitis
DISEASES = [
    (r"measles", "Measles"),
    (r"chicken\s*pox", "Chicken Pox"),
    (r"pertussis", "Pertussis"),
    (r"diphth", "Diphtheria"),
    (r"hepatitis\s*a\b", "Viral Hepatitis A"),
    (r"hepatitis\s*e\b", "Viral Hepatitis E"),
    (r"acute\s+diarr", "Acute Diarrhoeal Disease"),
    (r"dysentery", "Bacillary Dysentery"),
    (r"typhoid", "Typhoid Fever"),
    (r"meningococ", "Meningococcal Meningitis"),
    (r"meningitis", "Meningitis"),
    (r"pneumonia", "Pneumonia"),
    (r"ari\s*/\s*ili", "ARI/ILI"),
    (r"malaria", "Malaria"),
    (r"acute\s+encephalitis", "AES/JE"),
    (r"chikun", "Chikungunya"),
    (r"dengue", "Dengue"),
    (r"dog\s*bite", "Dog Bite"),
    (r"snake\s*bite", "Snake Bite"),
    (r"fever\s+of\s+unknown", "Fever of Unknown Origin"),
    (r"leptospir", "Leptospirosis"),
    (r"acute\s+flaccid", "Acute Flaccid Paralysis"),
]
# the heading's years ("DISEASE 2015 2016 INCIDENCE 2015 2016") are not counts
HEADING = re.compile(r"incidence|week", re.IGNORECASE)
# 523, *4/0, 32/10, 20/10(T/P), 0/(T/P), 30/5/(T/P); the page edge clips some to
# "114/9(T/P". Excel's #REF! and a letter o ("*5/o") hold a place but give no count.
# "*/1" leaves tested blank. The bulletin does not say what a leading "*" means.
COUNT = re.compile(r"^(\*?)(\d+|#REF!|(?=/\d))(?:/(\d*|[oO]))?/?(?:\(T/P\)?)?$")
# the incidence arrows of 2013-14, printed as Wingdings letters
ARROWS = {"G", "H", "=", "-"}


def disease(label: str) -> str | None:
    """The disease a row label names, or None."""
    text = label.lower()
    return next((name for pat, name in DISEASES if re.search(pat, text)), None)


def split(cells: list) -> tuple[str, list[tuple[float, re.Match]]]:
    """The label words and the counts of a line with their x (arrows dropped)."""
    words, counts = [], []
    for x, text in cells:
        for tok in text.split():
            if tok in ARROWS:
                continue
            m = COUNT.match(tok)
            if m:
                counts.append((x, m))
            else:
                words.append(tok)
    return " ".join(words), counts


def cells_of(name: str, counts: list[tuple[float, re.Match]], page: int) -> Iterator[dict]:
    for col, (_, m) in zip(COLS, counts, strict=True):
        star, first, second = m.groups()
        pair = second is not None
        measures = [("tested", first), ("positive", second)] if pair else [("cases", first)]
        for measure, value in measures:
            if value and value.isdigit():
                yield {
                    "disease": name,
                    "measure": measure,
                    "col": col,
                    "value": value,
                    "page": page,
                }
        if star:
            yield {"disease": name, "measure": "starred", "col": col, "value": "1", "page": page}


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each count keyed by disease, measure and column.

    A label may wrap onto a second line, and the counts may come on a third, on the line
    before the label, or with the last count a line or two below. Each line of four counts
    goes to the disease on its line, else the last one still without counts, else the next."""
    for page_no, lines in pages:
        done: set[str] = set()
        pending: str | None = None  # named, still without counts
        orphan: list[tuple[float, re.Match]] | None = None  # counts before their label
        # a row's first counts, the rest on a later line
        partial: tuple[str | None, list[tuple[float, re.Match]]] | None = None
        for cells in lines:
            label, counts = split(cells)
            name = disease(label)
            if name in done:
                name = None
            if HEADING.search(label):
                counts = []
            if partial and counts and not name and len(partial[1]) + len(counts) <= len(COLS):
                # "10885 10322 113973", then "128379" a line or two down (2013-14);
                # engines differ on which piece comes first, so order them by x
                name, counts = partial[0], sorted(partial[1] + counts, key=lambda c: c[0])
                partial = None
            if 0 < len(counts) < len(COLS):
                partial, pending = (name, counts), name or pending
                continue
            elif len(counts) != len(COLS):
                counts = []
            target: str
            if name and counts:
                target, use = name, counts
            elif counts and pending:
                target, use = pending, counts
            elif counts:
                orphan = counts
                continue
            elif name and orphan:
                target, use = name, orphan
            else:
                pending = name or pending
                continue
            yield from cells_of(target, use, page_no)
            done.add(target)
            pending = None if pending == target else pending
            orphan = None if use is orphan else orphan
