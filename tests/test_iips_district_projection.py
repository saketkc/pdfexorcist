"""IIPS district projections."""

import csv
from functools import cache
from pathlib import Path

import pandas as pd
import pytest
from iips_district_projection import KEY, TOTAL, checks, parse

from pdfexorcist import extract, validate

FIXTURES = Path(__file__).parent / "fixtures" / "iips"
MANIFEST = {
    m["fixture"]: m for m in csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8"))
}
EXPECTED = pd.read_csv(FIXTURES / "expected.csv", dtype=str, keep_default_na=False)

# Share of expected cells the vote must agree on; camelot can miss a whole
# block (Chamba, p.93), so a page may lose a voter.
MIN_COVERAGE = 0.95

Cell = tuple[int, int, str, str, str]  # page, block, printed year, sex, age


@cache
def _voted(fixture: str) -> pd.DataFrame:
    """extract() result for one fixture page, read once per session."""
    return extract(FIXTURES / fixture, parse=parse, key=KEY, checks=checks())


def _expected(fixture: str) -> dict[Cell, tuple[str, str]]:
    """cell -> (printed value, fix) for one fixture."""
    e = EXPECTED[EXPECTED.fixture == fixture]
    return {
        (int(r.page), int(r.block), r.printed_year, r.sex, r.age): (r.value, r.fix)
        for r in e.itertuples()
    }


@pytest.mark.parametrize("fixture", sorted(MANIFEST))
def test_vote_tallies_with_expected(fixture: str) -> None:
    """Pin correct values, known censusindia errors, and coverage."""
    res = _voted(fixture)
    ok = res[res.status == "verified"]
    got = {tuple(getattr(r, k) for k in KEY): r.value for r in ok.itertuples()}
    want = _expected(fixture)
    tallied = [k for k in want if k in got]
    wrong = {k: (got[k], want[k][0]) for k in tallied if got[k] != want[k][0]}
    missing = [k for k in want if k not in got]
    fixed = [k for k, (_, fix) in want.items() if fix]
    print(
        f"\n{fixture}: {len(got)} agreed, {len(tallied)} tallied, {len(wrong)} wrong, "
        f"{len(missing)} missing"
        f" ({len(fixed)} cells censusindia lacks or differs on; {res.n_agree.min()}+ of 5 engines "
        "per cell)"
    )
    assert wrong == {}
    assert [k for k in fixed if k not in got] == []
    assert len(tallied) / len(want) >= MIN_COVERAGE


def test_census_fixes() -> None:
    """Pin all manifest-listed censusindia defects."""
    n = EXPECTED.groupby(["fixture", "block", "fix"]).size().to_dict()
    assert n == {
        ("iips_p1125_andhra_prakasam.pdf", "0", ""): 290,
        ("iips_p1125_andhra_prakasam.pdf", "1", ""): 290,
        (
            "iips_p240_delhi_west.pdf",
            "0",
            "corrected",
        ): 290,  # holds the 2027-2031 block
        ("iips_p240_delhi_west.pdf", "1", "absent"): 290,  # 2027-2031 NA
        ("iips_p281_rajasthan_sirohi.pdf", "0", "absent"): 290,  # 2012-2016 NA
        ("iips_p281_rajasthan_sirohi.pdf", "1", ""): 290,
        (
            "iips_p603_manipur_imphal_east.pdf",
            "0",
            "corrected",
        ): 290,  # Ukhrul = Imphal East + Ukhrul
        ("iips_p603_manipur_imphal_east.pdf", "1", "corrected"): 290,
    }


@pytest.mark.parametrize("fixture", sorted(MANIFEST))
def test_table_arithmetic_holds(fixture: str) -> None:
    """Pin All ages totals within rounding."""
    res = _voted(fixture)
    ok = res[res.status == "verified"]
    assert (ok.age == TOTAL).sum() == 20  # 2 blocks x 5 years x 2 sexes, all judged
    failed = res[res.failed != ""]
    assert failed.empty, failed[[*KEY, "value", "failed"]].to_string()


def test_arithmetic_catches_a_misread() -> None:
    """Pin detection of a 100-count age-group error."""
    res = _voted("iips_p281_rajasthan_sirohi.pdf")
    bad = res[res.status == "verified"].copy()
    at = bad.index[
        (bad.block == 1) & (bad.year == "2019") & (bad.sex == "Females") & (bad.age == "45-49")
    ][0]
    bad.loc[at, "value"] = str(int(bad.loc[at, "value"]) + 100)
    assert "All ages = sum of ages" in validate(bad, checks()).failed[at]


def test_printed_headers() -> None:
    """Pin printed block headers and title-derived districts."""
    west = _voted("iips_p240_delhi_west.pdf")
    assert sorted(set(zip(west.block, west.year, strict=True))) == [
        (b, str(y)) for b in (0, 1) for y in range(2022, 2027)
    ]
    sirohi = _voted("iips_p281_rajasthan_sirohi.pdf")
    assert sorted(set(sirohi[sirohi.block == 0].year)) == [str(y) for y in range(2027, 2032)]
    imphal = _voted("iips_p603_manipur_imphal_east.pdf")
    assert set(zip(imphal.district, imphal.header, strict=True)) == {("Imphal East", "Ukhrul")}
    prakasam = _voted("iips_p1125_andhra_prakasam.pdf")
    assert set(zip(prakasam.block, prakasam.district, prakasam.header, strict=True)) == {
        (0, "Prakasam", "Prakasam"),
        (1, "Prakasam", "Guntur"),
    }
