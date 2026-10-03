"""NFHS-6 fact sheets."""

import csv
import os
import shutil
from functools import cache
from importlib.util import find_spec
from pathlib import Path

import pandas as pd
import pytest
from nfhs6_factsheet import KEY, at_most_100, checks, parse, total_between_urban_and_rural

from pdfexorcist import extract, validate

HERE = Path(__file__).parent
STATE = HERE / "fixtures" / "nfhs6_state"
DISTRICT = HERE / "fixtures" / "nfhs6_district"
AREA = {"Urban": "nfhs6_urban", "Rural": "nfhs6_rural", "Total": "nfhs6_total"}
OCR_ENGINES = {
    "tesseract": None,
    "chandra": "chandra",
    "glmocr": "mlx_vlm",
    "paddleocr": "paddleocr",
    "ocrmac": "ocrmac",
}  # engine: module (None: a binary)

# Slack for one engine's tokenisation change; a lost row or column still fails.
# PDFium joins a wrapped row's values to its label; camelot reads Jhargram's
# middle page as one cell.
MIN_COVERAGE = 0.97


def _manifest(folder: Path) -> list[dict]:
    return list(csv.DictReader((folder / "manifest.csv").open(encoding="utf-8")))


STATE_MANIFEST = _manifest(STATE)
DISTRICT_MANIFEST = _manifest(DISTRICT)
TEXT_STATES = [m["fixture"] for m in STATE_MANIFEST if m["text_layer"] == "yes"]
OUTLINED_STATES = [m["fixture"] for m in STATE_MANIFEST if m["text_layer"] == "no"]
DISTRICTS = [m["fixture"] for m in DISTRICT_MANIFEST]

Cell = tuple[int, int, str]  # fixture page, indicator number, column


def _expected(folder: Path) -> pd.DataFrame:
    return pd.read_csv(folder / "expected.csv", dtype=str, keep_default_na=False)


def _want(folder: Path, fixture: str) -> dict[Cell, str]:
    """(page, indicator, column) -> the printed value, for one fixture."""
    want: dict[Cell, str] = {}
    for r in _expected(folder)[lambda e: e.fixture == fixture].itertuples():
        cell = (int(r.page), int(r.indicator_no))
        want[(*cell, AREA[r.area])] = r.nfhs6
        if r.nfhs5:
            want[(*cell, "nfhs5_total")] = r.nfhs5
    return want


def _fixed(folder: Path, fixture: str) -> set[Cell]:
    """Cells nfhs6 had to fix (State fix) or that differ from nfhs6 (correction)."""
    e = _expected(folder)
    e = e[e.fixture == fixture]
    out: set[Cell] = set()
    for r in e.itertuples():
        notes = "; ".join(x for x in (getattr(r, "fix", ""), r.correction) if x)
        for col in ("nfhs6_urban", "nfhs6_rural", "nfhs6_total", "nfhs5_total"):
            if f"{col}:" in notes:
                out.add((int(r.page), int(r.indicator_no), col))
    return out


@cache
def _voted(folder: Path, fixture: str) -> pd.DataFrame:
    """extract() with the default text engines, read once per session."""
    return extract(folder / fixture, parse=parse, key=KEY, checks=checks())


def _tally(res: pd.DataFrame, want: dict[Cell, str], name: str) -> dict:
    ok = res[res.status == "verified"]
    got = {
        (int(p), int(n), c): v
        for p, n, c, v in zip(ok.page, ok.indicator_no, ok.column, ok.value, strict=True)
    }
    t = {
        "got": got,
        "wrong": {k: (got[k], v) for k, v in want.items() if k in got and got[k] != v},
        "missing": [k for k in want if k not in got],
        "unexpected": [k for k in got if k not in want],
    }
    tallied = len(want) - len(t["missing"])
    print(
        f"\n{name}: {len(got)} agreed, {tallied} of {len(want)} tallied, {len(t['wrong'])} wrong, "
        f"{len(t['missing'])} missing ({res.n_agree.min()}+ engines per cell)"
    )
    return t


@pytest.mark.parametrize("fixture", TEXT_STATES)
def test_state_tally(fixture: str) -> None:
    """Pin state values, corrections, sheet boundaries, and coverage."""
    want = _want(STATE, fixture)
    t = _tally(_voted(STATE, fixture), want, fixture)
    assert t["wrong"] == {}
    assert t["unexpected"] == []
    assert [k for k in _fixed(STATE, fixture) if k not in t["got"]] == []
    assert len(want) - len(t["missing"]) >= MIN_COVERAGE * len(want)


@pytest.mark.parametrize("fixture", DISTRICTS)
def test_district_tally(fixture: str) -> None:
    """Pin district values, retained cells, and coverage."""
    want = _want(DISTRICT, fixture)
    t = _tally(_voted(DISTRICT, fixture), want, fixture)
    assert t["wrong"] == {}
    assert t["unexpected"] == []
    assert len(want) - len(t["missing"]) >= MIN_COVERAGE * len(want)
    e = _expected(DISTRICT)
    e = e[e.fixture == fixture]
    three = [
        (int(r.page), int(r.indicator_no), col)
        for r in e.itertuples()
        for col, part in zip(
            ("nfhs6_total", "nfhs5_total"), r.repo_sources.split("; "), strict=False
        )
        if part.split(": ")[1].count("|") == 2
    ]
    assert [k for k in three if k not in t["got"]] == []


def test_expected_records_nfhs6_fixes() -> None:
    """Pin all manifest-listed State fixes."""
    e = _expected(STATE)
    fixed = e[e.fix != ""]
    assert sorted(set(zip(fixed.fixture, fixed.indicator_no.astype(int), strict=True))) == sorted(
        [("nfhs6_bihar_p43-45.pdf", n) for n in (19, 59, 97)]
        + [("nfhs6_india_p26-28.pdf", 97)]
        + [("nfhs6_chandigarh_p145-147.pdf", n) for n in _chandigarh_fixed()]
        + [("nfhs6_tamil_nadu_p115.pdf", n) for n in (7, 8, 10, 12, 13, 17, 18, 19, 23, 24, 31, 40)]
    )
    bihar = e[(e.fixture == "nfhs6_bihar_p43-45.pdf") & (e.indicator_no == "19")]
    assert bihar.set_index("area").loc["Urban", "nfhs6"] == "8.9"  # unfixed: 0.9


def _chandigarh_fixed() -> list[int]:
    e = _expected(STATE)
    c = e[(e.fixture == "nfhs6_chandigarh_p145-147.pdf") & (e.fix != "")]
    assert c.fix.str.contains("23_apply_compendium_state_fixes").all()
    return sorted({int(n) for n in c.indicator_no})


def test_printed_values() -> None:
    """Pin printed brackets, placeholders, and whole numbers."""
    chd = _voted(STATE, "nfhs6_chandigarh_p145-147.pdf")
    at = chd.set_index(["page", "indicator_no", "column"]).value
    assert at[(1, 6, "nfhs6_rural")] == "(97.7)"
    assert at[(1, 17, "nfhs5_total")] == "*"
    assert at[(1, 39, "nfhs6_total")] == "(65.0)"
    gpm = _voted(DISTRICT, "nfhs6_gaurela_pendra_marwahi_p59-61.pdf")
    at = gpm.set_index(["page", "indicator_no", "column"]).value
    assert (at[(1, 3, "nfhs6_total")], at[(1, 4, "nfhs6_total")]) == ("12", "99")
    assert set(gpm.column) == {"nfhs6_total"}  # no NFHS-5 column on this sheet


@pytest.mark.parametrize(
    "folder, fixture",
    [(STATE, f) for f in TEXT_STATES] + [(DISTRICT, f) for f in DISTRICTS],
)
def test_sheet_rules_hold(folder: Path, fixture: str) -> None:
    """Pin percentage and total-range rules."""
    res = _voted(folder, fixture)
    assert (res.failed != "").sum() == 0, res[res.failed != ""][[*KEY, "value", "failed"]]
    assert set(res.geo) == {_geo(folder, fixture)}


def _geo(folder: Path, fixture: str) -> str:
    m = next(m for m in _manifest(folder) if m["fixture"] == fixture)
    return m["geography"] if folder == STATE else m["title"]  # as the page prints it


def test_rules_catch_a_misread() -> None:
    """Pin detection of invalid totals and percentages only."""
    ok = _voted(STATE, "nfhs6_india_p26-28.pdf")
    ok = ok[ok.status == "verified"].copy()
    total = ok.index[(ok.indicator_no == 1) & (ok.column == "nfhs6_total")][0]
    ok.loc[total, "value"] = "18.0"  # Urban 6.6, Rural 8.6
    over = ok.index[(ok.indicator_no == 4) & (ok.column == "nfhs6_urban")][0]
    ok.loc[over, "value"] = "995"  # 99.5 with its point lost
    failed = validate(ok, checks()).failed
    assert total_between_urban_and_rural.__name__ in failed[total]
    assert at_most_100.__name__ in failed[over]
    assert (failed != "").sum() == 4  # the two edits and the Urban/Rural beside the Total


def _lines(rows: list[list[tuple[float, str]]]) -> list:
    return [(1, rows)]


def test_parser_on_awkward_lines() -> None:
    """Pin parser handling of difficult engine-shaped rows."""
    head = [(10, "India - Key Indicators")]
    rows = [
        head,
        [
            (10, "1. Population below age 5 years (%)"),
            (140, "6.6"),
            (153, "8.6"),
            (165, "8.0"),
            (179, "8.2"),
        ],
        # a wrapped label: values on their own line, between the label's two lines
        [(10, "2. Population below age 15 years")],
        [(140, "22.0"), (153, "27.0"), (165, "25.5"), (179, "26.5")],
        [(10, "(%)")],
        # a label drawn as graphics: only its number is text; a footnote mark split off
        [(2, "3"), (60, "15"), (140, "12.7"), (153, "(13.0)"), (165, "12.9"), (179, "*")],
        # NFHS-5 a little off the baseline: one value on the line above the rest
        [(10, "4.Population living in households with electricity")],
        [(179, "96.8")],
        [(10, "(%)"), (140, "99.5"), (153, "97.8"), (165, "98.3")],
        # a value missing: the row yields nothing
        [(10, "5. Households using iodized salt (%)"), (140, "99.1"), (153, "95.4"), (179, "95.9")],
        # a page number and a footnote are not rows
        [(80, "4")],
        [(10, "1Piped water into dwelling"), (100, "small tank 10")],
        [
            (10, "1. Repeat of an earlier number (%)"),
            (140, "1.0"),
            (153, "1.0"),
            (165, "1.0"),
            (179, "1.0"),
        ],
    ]
    got = {(r["indicator_no"], r["column"]): r["value"] for r in parse(_lines(rows))}
    assert got == {
        (1, "nfhs6_urban"): "6.6",
        (1, "nfhs6_rural"): "8.6",
        (1, "nfhs6_total"): "8.0",
        (1, "nfhs5_total"): "8.2",
        (2, "nfhs6_urban"): "22.0",
        (2, "nfhs6_rural"): "27.0",
        (2, "nfhs6_total"): "25.5",
        (2, "nfhs5_total"): "26.5",
        (3, "nfhs6_urban"): "12.7",
        (3, "nfhs6_rural"): "(13.0)",
        (3, "nfhs6_total"): "12.9",
        (3, "nfhs5_total"): "*",
        (4, "nfhs6_urban"): "99.5",
        (4, "nfhs6_rural"): "97.8",
        (4, "nfhs6_total"): "98.3",
        (4, "nfhs5_total"): "96.8",
    }


def test_district_column() -> None:
    """Pin wrapped-label numbers as label text in single-column districts."""
    rows = [
        [(237, "Jhargram, West Bengal"), (333, "-"), (394, "Key Indicators")],
        [(239, "41. Mothers who received postnatal care ... within"), (449.6, "2")],
        [(87, "days of delivery+ (%)"), (507.6, "85.3")],
        [
            (188, "42. Children born at home ... within"),
            (349, "24"),
            (389, "hours of birth (%)"),
            (514.2, "*"),
        ],
        [(110, "43. Children who received postnatal care (%)"), (505.0, "(100.0)")],
    ]
    got = [
        (r["indicator_no"], r["column"], r["value"], r["level"], r["geo"])
        for r in parse(_lines(rows))
    ]
    geo = "Jhargram, West Bengal"
    assert got == [
        (41, "nfhs6_total", "85.3", "district", geo),
        (42, "nfhs6_total", "*", "district", geo),
        (43, "nfhs6_total", "(100.0)", "district", geo),
    ]


def _installed() -> list[str]:
    return [
        e for e, mod in OCR_ENGINES.items() if (shutil.which(e) if mod is None else find_spec(mod))
    ]


# Outlined Tamil Nadu page: Tesseract drops decimal points (143 for 14.3), so
# the other OCR engines carry the vote.
OCR_MIN_COVERAGE = 0.95


@pytest.mark.skipif(
    not os.environ.get("PDFEXORCIST_OCR_TESTS"),
    reason="slow OCR test; set PDFEXORCIST_OCR_TESTS=1",
)
@pytest.mark.parametrize("fixture", OUTLINED_STATES)
def test_ocr_vote_on_outlined_page(fixture: str) -> None:
    """Pin OCR values, corrections, coverage, and rules for outlined glyphs."""
    engines = _installed()
    if len(engines) < 3:
        pytest.skip(f"needs 3 OCR engines, found {engines}")
    need = max(2, len(engines) // 2 + 1)  # 3 of 5, 3 of 4, 2 of 3
    res = extract(
        STATE / fixture, methods=engines, parse=parse, key=KEY, min_agree=need, checks=checks()
    )
    want = _want(STATE, fixture)
    t = _tally(res, want, f"{fixture} ({', '.join(engines)}; {need} must agree)")
    assert t["wrong"] == {}
    assert t["unexpected"] == []
    assert [k for k in _fixed(STATE, fixture) if k not in t["got"]] == []
    assert len(want) - len(t["missing"]) >= OCR_MIN_COVERAGE * len(want)
    assert (res.failed != "").sum() == 0
