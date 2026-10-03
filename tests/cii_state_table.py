"""NCRB Crime in India State/UT tables."""

import re
import statistics
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

import pandas as pd

from pdfexorcist import check, total_check
from pdfexorcist.checks import Check
from pdfexorcist.rows import Page, is_value

KEY = ["page", "row", "col"]
HEADER = re.compile(r"^\[(\d+)\]$")
SECTION = re.compile(r"^(STATES|UNION TERRITORIES)\s*:?$", re.I)
WRAPS = ("&", " and", " of")  # a name fragment ending so continues on the next line
DNH = re.compile(r"haveli|daman", re.I)


@dataclass(frozen=True)
class Layout:
    """What one table's columns mean, for its arithmetic checks."""

    counts: tuple[int, ...]  # additive columns: States sum to TOTAL STATE(S), etc.
    sums: tuple[tuple[int, tuple[int, ...]], ...] = ()  # printed "Col.12=Col.15+Col.18"
    rate: tuple[int, int, int] | None = None  # (count col, population col in lakhs, rate col)


def footnote_free(v: str) -> str | None:
    """normalize= hook: drop footnote marks ("490+") and thousands commas."""
    return re.sub(r"[*#@+$]+$", "", v).replace(",", "")


def _tokens(cells) -> list[tuple[float, str]]:
    """Cells -> (x, token); rejoin "32" ".0" that PDFium splits into two runs."""
    out: list[tuple[float, str]] = []
    for x, text in cells:
        for t in re.sub(r"\[\s*(\d+)\s*\]", r"[\1]", text).split():
            if out and re.fullmatch(r"\.\d+", t) and re.fullmatch(r"\d+", out[-1][1]):
                out[-1] = (out[-1][0], out[-1][1] + t)
            else:
                out.append((x, t))
    return out


def _unfinished(name: list[str]) -> bool:
    return bool(name) and name[-1].rstrip().endswith(WRAPS)


def _columns(toks: list[list[tuple[float, str]]], hdr: int) -> list[tuple[int, float]]:
    """(printed column, x) from the "[n]" row, value columns re-centred on full rows."""
    colx = [(int(HEADER.match(s).group(1)), x) for x, s in toks[hdr]]
    n = len(colx) - 2
    full = []
    for line in toks[hdr + 1 :]:
        vals = [
            x
            for i, (x, t) in enumerate(line)
            if is_value(t) and not (i == 0 and re.fullmatch(r"\d{1,2}", t))
        ]
        if len(vals) == n and not any(HEADER.match(t) for _, t in line):
            full.append(vals)
    if len(full) < 5:
        return colx
    centres = [statistics.median(v[i] for v in full) for i in range(n)]
    return colx[:2] + [(c, x) for (c, _), x in zip(colx[2:], centres, strict=True)]


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """One engine's pages -> {page, row, col, name, section, value} readings."""
    for page_no, lines in pages:
        toks = [_tokens(c) for c in lines]
        hdr = next(
            (i for i, t in enumerate(toks) if len(t) >= 3 and all(HEADER.match(s) for _, s in t)),
            None,
        )
        if hdr is None:
            continue  # this engine did not see the column-number row: abstain on the page
        colx = _columns(toks, hdr)
        first_val = sorted(c for c, _ in colx)[2]  # [1] serial, [2] State/UT

        def col_of(x: float, colx: list[tuple[int, float]] = colx) -> int:
            return min(colx, key=lambda cx: abs(cx[1] - x))[0]

        recs: list[dict] = []
        cur: dict | None = None
        pending: list[str] = []  # value-less name text not yet given to a row
        section = "state"
        for line in toks[hdr + 1 :]:
            serial, name, vals = None, [], {}
            for i, (x, t) in enumerate(line):
                c = col_of(x)
                lead = (
                    i == 0 and c < first_val and re.fullmatch(r"\d{1,2}", t)
                )  # "13 Madhya Pradesh"
                if lead and serial is None:
                    serial = t
                elif c >= first_val and is_value(t):
                    vals.setdefault(c, t)
                elif not is_value(t):
                    name.append(t)
            text = " ".join(name)
            if SECTION.match(text) or (cur and cur["row"] == "totalallindia" and text):
                if cur is not None and pending:
                    cur["name"] += pending
                pending = []
                if cur and cur["row"] == "totalallindia":
                    break  # notes under the table
                continue
            is_total = text.upper().startswith("TOTAL")
            if serial or is_total:
                if pending and cur is not None and not _unfinished(pending):
                    cur["name"] += pending  # "Daman & Diu" finishes the row above
                    pending = []
                row = re.sub(r"[^a-z]", "", text.lower()) if is_total else serial
                cur = {
                    "row": row,
                    "name": pending + ([text] if text else []),
                    "vals": vals,
                    "section": "total" if is_total else section,
                }
                pending = []
                recs.append(cur)
                section = "ut" if row == "totalstates" else section
                continue
            if cur is None:
                continue
            if text and not vals:
                pending.append(text)  # wrapped name: of the row above or the one below
                continue
            for c, v in vals.items():
                cur["vals"].setdefault(c, v)  # a value on a slightly lower baseline
        for r in recs:
            for c, v in r["vals"].items():
                yield {
                    "page": page_no,
                    "row": r["row"],
                    "col": c,
                    "name": " ".join(r["name"]),
                    "section": r["section"],
                    "value": v,
                }


def _num(df: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(df.value, errors="coerce")


def rate_check(count: int, pop: int, rate: int) -> Check:
    """rate = count / population (lakhs), allowing for the printed population's rounding."""

    @check(f"col {rate} = col {count} / col {pop}")
    def fn(df: pd.DataFrame) -> pd.Series:
        w = df.assign(v=_num(df)).pivot_table(
            index=["page", "row"], columns="col", values="v", aggfunc="first"
        )
        if not {count, pop, rate} <= set(w.columns):
            return pd.Series(False, index=df.index)
        tol = 0.051 + w[count] * 0.05 / w[pop] ** 2  # population printed to 0.1 lakh
        bad = ((w[count] / w[pop] - w[rate]).abs() > tol) & (w[pop] > 0)
        bad = set(bad[bad].index)
        return pd.Series(
            [
                (p, r) in bad and c in (count, pop, rate)
                for p, r, c in zip(df.page, df.row, df.col, strict=True)
            ],
            index=df.index,
        )

    return fn


def checks(layout: Layout) -> list[Check]:
    """The table's own arithmetic, as pdfexorcist checks."""
    counts = list(layout.counts)
    by = ["page", "col"]
    out: list[Check] = [
        total_check(
            "row",
            "totalstates",
            by=by,
            where=f"(section == 'state' or row == 'totalstates') and col in {counts}",
        ),
        total_check(
            "row",
            "totaluts",
            by=by,
            where=f"(section == 'ut' or row == 'totaluts') and col in {counts}",
        ),
        total_check(
            "row",
            "totalallindia",
            ["totalstates", "totaluts"],
            by=by,
            where=f"col in {counts}",
        ),
    ]
    out += [total_check("col", t, list(parts), by=["page", "row"]) for t, parts in layout.sums]
    if layout.rate:
        count, pop, rate = layout.rate
        # populations are printed to 0.1 lakh, so their sums are off by rounding
        out.append(
            total_check(
                "row",
                "totalallindia",
                ["totalstates", "totaluts"],
                by=by,
                where=f"col == {pop}",
                abs_tol=0.15,
                name=f"col {pop}: States + UTs = All India",
            )
        )
        out.append(rate_check(count, pop, rate))
    return out


def dnh_rows(res: pd.DataFrame) -> Sequence[str]:
    """Row keys whose agreed name is the DNH&DD UT's."""
    return sorted(set(res.row[res.name.str.contains(DNH, na=False)]))
