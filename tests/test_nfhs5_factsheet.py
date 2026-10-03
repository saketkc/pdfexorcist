"""NFHS-5 fact sheets."""

import csv
from functools import cache
from pathlib import Path

import pandas as pd
import pytest
from nfhs5_factsheet import KEY, at_most_100, checks, parse, total_between_urban_and_rural

from pdfexorcist import extract, validate

HERE = Path(__file__).parent
STATE = HERE / "fixtures" / "nfhs5_state"
DISTRICT = HERE / "fixtures" / "nfhs5_district"
STATE_COLS = ("nfhs5_urban", "nfhs5_rural", "nfhs5_total", "nfhs4_total")
DISTRICT_COLS = ("nfhs5_total", "nfhs4_total")

# Slack for one engine's tokenisation change; a lost row or column still fails.
# Chandigarh's row 68 goes unagreed (camelot reads it with row 40's numbers).
MIN_COVERAGE = 0.97


def _manifest(folder: Path) -> list[dict]:
    return list(csv.DictReader((folder / "manifest.csv").open(encoding="utf-8")))


STATES = [m["fixture"] for m in _manifest(STATE)]
DISTRICTS = [m["fixture"] for m in _manifest(DISTRICT)]

Cell = tuple[int, int, str]  # fixture page, printed indicator number, column


def _expected(folder: Path, fixture: str) -> pd.DataFrame:
    e = pd.read_csv(folder / "expected.csv", dtype=str, keep_default_na=False)
    return e[e.fixture == fixture]


def _want(folder: Path, fixture: str) -> dict[Cell, str]:
    """(page, indicator, column) -> the printed value, for one fixture."""
    cols = STATE_COLS if folder == STATE else DISTRICT_COLS
    return {
        (int(r["page"]), int(r["indicator_no"]), c): r[c]
        for r in _expected(folder, fixture).to_dict("records")
        for c in cols
        if r[c]
    }


def _differing(folder: Path, fixture: str) -> set[Cell]:
    """Cells where the page and the CSV differ (checked with a class, not "agrees")."""
    cols = STATE_COLS if folder == STATE else DISTRICT_COLS
    out = set()
    for r in _expected(folder, fixture).to_dict("records"):
        cell = (int(r["page"]), int(r["indicator_no"]))
        for part in filter(None, r["checked"].split("; ")):
            if part.startswith("printed number"):  # the whole row
                out |= {(*cell, c) for c in cols if r[c]}
            elif "agrees" not in part:
                out.add((*cell, part.split(":")[0]))
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
    print(
        f"\n{name}: {len(got)} agreed, {len(want) - len(t['missing'])} of {len(want)} tallied, "
        f"{len(t['wrong'])} wrong, {len(t['missing'])} missing"
    )
    return t


@pytest.mark.parametrize(
    "folder, fixture", [(STATE, f) for f in STATES] + [(DISTRICT, f) for f in DISTRICTS]
)
def test_vote_tallies_with_expected(folder: Path, fixture: str) -> None:
    """Pin sheet values, boundaries, CSV differences, and coverage."""
    want = _want(folder, fixture)
    t = _tally(_voted(folder, fixture), want, fixture)
    assert t["wrong"] == {}
    assert t["unexpected"] == []
    assert len(want) - len(t["missing"]) >= MIN_COVERAGE * len(want)
    assert [k for k in _differing(folder, fixture) if k not in t["got"]] == []


def test_csv_differences() -> None:
    """Pin documented CSV differences from the printed sheet."""
    s = pd.read_csv(STATE / "expected.csv", dtype=str, keep_default_na=False)
    edition = s[s.checked.str.contains(": e ")]
    assert sorted(zip(edition.geo, edition.indicator_no, strict=True)) == [
        ("Bihar", "14"),
        ("Bihar", "15"),
    ]
    bihar = edition.set_index("indicator_no")
    assert (bihar.loc["14", "nfhs5_total"], bihar.loc["14", "csv_nfhs5_total"]) == ("55.0", "57.8")
    d = pd.read_csv(DISTRICT / "expected.csv", dtype=str, keep_default_na=False)
    kangra = d[(d.geo == "Kangra, Himachal Pradesh") & (d.indicator_no == "16")].iloc[0]
    assert (kangra.nfhs4_total, kangra.csv_nfhs4_total) == ("2.4", "")  # class a
    raigarh = d[(d.geo == "Raigarh, Maharashtra") & (d.indicator_no == "97")].iloc[0]
    assert raigarh.csv_nfhs5_total_note.startswith("Based on 25-49")  # printed 26.4, no brackets
    mahisagar = d[d.geo == "Mahisagar, Gujarat"]
    shifted = mahisagar[mahisagar.indicator_no != mahisagar.csv_no]
    assert sorted(shifted.indicator_no.astype(int)) == list(range(11, 33))
    assert (shifted.csv_no.astype(int) == shifted.indicator_no.astype(int) - 1).all()


def test_printed_placeholders() -> None:
    """Pin printed placeholders and numeric forms."""
    at = _voted(STATE, "nfhs5_india_p3-6.pdf").set_index(KEY).value
    assert at[(1, 3, "nfhs5_rural")] == "1,037"  # sex ratio
    assert at[(1, 24, "nfhs5_urban")] == "27"  # adolescent fertility rate
    assert at[(2, 47, "nfhs5_urban")] == "3,385"  # Rs.
    assert at[(1, 6, "nfhs4_total")] == "na"
    at = _voted(STATE, "nfhs5_chandigarh_p3-6.pdf").set_index(KEY).value
    assert (at[(2, 67, "nfhs5_urban")], at[(2, 67, "nfhs5_rural")]) == ("(92.8)", "*")
    res = _voted(DISTRICT, "nfhs5_mahisagar_p121-123.pdf")
    assert set(res.column) == {"nfhs5_total"}  # no NFHS-4 column on this sheet
    at = res.set_index(KEY).value
    assert (at[(1, 32, "nfhs5_total")], at[(2, 32, "nfhs5_total")]) == ("83.1", "77.2")  # 32 twice


@pytest.mark.parametrize(
    "folder, fixture", [(STATE, f) for f in STATES] + [(DISTRICT, f) for f in DISTRICTS]
)
def test_sheet_rules_hold(folder: Path, fixture: str) -> None:
    """Pin percentage, total-range, and title-geography rules."""
    res = _voted(folder, fixture)
    assert (res.failed != "").sum() == 0, res[res.failed != ""][[*KEY, "value", "failed"]]
    m = next(m for m in _manifest(folder) if m["fixture"] == fixture)
    assert set(res.geo) == {m["geography"]}


def test_rules_catch_a_misread() -> None:
    """Pin detection of invalid totals and percentages only."""
    ok = _voted(STATE, "nfhs5_india_p3-6.pdf")
    ok = ok[ok.status == "verified"].copy()
    total = ok.index[(ok.indicator_no == 1) & (ok.column == "nfhs5_total")][0]
    ok.loc[total, "value"] = "85.0"  # Urban 82.5, Rural 66.8
    over = ok.index[(ok.indicator_no == 5) & (ok.column == "nfhs5_urban")][0]
    ok.loc[over, "value"] = "933"  # 93.3 with its point lost
    failed = validate(ok, checks()).failed
    assert total_between_urban_and_rural.__name__ in failed[total]
    assert at_most_100.__name__ in failed[over]
    assert (failed != "").sum() == 4  # the two edits and the Urban/Rural beside the Total


def _lines(rows: list[list[tuple[float, str]]]) -> list:
    return [(1, rows)]


def _got(rows: list) -> dict:
    return {(r["indicator_no"], r["column"]): r["value"] for r in parse(_lines(rows))}


def test_parser_on_awkward_lines() -> None:
    """Pin parser handling of difficult engine-shaped rows."""
    rows = [
        [(10, "Kangra, Himachal Pradesh - Key Indicators")],
        [(10, "15. Women with 10 or more years of schooling (%)"), (489, "69.9"), (548, "65.8")],
        [(10, "Marriage and Fertility")],
        # a value printed above its row: read before the row's label
        [(548, "2.4")],
        [(10, "16. Women age 20-24 years married before age 18 years (%)"), (494, "1.5")],
        # a wrapped label: the values between the label's two lines
        [(10, "38. Mothers who received postnatal care from a doctor/nurse/LHV/ANM/midwife/other")],
        [(494, "(93.1)"), (548, "*")],
        [(10, "health personnel within 2 days of delivery (%)")],
        # a stray token outside the page box, right of the table
        [
            (10, "100. Ever undergone an oral cavity examination (%)"),
            (498, "0.4"),
            (550, "na"),
            (612, "na"),
        ],
        # a row the page prints without values yields nothing
        [(10, "101. Women age 15 years and above who use any kind of tobacco (%)")],
        [
            (10, "102. Men age 15 years and above who use any kind of tobacco (%)"),
            (496, "31.8"),
            (550, "1037"),
        ],
    ]
    assert _got(rows) == {
        (15, "nfhs5_total"): "69.9",
        (15, "nfhs4_total"): "65.8",
        (16, "nfhs5_total"): "1.5",
        (16, "nfhs4_total"): "2.4",
        (38, "nfhs5_total"): "(93.1)",
        (38, "nfhs4_total"): "*",
        (100, "nfhs5_total"): "0.4",
        (100, "nfhs4_total"): "na",
        (102, "nfhs5_total"): "31.8",
        (102, "nfhs4_total"): "1037",
    }


def test_titles() -> None:
    """Pin wrapped titles, contents exclusion, and single-column districts."""
    rows = [
        [(30, "Dadra & Nagar Haveli, Dadra & Nagar Haveli and")],
        [(40, "Daman & Diu - Key Indicators")],
        [
            (10, "1. Female population age 6 years and above who ever attended school (%)"),
            (505, "73.1"),
        ],
        [(10, "2. Population below age 15 years (%)"), (505, "25.0")],
    ]
    got = [(r["indicator_no"], r["column"], r["value"], r["geo"]) for r in parse(_lines(rows))]
    geo = "Dadra & Nagar Haveli, Dadra & Nagar Haveli and Daman & Diu"
    assert got == [(1, "nfhs5_total", "73.1", geo), (2, "nfhs5_total", "25.0", geo)]
    rows[:2] = [[(30, "North & Middle Andaman, Andaman & Nicobar Islands – Key Indicators")]]
    assert {r["geo"] for r in parse(_lines(rows))} == {
        "North & Middle Andaman, Andaman & Nicobar Islands"
    }
    contents = [
        [(10, "Key Indicators Content")],
        [(10, "Content"), (400, "Page No.")],
        [(10, "1. North Goa"), (400, "7")],
        [(10, "2. South Goa"), (400, "13")],
    ]
    assert list(parse(_lines(contents))) == []
