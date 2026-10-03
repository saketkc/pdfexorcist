"""Per-engine readings and their positions."""

import bisect
import re
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pandas as pd

from .cells import Box, token_boxes

Page = tuple[int, list]


@dataclass
class Readings:
    """Pre-vote engine frames and source lines."""

    frames: list[pd.DataFrame] = field(default_factory=list)
    lines: dict[str, list[Page]] = field(default_factory=dict)
    pdf: bytes | None = None  # the file the engines read: pages cut, image wrapped, boxes grown

    @property
    def cells(self) -> pd.DataFrame:
        """Return one row per reading; box is None when unknown."""
        if not self.frames:
            return pd.DataFrame(columns=["method", "value", "box"])
        df = pd.concat(self.frames, ignore_index=True)
        if "box" not in df.columns:
            df["box"] = None
        boxes = [b if isinstance(b, tuple) else None for b in df["box"]]
        df["box"] = pd.Series(boxes, index=df.index, dtype=object)
        return df

    def page_lines(self, method: str, page: int = 1) -> list:
        """Return one engine's page lines, or an empty list."""
        return next((ls for p, ls in self.lines.get(method, []) if p == page), [])


_NUM_JUNK = re.compile(r"[,\s*#@$+†‡%()]")


def _number(text: str) -> float | None:
    t = _NUM_JUNK.sub("", str(text)).replace("−", "-").replace("·", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _canon(text: str) -> tuple:
    n = _number(text)
    return ("n", n) if n is not None else ("s", str(text).strip())


def same_value(
    token: str, value: str, normalize: Callable[[str], str | None] | None = None
) -> bool:
    """Return whether numeric spellings denote the same value."""
    want = _canon(value)
    if _canon(token) == want:
        return True
    norm = normalize(token) if normalize is not None else None
    return norm is not None and _canon(norm) == want


def locate(
    values: Sequence[str],
    lines: list,
    normalize: Callable[[str], str | None] | None = None,
) -> list[Box | None]:
    """Locate each value among one engine's words; missing boxes are None."""
    toks = [(t, b) for line in lines for _, t, b in token_boxes(line) if b is not None]
    where: dict[tuple, list[int]] = {}
    for i, (t, _) in enumerate(toks):
        keys = {_canon(t)}
        norm = normalize(t) if normalize is not None else None
        if norm is not None:
            keys.add(_canon(norm))
        for k in keys:
            where.setdefault(k, []).append(i)
    used = [False] * len(toks)
    out: list[Box | None] = []
    pos = 0
    for v in values:
        cands = where.get(_canon(v), [])
        start = bisect.bisect_left(cands, pos)
        ahead = next((i for i in cands[start:] if not used[i]), None)
        hit = ahead if ahead is not None else next((i for i in cands if not used[i]), None)
        if ahead is not None:
            pos = ahead + 1
        if hit is None:
            out.append(None)
            continue
        used[hit] = True
        out.append(toks[hit][1])
    return out


def consensus(boxes: Sequence[Box | None]) -> Box | None:
    """Return the median box, or None for no boxes."""
    bs = [b for b in boxes if b is not None]
    if not bs:
        return None
    return tuple(statistics.median(b[i] for b in bs) for i in range(4))  # type: ignore[return-value]
