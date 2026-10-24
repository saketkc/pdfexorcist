"""Geometry and caption rules shared by the AMRSN readers."""

import re

from pdfexorcist.cells import Box

Word = tuple[str, Box]  # text, box

# The capital letter after the number stops a match on "Table 6.16 and".
# The 2017 report uses roman numerals ("Table iii.").
CAPTION = re.compile(
    r"^\s*Table\s*-?\s*(\d+(?:\.\d+)*(?:\s?[A-Za-z])?|[ivxIVX]{1,4}(?=\s*[:.]))\s*[:.\-]?\s*[A-Z(]"
)
# "Table- 7.19 A:" (2023) is a caption too
TABLE_START = re.compile(r"^\s*Table\s*-?\s*(\d|[ivx]{1,4}\s*[:.])", re.I)
END = re.compile(
    r"^\s*(Fig(ure|\.)|Source|Note|Clinical relevance)", re.I
)  # what ends a table below its caption
FOOT = re.compile(r"Surveillance\s+Network|Council\s+of\s+Medical", re.I)  # the running footer
GAP = 6  # points between the words of one cell


def cx(b: Box) -> float:
    return (b[0] + b[2]) / 2


def cy(b: Box) -> float:
    return (b[1] + b[3]) / 2


def lines_of(words: list[Word]) -> list[list[Word]]:
    """Words grouped into lines by their middle, each left to right.

    Engines split a ruled row into lines differently, so lines come from the boxes.
    """
    out: list[list[Word]] = []
    for w in sorted(words, key=lambda w: cy(w[1])):
        if out and abs(cy(w[1]) - cy(out[-1][0][1])) < 3:
            out[-1].append(w)
        else:
            out.append([w])
    return [sorted(ws, key=lambda w: w[1][0]) for ws in out]


def chunks(line: list[Word]) -> list[Word]:
    """A line's words joined into cells where the gap is a space."""
    out: list[Word] = []
    for t, b in line:
        if out and b[0] - out[-1][1][2] < GAP:
            pt, pb = out[-1]
            out[-1] = (f"{pt} {t}", (pb[0], min(pb[1], b[1]), b[2], max(pb[3], b[3])))
        else:
            out.append((t, b))
    return out


def edges(values: list[float]) -> list[float]:
    """Values within 3 points of the one before as one."""
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > 3:
            out.append(v)
    return out


def spans(boxes: list[Box], slack: float) -> list[tuple[float, float]]:
    """Column spans: x-ranges merged where the next starts before the last ends + slack."""
    out: list[list[float]] = []
    for b in sorted(boxes, key=lambda b: b[0]):
        if out and b[0] < out[-1][1] + slack:
            out[-1][1] = max(out[-1][1], b[2])
        else:
            out.append([b[0], b[2]])
    return [(a, z) for a, z in out]


def norm(text: str) -> str:
    """Spaces collapsed, and a word broken after its hyphen glued ("Piperacillin- tazobactam")."""
    return re.sub(r"(?<=[A-Za-z])- (?=[a-z])", "-", re.sub(r"\s+", " ", text)).strip()
