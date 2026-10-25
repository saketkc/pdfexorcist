"""Cells that carry their page position."""

import re
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing_extensions import Self

Box = tuple[float, float, float, float]


def _inside(box: tuple, x0: float, y0: float, x1: float, y1: float) -> bool:
    """Test whether a box center lies inside box."""
    return box[0] <= (x0 + x1) / 2 <= box[2] and box[1] <= (y0 + y1) / 2 <= box[3]


class BoxCell(tuple[float, str]):
    """An (x, text) cell with an optional box; equal to, and unpacks like, (x, text)."""

    box: Box | None

    def __new__(cls, x: float, text: str, box: Box | None = None) -> "Self":
        self = super().__new__(cls, (x, text))
        self.box = box
        return self

    def __getnewargs__(self) -> tuple[float, str, Box | None]:
        return (self[0], self[1], self.box)  # pickle/copy keep the box


def cell_box(cell: Sequence) -> Box | None:
    """The cell's box, or None for a plain (x, text) tuple."""
    return getattr(cell, "box", None)


def union(boxes: Sequence[Box | None]) -> Box | None:
    """Smallest box holding every given box (None when any is missing)."""
    if not boxes or any(b is None for b in boxes):
        return None
    bs: list[Box] = [b for b in boxes if b is not None]
    return (
        min(b[0] for b in bs),
        min(b[1] for b in bs),
        max(b[2] for b in bs),
        max(b[3] for b in bs),
    )


def token_boxes(
    cells: Sequence[Sequence],
) -> Iterator[tuple[float, str, Box | None]]:
    """Yield positioned whitespace tokens from cells."""
    for cell in cells:
        x, text = cell[0], cell[1]
        box = cell_box(cell)
        width = max(len(text), 1)
        for m in re.finditer(r"\S+", text):
            tb = None
            if box is not None:
                x0, y0, x1, y1 = box
                tb = (
                    x0 + (x1 - x0) * m.start() / width,
                    y0,
                    x0 + (x1 - x0) * m.end() / width,
                    y1,
                )
            yield x, m.group(), tb


def word_xs(cells: Sequence[Sequence]) -> list[tuple[float, str]]:
    """Each word with its x; a cell of several words is spread over its width.

    Without a box the engine's unit is taken to be a character (pdftotext).
    """
    out: list[tuple[float, str]] = []
    for cell in cells:
        x, text = cell[0], cell[1]
        words = list(re.finditer(r"\S+", text))
        if len(words) == 1:
            out.append((x, words[0].group()))
            continue
        box = cell_box(cell)
        x0, width = (box[0], box[2] - box[0]) if box else (x - len(text) / 2, len(text))
        for m in words:
            mid = (m.start() + m.end()) / 2 / max(len(text), 1)
            out.append((x0 + width * mid, m.group()))
    return out
