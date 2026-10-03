"""Crime in India tables."""

import csv
from pathlib import Path

import pandas as pd
import pytest
from cii_state_table import KEY, Layout, checks, dnh_rows, footnote_free, parse

from pdfexorcist import extract, validate

FIXTURES = Path(__file__).parent / "fixtures" / "cii"
MANIFEST = {
    m["fixture"]: m for m in csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8"))
}
EXPECTED = pd.read_csv(FIXTURES / "expected.csv", dtype={"row": str, "value": str})

LAYOUTS: dict[str, Layout] = {
    "cii_2021_1A.1_p43.pdf": Layout(counts=(3, 4, 5), rate=(5, 6, 7)),
    "cii_2023_1A.4_p47.pdf": Layout(
        counts=(12, 13, 15, 16, 18, 19), sums=((12, (15, 18)), (13, (16, 19)))
    ),
    "cii_2024_1C.2_p264.pdf": Layout(counts=tuple(range(3, 11))),
}
# Share of expected cells the vote must agree on, with slack for an engine
# upgrade that drops a few cells.
COVERAGE_FLOOR = 0.95

Cell = tuple[int, str, int]


def _expected(fixture: str) -> dict[Cell, float]:
    e = EXPECTED[EXPECTED.fixture == fixture]
    return {(1, r.row, int(r.col)): float(r.value) for r in e.itertuples()}


@pytest.fixture(scope="module", params=sorted(MANIFEST))
def voted(request) -> tuple[str, pd.DataFrame]:
    fixture = request.param
    res = extract(
        FIXTURES / fixture,
        parse=parse,
        key=KEY,
        normalize=footnote_free,
        checks=checks(LAYOUTS[fixture]),
    )
    return fixture, res


def test_verified_values(voted):
    """Pin verified values and agreement coverage."""
    fixture, res = voted
    want = _expected(fixture)
    ok = res[res.status == "verified"]
    got = {(int(r.page), r.row, int(r.col)): r.value for r in ok.itertuples()}
    tallied = {k: v for k, v in got.items() if k in want}
    wrong = {k: (v, want[k]) for k, v in tallied.items() if float(v) != want[k]}
    missing = sorted(k for k in want if k not in got)
    print(
        f"\n{fixture}: {len(got)} agreed, {len(tallied)} tallied, {len(wrong)} wrong, "
        f"{len(missing)} of {len(want)} missing"
    )
    assert wrong == {}
    assert len(tallied) >= COVERAGE_FLOOR * len(want), missing


def test_dnhdd_row_verified_and_correct(voted):
    """Pin name-based DNH&DD identification and values."""
    fixture, res = voted
    assert dnh_rows(res) == ["31"]
    want = {k: v for k, v in _expected(fixture).items() if k[1] == "31"}
    row = res[res.row == "31"].set_index("col")
    assert len(want) >= 6
    for (_, _, col), v in want.items():
        assert row.status.get(col) == "verified", (col, row.votes.get(col))
        assert float(row.value[col]) == v, (col, row.value[col], v)


def test_table_arithmetic_holds(voted):
    """Pin state, UT, column-sum, and rate checks."""
    _fixture, res = voted
    failed = res[res.failed != ""]
    assert failed.empty, failed[["row", "col", "value", "failed"]].to_string()


def test_dnhdd_error(voted):
    """Pin detection of a one-count DNH&DD error."""
    fixture, res = voted
    col = LAYOUTS[fixture].counts[0]
    bad = res.copy()
    at = bad.index[(bad.row == "31") & (bad.col == col)][0]
    bad.loc[at, "value"] = str(int(float(bad.loc[at, "value"])) + 1)
    failed = validate(bad, checks(LAYOUTS[fixture])).failed
    assert "totaluts" in failed[at]
