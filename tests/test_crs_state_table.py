"""CRS tables."""

from functools import cache
from pathlib import Path

import pandas as pd
from crs_state_table import KEY, checks, parse

from pdfexorcist import extract, validate

FIXTURES = Path(__file__).parent / "fixtures" / "crs"
FIXTURE = "crs_2023_t1_t4.pdf"
EXPECTED = pd.read_csv(FIXTURES / "expected.csv", dtype=str, keep_default_na=False)

# Share of expected cells the vote must agree on, with slack for an engine
# upgrade that loses a row.
MIN_COVERAGE = 0.95

Cell = tuple[int, str, str]  # page, state key, col


@cache
def _voted() -> pd.DataFrame:
    """extract() result for the fixture, read once per session."""
    return extract(FIXTURES / FIXTURE, parse=parse, key=KEY, checks=checks())


def test_vote_tallies_with_expected() -> None:
    """Pin correct agreed values and coverage."""
    res = _voted()
    ok = res[res.status == "verified"]
    got: dict[Cell, str] = {(int(r.page), r.state, r.col): r.value for r in ok.itertuples()}
    want: dict[Cell, str] = {
        (int(r.page), r.state_key, r.col): r.value for r in EXPECTED.itertuples()
    }
    tallied = [k for k in want if k in got]
    wrong = {k: (got[k], want[k]) for k in tallied if got[k] != want[k]}
    missing = [k for k in want if k not in got]
    print(
        f"\n{FIXTURE}: {len(got)} agreed, {len(tallied)} tallied, {len(wrong)} wrong, "
        f"{len(missing)} of {len(want)} missing ({res.n_agree.min()}+ engines per cell)"
    )
    assert wrong == {}
    assert len(tallied) / len(want) >= MIN_COVERAGE


def test_table_arithmetic_holds() -> None:
    """Pin Person and Total arithmetic checks."""
    res = _voted()
    failed = res[res.failed != ""]
    assert failed.empty, failed[[*KEY, "value", "failed"]].to_string()


def test_arithmetic_catches_a_misread() -> None:
    """Pin both checks for a tenfold Bihar misread."""
    res = _voted()
    bad = res[res.status == "verified"].copy()
    at = bad.index[(bad.page == 1) & (bad.state == "bihar") & (bad.col == "Rural_Male")][0]
    assert bad.loc[at, "value"] == "916009"
    bad.loc[at, "value"] = "9160090"
    failed = validate(bad, checks()).failed[at]
    assert "Person >= Male + Female" in failed and "Total >= Rural + Urban" in failed


def test_wrapped_name_and_fake_bold_row() -> None:
    """Pin wrapped-name recovery and unresolved fake-bold India."""
    res = _voted()
    dnhdd = res[(res.page == 1) & (res.state == "dadraandnagarhavelianddamananddiu")]
    assert set(dnhdd.label) == {"Dadra and Nagar Haveli and Daman and Diu"}
    assert dict(zip(dnhdd.col, dnhdd.value, strict=True))["Total_Person"] == "12948"
    assert (dnhdd.status == "verified").all()
    india = res[res.state == "india"]
    assert len(india) == 18 and (india.status != "verified").all()
