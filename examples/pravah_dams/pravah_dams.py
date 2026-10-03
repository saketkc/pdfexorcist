"""Pravah daily dam-storage report."""

import re
from collections.abc import Iterable, Iterator

import pandas as pd

from pdfexorcist import check
from pdfexorcist.rows import Page, label_key

COLS = [
    "sr",
    "date",
    "time",
    "dead",
    "live_cap",
    "gross_cap",
    "live",
    "gross",
    "pct_live",
    "pct_live_last_year",
]
KEY = ["page", "id", "col"]
NUM = r"(\d+(?:\.\d+)?)"
ROW = re.compile(
    r"^(\d{1,3}) (.+?) (\d\d/\d\d/\d{4}) (\d{1,2}:\d\d ?[AP]M)"
    + rf" {NUM}" * 5
    + rf" {NUM} ?% {NUM} ?%$"
)
HEADER_END = " ".join(str(i) for i in range(1, 12))  # the column-number row under the header


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield values keyed with dam, region, and district."""
    region = district = None
    held: tuple | None = None  # page, name, values, region, district
    loose: list[str] = []  # lines without values since the last row

    def flush(extra: list[str]) -> Iterator[dict]:
        if held is None:
            return
        page_no, name, vals, reg, dist = held
        name = " ".join([name, *extra])
        for col, v in zip(COLS, vals, strict=True):
            yield {
                "page": page_no,
                "id": label_key(name),
                "col": col,
                "value": v,
                "dam": name,
                "region": reg,
                "district": dist,
            }

    for page_no, lines in pages:
        in_table = False
        for cells in lines:
            text = " ".join(t for _, s in cells for t in s.split())
            if not in_table:
                in_table = text == HEADER_END
                continue
            m = ROW.match(text)
            if text.startswith(("Total for", "Grand Total")):
                yield from flush(loose)
                held, loose = None, []
            elif not m:
                if text:
                    loose.append(text)
            elif m.group(1) == "1" and loose:
                headings = [s for s in loose if s.endswith("Region")]
                yield from flush(loose[: loose.index(headings[0])] if headings else loose[:-1])
                if headings:
                    region = headings[-1].removesuffix("Region").strip()
                district = loose[-1]
            else:
                yield from flush(loose)
            if m:
                vals = [m.group(1), *m.groups()[2:]]
                held, loose = (page_no, m.group(2), vals, region, district), []
    yield from flush([])


@check("pct_live = 100 * live / live_cap")
def pct_of_live(df: pd.DataFrame) -> pd.Series:
    """Check live-storage percentages to two decimal places."""
    v = pd.to_numeric(df.value, errors="coerce")
    w = df.assign(v=v).pivot_table(index=["page", "id"], columns="col", values="v", aggfunc="first")
    if not {"pct_live", "live", "live_cap"} <= set(w.columns):
        return pd.Series(False, index=df.index)
    off = (w.pct_live - 100 * w.live / w.live_cap).abs() > 0.005 + 1e-9
    bad = {(p, i, c) for p, i in off[off].index for c in ("pct_live", "live", "live_cap")}
    return pd.Series([k in bad for k in zip(df.page, df.id, df.col, strict=True)], index=df.index)
