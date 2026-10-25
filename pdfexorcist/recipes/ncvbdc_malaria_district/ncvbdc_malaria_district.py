"""NCVBDC malaria annual report: the epidemiological situation of each district, 2010-2024.

Each State/UT block of district rows ends in its Total row ("Assam Total"); most years end
with a page of State/UT rows closed by the India row. Rows are keyed by block (the State,
numbered when it recurs) and serial number, or by name before 2017, when rows had none.
"""

import statistics
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from itertools import pairwise

from ncvbdc_malaria_layouts import (
    INDIA,
    INTEGER,
    LAYOUTS,
    NOISE,
    NOT_COUNTS,
    REPORT_TITLE,
    SERIAL,
    STATE_TITLE,
    TOTAL,
    complete,
    row_label,
    state_name,
    unglue,
    without_state,
)

from pdfexorcist.cells import word_xs
from pdfexorcist.rows import Page, is_value, label_key

Value = tuple[float, str]


@dataclass
class _Band:
    """The lines of one row: label pieces, the name lines above it, and its values."""

    page: int
    labels: list[str]
    pending: list[str]
    values: list[Value] = field(default_factory=list)


def _split(cells: list) -> tuple[str, list[Value]]:
    """A line's label and its trailing values, each with its x."""
    words = word_xs(cells)
    # a letter o printed for a zero between two numbers (2021, Manipur)
    words = [
        (x, "0") if w in ("o", "O") and 0 < k < len(words) - 1
        and is_value(words[k - 1][1]) and is_value(words[k + 1][1]) else (x, w)
        for k, (x, w) in enumerate(words)
    ]  # fmt: skip
    i = len(words)
    while i and is_value(words[i - 1][1]):
        i -= 1
    label, values = " ".join(w for _, w in words[:i]), words[i:]
    text, vals = unglue(label, [v for _, v in values])
    if len(vals) > len(values):  # a value split off the label, just left of the rest
        x = values[0][0] - 1 if values else words[-1][0]
        values = [(x, vals[0]), *values]
    return text, values


def _target(pages: list[Page]) -> int:
    """The commonest row length of a layout: which layout this report has."""
    counts: Counter[int] = Counter()
    for _, lines in pages:
        for cells in lines:
            n = len(complete([v for _, v in _split(cells)[1]]))
            if n in LAYOUTS:
                counts[n] += 1
    return counts.most_common(1)[0][0] if counts else 0


def _place(values: list[Value], centres: list[float], n: int) -> list[str | None] | None:
    """Values of a row with blank cells, each at the column whose x is nearest."""
    if len(centres) != n:
        return None
    at = [min(range(n), key=lambda i: abs(centres[i] - x)) for x, _ in values]
    if any(b <= a for a, b in pairwise(at)):
        return None
    out: list[str | None] = [None] * n
    for i, (_, v) in zip(at, values, strict=True):
        out[i] = v
    return out


class _Reader:
    """Rows of one engine's reading, held until their block closes.

    The State comes from the block's title ("State: Assam", "Situation Report of Assam
    2017") or its Total row (2023, 2024).
    """

    def __init__(self, target: int) -> None:
        self.n = target
        self.title = ""
        self.blocks: dict[str, int] = {}
        self.held: list[dict] = []

    def page(self, page_no: int, lines: list) -> Iterator[dict]:
        items: list[_Band | str] = []  # bands, and State titles between them
        band: _Band | None = None
        pending: list[str] = []
        for cells in lines:
            text = " ".join(t for _, t in cells).strip()
            label, values = _split(cells)
            n = len(complete([v for _, v in values]))
            m, r = STATE_TITLE.search(text), REPORT_TITLE.search(text)
            if n not in LAYOUTS and (m or r):
                items.append((m[1] if m else state_name(r[1] if r else "")) or "India")
                band, pending = None, []
            elif not values:
                if band and not any(band.labels) and SERIAL.match(label):
                    band.labels.append(label)  # serial and name below the values (2021)
                elif (
                    band
                    and len(band.values) < self.n
                    and not NOISE.search(text)
                    and (not TOTAL.search(label))
                ):
                    band.labels.append(label)  # the rest of a wrapped name
                elif NOISE.search(text) or not any(c.isalpha() for c in text):
                    band, pending = None, []
                else:
                    band, pending = None, [*pending, label][-4:]
            elif NOISE.search(label) and not TOTAL.search(label) and len(values) < self.n - 3:
                continue  # "Page 2 of 15", a footer's year: not part of the row above
            elif band and not label and len(values) == 1 and self._serial_below(band, values):
                band.labels.insert(0, values[0][1])  # "29" on the line below its row (2021)
            elif band and self._continues(band, label, values):
                band.labels.append(label)  # the rest of a row printed over two lines
                band.values += values
            else:
                band = self._start(page_no, label, values, pending)
                items.append(band)
                pending = []
        yield from self._emit(items)

    def _continues(self, band: _Band, label: str, values: list[Value]) -> bool:
        """Whether a line holds more of the row before it (2021: cells at different heights).

        Such a row runs over the lines up to the next serial number.
        """
        room = self.n + (0 if band.labels[0] else 1)  # its serial may be among the values
        return (
            len(band.values) < self.n
            and len(band.values) + len(values) <= room
            and not (SERIAL.match(label) and any(band.labels))
        )

    def _serial_below(self, band: _Band, values: list[Value]) -> bool:
        return (
            INTEGER.match(values[0][1]) is not None
            and len(band.values) == self.n
            and not SERIAL.match(band.labels[0])
        )

    def _start(self, page_no: int, label: str, values: list[Value], pending: list) -> _Band:
        if SERIAL.match(label) and len(values) == self.n + 1 and INTEGER.match(values[0][1]):
            label, values = f"{label} {values[0][1]}", values[1:]  # "North 24 Parganas"
        return _Band(page_no, [label], pending, values)

    def _serial(self, band: _Band, ordered: list[Value], left: float) -> list[Value]:
        """A row without a label whose first value is its serial: one value too many, or
        one left of the first column."""
        if band.labels[0] or len(ordered) < 2 or not INTEGER.match(ordered[0][1]):
            return ordered
        if len(ordered) == self.n + 1 or ordered[0][0] < left:
            band.labels = [ordered[0][1], *band.labels[1:]]
            return ordered[1:]
        return ordered

    def _emit(self, items: list) -> Iterator[dict]:
        bands = [b for b in items if isinstance(b, _Band)]
        full = [sorted(b.values) for b in bands if len(b.values) == self.n and any(b.labels)]
        full += [sorted(b.values)[1:] for b in bands if len(b.values) == self.n + 1]
        xs = [[x for x, _ in vals] for vals in full]
        centres = [statistics.median(c) for c in zip(*xs, strict=True)] if xs else []
        # left of the first column by more than the gap to the second
        left = 2 * centres[0] - centres[1] if len(centres) > 1 else -1e9
        for item in items:
            if isinstance(item, str):
                if self.held and item != self.title:
                    # the last State's Total row was not read: keep its rows apart
                    yield from self._close(self.held[-1]["page"], self.title, None)
                self.title = item
                continue
            ordered = self._serial(item, sorted(item.values, key=lambda v: v[0]), left)
            values: list[str | None] | None = complete([v for _, v in ordered])
            label = " ".join(x for x in item.labels if x)
            if len(values) != self.n:
                # up to three blank cells; not a stray line ("Page 1 of 15")
                ok = len(ordered) >= max(5, self.n - 3) and not NOISE.search(label)
                values = _place(ordered, centres, self.n) if ok else None
            if values is None:
                continue
            if not label and not item.pending and self.n > 8:
                label = "Total"  # 2022's India row prints no label
            bare = not label or bool(SERIAL.fullmatch(label) and not SERIAL.match(label)[2])
            if bare and item.pending and TOTAL.search(item.pending[-1]):
                label = item.pending[-1]  # "State Total" on the line above (2018)
            m = SERIAL.match(label)
            # a Total row closes its block ("State Total", "0 State Total" in 2017), but
            # "1 Andhra Pradesh Total" is a State's row on the India page (2023)
            if TOTAL.search(label) and not (m and state_name(m[2])):
                yield from self._close(item.page, m[2] if m else label, values)
                continue
            serial, name = row_label(item.pending, label)
            if row := serial or label_key(name):
                self.held.append(
                    {"page": item.page, "row": row, "sno": serial, "name": name, "values": values}
                )

    def _close(self, page_no: int, label: str, values: list | None) -> Iterator[dict]:
        state = "India" if INDIA.search(label) else state_name(label)
        state = state or self.title or "India"
        key = label_key(state)
        n = self.blocks.get(key, 0)
        self.blocks[key] = n + 1
        block = f"{key}#{n}" if n else key
        total = {"page": page_no, "row": "Total", "sno": "", "name": "Total", "values": values}
        for r in [*self.held, *([total] if values is not None else [])]:
            name = r["name"]
            if LAYOUTS[len(r["values"])][0] == "2024" and r["row"] != "Total":
                name = without_state(name, state)
            yield from _cells(r | {"name": name}, block, state)
        self.held = []


def _cells(r: dict, block: str, state: str) -> Iterator[dict]:
    layout, cols = LAYOUTS[len(r["values"])]
    for col, value in zip(cols, r["values"], strict=True):
        if value is None:
            continue
        yield {
            "block": block,
            "row": r["row"],
            "col": col,
            "value": value,
            "state": state,
            "district": r["name"],
            "sno": r["sno"],
            "layout": layout,
            "kind": "rate" if col in NOT_COUNTS else "count",
            "page": r["page"],
        }


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each value keyed by block, row and column."""
    pages = list(pages)
    reader = _Reader(_target(pages))
    for page_no, lines in pages:
        yield from reader.page(page_no, lines)
