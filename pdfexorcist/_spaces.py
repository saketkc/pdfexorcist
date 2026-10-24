"""Space glyphs drawn on top of visible glyphs (letter-spaced or justified text)."""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any


def overprinted_spaces(chars: Iterable[Mapping[str, Any]]) -> set[int]:
    """Return the ids of space chars whose centre lies inside a visible glyph on their line.

    chars are dicts with text, x0, x1 and top (pdfplumber's char keys). Such a
    space splits "duck" into "d u c k" for an engine that breaks words at spaces.
    The centre must lie a quarter of the space's width inside: an italic "f" overhangs the
    space before it ("Enterococcus faecalis").
    """
    chars = list(chars)
    lines: defaultdict[int, list[tuple[float, float]]] = defaultdict(list)
    for c in chars:
        if c["text"] != " ":
            lines[round(c["top"])].append((c["x0"], c["x1"]))
    stray = set()
    for c in chars:
        if c["text"] == " ":
            mid = (c["x0"] + c["x1"]) / 2
            inset = (c["x1"] - c["x0"]) / 4
            near = (lines.get(round(c["top"]) + d, ()) for d in (-2, -1, 0, 1, 2))
            if any(a + inset < mid < b - inset for ln in near for a, b in ln):
                stray.add(id(c))
    return stray
