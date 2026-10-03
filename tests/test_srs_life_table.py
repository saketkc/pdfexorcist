"""SRS life tables."""

import csv
from functools import cache
from pathlib import Path

import pandas as pd
import pytest
from srs_life_table import COLS, KEY, parse, survivorship

from pdfexorcist import extract

FIXTURES = Path(__file__).parent / "fixtures" / "srs"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
EXPECTED = pd.read_csv(FIXTURES / "expected.csv", dtype=str, keep_default_na=False)
FILES = sorted({m["fixture"] for m in MANIFEST})

# Share of expected cells that must be verified, with slack for an engine
# upgrade that loses a row.
MIN_COVERAGE = 0.95

Cell = tuple[int, str, str, str]  # page, category, age, col


def _expected(fixture: str) -> tuple[dict[Cell, tuple[str, str]], list[Cell]]:
    """(cell -> (state, printed value), cells srsindia corrected) for one fixture file."""
    want: dict[Cell, tuple[str, str]] = {}
    fixed: list[Cell] = []
    for r in EXPECTED[EXPECTED.fixture == fixture].itertuples():
        cols = COLS if r.fixed == "all" else r.fixed.split()
        for c in COLS:
            if getattr(r, c) == "":
                continue  # 85+ nqx is printed "..."
            k = (int(r.page), r.category, r.age, c)
            want[k] = (r.state, getattr(r, c))
            if c in cols:
                fixed.append(k)
    return want, fixed


@cache
def _voted(fixture: str) -> pd.DataFrame:
    """extract() result for one fixture PDF, read once per session."""
    return extract(FIXTURES / fixture, parse=parse, key=KEY, checks=[survivorship])


def test_expected_covers_every_fix() -> None:
    """Pin all three 2019-23 srsindia fixes."""
    fixes = EXPECTED[EXPECTED.fix != ""]
    got = set(zip(fixes.state, fixes.category, fixes.fix, strict=True))
    assert {
        ("West Bengal", "Urban", "value corrected"),
        ("Gujarat", "Total", "category restored"),
        ("India", "Urban", "row added"),
    } <= got
    assert len(fixes[fixes.state == "Gujarat"]) == 19
    wb = fixes[fixes.state == "West Bengal"].fixed.str.split().explode()
    assert len(wb) == 74


@pytest.mark.parametrize("fixture", FILES)
def test_verified_tally(fixture: str) -> None:
    """Pin correct votes, corrected cells, and coverage."""
    res = _voted(fixture)
    ok = res[res.status == "verified"]
    got = {tuple(getattr(r, k) for k in KEY): (r.state, r.value) for r in ok.itertuples()}
    failed = {tuple(getattr(r, k) for k in KEY) for r in ok[ok.failed != ""].itertuples()}
    want, fixed = _expected(fixture)

    tallied = [k for k in want if k in got]
    wrong = {k: (got[k], want[k]) for k in tallied if got[k] != want[k]}
    missing = [k for k in want if k not in got]
    print(
        f"\n{fixture}: {len(got)} agreed, {len(tallied)} tallied, {len(wrong)} wrong, "
        f"{len(missing)} missing"
        f" ({', '.join(sorted({s for s, _ in want.values()}))}; {res.n_agree.min()}+ of 5 engines "
        "per cell)"
    )

    assert wrong == {}
    assert [k for k in fixed if k not in got] == []
    assert [k for k in fixed if k in failed] == []
    assert len(tallied) / len(want) >= MIN_COVERAGE


def test_corrigendum_value() -> None:
    """Pin West Bengal urban female e0 at 76.3."""
    res = _voted("srs_2019-23.pdf")
    cell = res[
        (res.state == "West Bengal")
        & (res.category == "Urban")
        & (res.age == "0-1")
        & (res.col == "female_ex")
    ]
    assert cell.value.tolist() == ["76.3"] and cell.status.tolist() == ["verified"]


def test_misprinted_age_label_is_read() -> None:
    """Pin normalization of Uttarakhand's 80+85 misprint."""
    res = _voted("srs_2010-14_uttrakhand.pdf")
    row = res[(res.state == "Uttarakhand") & (res.category == "Total") & (res.age == "80-85")]
    assert dict(zip(row.col, row.value, strict=True))["total_ex"] == "10.9"
