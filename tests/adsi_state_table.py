"""NCRB ADSI State/UT tables."""

import re
import statistics
from collections.abc import Callable, Iterable, Iterator
from itertools import pairwise

import pandas as pd

from pdfexorcist import check, total_check
from pdfexorcist.checks import Check
from pdfexorcist.rows import Page

KEY = ["page", "row", "col"]
Tok = tuple[float, str]
HEADER = re.compile(r"^[\(\[](\d+)[\)\]]$")  # (1)
SECTION = re.compile(r"^(STATES|UNION TERRITORIES|CITIES)\s*:?$", re.I)
UNFINISHED = re.compile(r"(&|\band|\bof)$", re.I)  # "D & N HAVELI AND" continues on the next line
# "12", "1.", "2ARUNACHAL", "4BIHAR"; not "1801554", nor "1O KARNATAKA"
# (10: a look-alike letter ending the token)
SERIAL = re.compile(r"^(\d{1,2})\.?(?=\s|$|[AC-HJ-NP-RT-Ya-km-z]|[BIOSZlo][A-Za-z])")
NOISE = "\"'*:;|‘’“”[]{}"  # OCR marks around a number (dotted leaders, quotes); never digits or "."
TOL = 0.45  # a value must lie within TOL x column spacing of its column centre

# printed column number -> metric; values start at column (3)
METRICS: dict[str, dict[int, str]] = {
    "1.2": {
        3: "nature",
        4: "other",
        5: "total",
        6: "share",
        7: "pop",
        8: "rate",
    },  # 2014 on
    "2.2": {3: "total", 4: "share", 5: "pop", 6: "rate"},
    "2(A)": {3: "total", 4: "share", 5: "pop", 6: "rate"},  # 1995
}


def row_key(name: str) -> str:
    """Letters only: 'TOTAL (ALL INDIA)' -> 'totalallindia', 'A & N ISLANDS' -> 'anislands'."""
    return re.sub(r"[^a-z]", "", name.lower())


def _tokens(cells: list[Tok]) -> list[Tok]:
    """Yield positioned tokens, rejoining PDFium-split decimals and header numbers."""
    out: list[Tok] = []
    for x, text in cells:
        for t in re.sub(r"\(\s*(\d+)\s*\)", r"(\1)", text).split():  # "( 5 )" in one run
            if out and re.fullmatch(r"\.\d+", t) and re.fullmatch(r"\d+", out[-1][1]):
                out[-1] = (out[-1][0], out[-1][1] + t)
            elif t == ")" and len(out) >= 2 and out[-2][1] == "(" and out[-1][1].isdigit():
                out[-2:] = [(out[-1][0], f"({out[-1][1]})")]  # x of the digit: the column centre
            else:
                out.append((x, t))
    return out


def _is_header(line: list[Tok]) -> bool:
    """The column-number row: at least 3 "(n)" tokens and little else ("(1)(2)" glued by OCR)."""
    n = sum(bool(HEADER.match(s)) for _, s in line)
    return n >= 3 and n >= 0.75 * len(line)


def _value(t: str) -> str | None:
    """A number token without OCR marks around it ('5.53"]' -> '5.53'), or None."""
    t = t.strip(NOISE).replace(",", "")
    return t if re.fullmatch(r"\d+(\.\d+)?", t) else None


def _centres(lines: list[list[Tok]], k: int) -> list[float] | None:
    """Median x of the i-th value over lines whose trailing run is exactly k values."""
    full = []
    for line in lines:
        i = len(line)
        while i and _value(line[i - 1][1]) is not None:
            i -= 1
        if len(line) - i == k:
            full.append(line[i:])
    if len(full) < 3:
        return None  # too few complete rows to place columns: the engine abstains
    return [statistics.median(v[i][0] for v in full) for i in range(k)]


def _split(line: list[Tok], centres: list[float]) -> tuple[str | None, str, dict[int, str]]:
    """A line -> (serial, label text, {value index: value}); None values mark a dropped cell."""
    spacing = min((b - a for a, b in pairwise(centres)), default=1.0) or 1.0
    label: list[str] = []
    placed: dict[int, list[str | None]] = {}
    for x, t in line:
        if x < centres[0] - TOL * spacing:
            label.append(t)
            continue
        c = min(range(len(centres)), key=lambda i: abs(centres[i] - x))
        if abs(centres[c] - x) <= TOL * spacing and t.strip(NOISE):
            placed.setdefault(c, []).append(_value(t))
    vals = {c: v[0] for c, v in placed.items() if len(v) == 1 and v[0] is not None}
    text = " ".join(label).lstrip(NOISE + " .,-")
    serial = None
    if m := SERIAL.match(text):
        serial, text = str(int(m.group(1))), text[m.end() :].lstrip(NOISE + " .")
    return serial, text, vals


def _records(lines: list[list[Tok]], centres: list[float]) -> list[dict]:
    """Table lines -> rows {serial, name parts, {value index: value}, section}."""
    recs: list[dict] = []
    cur: dict | None = None
    pending: list[str] = []  # name lines waiting for their row
    section = "state"
    for line in lines:
        serial, text, vals = _split(line, centres)
        if SECTION.match(text):
            pending = []
            continue
        is_total = text.upper().startswith("TOTAL")
        if serial or is_total:
            # a complete wrapped name ("DAMAN & DIU") finishes the row above
            if pending and text and cur is not None and not UNFINISHED.search(pending[-1]):
                cur["name"] += pending
                pending = []
            cur = {
                "serial": None if is_total else serial,
                "name": pending + ([text] if text else []),
                "vals": dict(vals),
                "section": "total" if is_total else section,
            }
            pending = []
            recs.append(cur)
            section = "ut" if is_total and "STATE" in text.upper() else section
            if is_total and "INDIA" in text.upper():
                break  # notes, or the cities that follow the State/UT rows
            continue
        if cur is None:
            continue
        incomplete = len(cur["vals"]) < len(centres) - 1  # one blank allowed
        if text and not vals and (not incomplete or UNFINISHED.search(text)):
            pending.append(text)  # wrapped name of the next row
            continue
        if text:
            cur["name"].append(text)
        if not cur[
            "vals"
        ]:  # values printed beside a wrapped name; never into a row that has its own
            cur["vals"] = dict(vals)
    return recs


def make_parser(table: str) -> Callable[[Iterable[Page]], Iterator[dict]]:
    """Parser for one State/UT table layout (a key of METRICS) on every page."""
    metrics = METRICS[table]
    first = min(metrics)

    def parse(pages: Iterable[Page]) -> Iterator[dict]:
        for page_no, lines in pages:
            toks = [_tokens(c) for c in lines]
            # the table starts below the column-number row, else below "STATES"
            start = next((i for i, t in enumerate(toks) if _is_header(t)), None)
            if start is None:
                start = next(
                    (i for i, t in enumerate(toks) if SECTION.match(" ".join(s for _, s in t))),
                    None,
                )
            if start is None:
                continue  # no table seen: this engine abstains on the page
            body = toks[start + 1 :]
            centres = _centres(body, len(metrics))
            if centres is None:
                continue
            for r in _records(body, centres):
                name = " ".join(r["name"])
                for i, v in r["vals"].items():
                    yield {
                        "page": page_no,
                        "row": r["serial"] or row_key(name),
                        "col": first + i,
                        "name": name,
                        "section": r["section"],
                        "metric": metrics[first + i],
                        "value": v,
                    }

    return parse


def _wide(df: pd.DataFrame) -> pd.DataFrame:
    v = pd.to_numeric(df.value, errors="coerce")
    return df.assign(v=v).pivot_table(
        index=["page", "row"], columns="metric", values="v", aggfunc="first"
    )


def _flag(df: pd.DataFrame, bad: pd.Series, metrics: tuple[str, ...]) -> pd.Series:
    """Rows (page, row) where bad is True -> True on their cells of the given metrics."""
    bad = set(bad[bad].index)
    return pd.Series(
        [
            (p, r) in bad and m in metrics
            for p, r, m in zip(df.page, df.row, df.metric, strict=True)
        ],
        index=df.index,
    )


@check("rate = total / pop")
def rate_ok(df: pd.DataFrame) -> pd.Series:
    w = _wide(df)
    if not {"rate", "total", "pop"} <= set(w.columns):
        return pd.Series(False, index=df.index)
    # NCRB divides by the unrounded population: allow its ±0.05 rounding too
    tol = 0.051 + w["total"] * 0.05 / w["pop"] ** 2
    return _flag(
        df,
        ((w["total"] / w["pop"] - w["rate"]).abs() > tol) & (w["pop"] > 0),
        ("rate", "total", "pop"),
    )


@check("share = total / all-India (±0.051)")
def share_ok(df: pd.DataFrame) -> pd.Series:
    w = _wide(df)
    if not {"share", "total"} <= set(w.columns):
        return pd.Series(False, index=df.index)
    india = w.total[[r for r in w.index if "india" in r[1]]].groupby(level=0).first()
    expect = w.total / w.index.get_level_values(0).map(india).values * 100
    return _flag(df, (expect - w.share).abs() > 0.051, ("share",))


def adsi_checks() -> list[Check]:
    """Return State, UT, cause, rate, share, and sex-total checks."""
    counts = "metric in ['nature', 'other', 'total']"
    by = ["page", "col"]
    return [
        total_check(
            "row",
            "totalstates",
            by=by,
            where=f"(section == 'state' or row == 'totalstates') and {counts}",
        ),
        total_check(
            "row",
            "totaluts",
            by=by,
            where=f"(section == 'ut' or row == 'totaluts') and {counts}",
        ),
        total_check(
            "row",
            "totalstates",
            by=by,
            rel_tol=0.0005,
            where="(section == 'state' or row == 'totalstates') and metric == 'pop'",
        ),
        total_check(
            "row",
            "totaluts",
            by=by,
            rel_tol=0.0005,
            where="(section == 'ut' or row == 'totaluts') and metric == 'pop'",
        ),
        total_check(
            "row",
            "totalallindia",
            ["totalstates", "totaluts"],
            by=by,
            rel_tol=0.0005,
            where="metric in ['nature', 'other', 'total', 'pop', 'share']",
        ),
        total_check("metric", "total", ["nature", "other"], by=["page", "row"]),
        rate_ok,
        share_ok,
    ]
