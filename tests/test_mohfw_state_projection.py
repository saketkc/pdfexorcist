"""MoHFW projections."""

import csv
from functools import cache
from pathlib import Path

import pandas as pd
import pytest
from mohfw_state_projection import AGES, KEY, YEARS, checks, parse

from pdfexorcist import extract, validate

FIXTURES = Path(__file__).parent / "fixtures" / "mohfw"
MANIFEST = {
    m["fixture"]: m for m in csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8"))
}
EXPECTED = pd.read_csv(
    FIXTURES / "expected.csv",
    dtype={"value": str, "censusindia": str},
    keep_default_na=False,
)

# Share of expected cells the vote must agree on, with slack for an engine
# upgrade that loses a row.
COVERAGE_FLOOR = 0.95

Cell = tuple[int, str, str]  # year, age, sex


@cache
def _voted(fixture: str) -> pd.DataFrame:
    """extract() result for one fixture PDF, read once per session."""
    return extract(FIXTURES / fixture, parse=parse, key=KEY, checks=checks())


def _expected(fixture: str) -> dict[Cell, str]:
    e = EXPECTED[EXPECTED.fixture == fixture]
    return {(int(r.year), r.age, r.sex): r.value for r in e.itertuples()}


@pytest.mark.parametrize("fixture", sorted(MANIFEST))
def test_value_tally(fixture: str) -> None:
    """Pin correct agreed values and coverage."""
    res = _voted(fixture)
    ok = res[res.status == "verified"]
    got = {(int(r.year), r.age, r.sex): r.value for r in ok.itertuples()}
    want = _expected(fixture)
    tallied = [k for k in want if k in got]
    wrong = {k: (got[k], want[k]) for k in tallied if got[k] != want[k]}
    missing = sorted(k for k in want if k not in got)
    e = EXPECTED[EXPECTED.fixture == fixture]
    fixed = int((e.value != e.censusindia).sum())
    print(
        f"\n{fixture}: {len(got)} agreed, {len(tallied)} tallied, {len(wrong)} wrong, "
        f"{len(missing)} of {len(want)} missing ({fixed} censusindia values corrected; "
        f"{res.n_agree.min()}+ engines per cell)"
    )
    assert wrong == {}
    assert len(tallied) >= COVERAGE_FLOOR * len(want), missing


@pytest.mark.parametrize("fixture", sorted(MANIFEST))
def test_whole_table_is_agreed(fixture: str) -> None:
    """Pin agreement for every printed table cell."""
    res = _voted(fixture)
    ok = res[res.status == "verified"]
    assert set(ok.year) == set(YEARS)
    assert len(ok) == len(YEARS) * (len(AGES) + 2) * 3


@pytest.mark.parametrize("fixture", sorted(MANIFEST))
def test_table_arithmetic_holds(fixture: str) -> None:
    """Pin sex, age-total, and 0-4 arithmetic checks."""
    res = _voted(fixture)
    failed = res[res.failed != ""]
    assert failed.empty, failed[[*KEY, "value", "failed"]].to_string()


def test_arithmetic_error() -> None:
    """Pin both checks for India's 2026 Male 0-4 misread."""
    res = _voted("mohfw_india_p165-166.pdf")
    bad = res[res.status == "verified"].copy()
    at = bad.index[(bad.year == 2026) & (bad.age == "0-4") & (bad.sex == "Male")][0]
    bad.loc[at, "value"] = "56943"
    failed = validate(bad, checks()).failed[at]
    assert "Person = Male + Female" in failed and "Total = sum of age groups" in failed


def test_india_break() -> None:
    """Pin India totals that continue onto the next page."""
    res = _voted("mohfw_india_p165-166.pdf")
    tot = res[(res.age == "Total") & (res.year == 2036)].set_index("sex")
    assert tot.value.to_dict() == {
        "Person": "1518288",
        "Male": "775702",
        "Female": "742586",
    }
    assert set(tot.page) == {2}


def test_title_typo() -> None:
    """Pin position-based parsing despite Uttarakhand's PUNJAB title."""
    res = _voted("mohfw_uttarakhand_p182.pdf")
    assert set(res.title) == {"PUNJAB"}
    assert res[
        (res.year == 2011) & (res.age == "Total") & (res.sex == "Person")
    ].value.tolist() == ["10086"]
