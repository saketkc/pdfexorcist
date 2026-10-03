"""MCCD Table 4."""

import csv
from functools import cache
from pathlib import Path

import pandas as pd
import pytest
from mccd_table4 import KEY, header_states, parse

from pdfexorcist import extract

FIXTURES = Path(__file__).parent / "fixtures" / "mccd"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
Cell = tuple[str, str, str]  # (ICD code key, sex, State)

# must be verified and correct: 2009's horizontal All States header, 2011's
# off-page half spread, 2014's Maharashtra column
HARD_CASES = {
    "2009": {("A40-A41", "T", "All States (Total)"): "41387"},
    "2011": {
        ("A40-A41", "T", "All States (Total)"): "39408",
        ("A40-A41", "T", "Andhra Pradesh"): "2378",
        ("A40-A41", "T", "Tamil Nadu"): "3491",
    },
    "2014": {
        ("A40-A41", "T", "Maharashtra"): "14402",
        ("A40-A41", "T", "Lakshadweep"): "3",
    },
}
# Share of expected cells that must be verified, with slack for an engine upgrade.
MIN_COVERAGE = 0.97


def _expected(name: str) -> dict[Cell, str]:
    wide = pd.read_csv(FIXTURES / name, dtype=str)
    long = wide.melt(
        id_vars=["cause_no", "code", "sex"], var_name="state", value_name="deaths"
    ).dropna()
    return {(r.code, r.sex, r.state): r.deaths for r in long.itertuples()}


@cache
def _voted(fixture: str) -> tuple[dict[Cell, str], dict[Cell, set]]:
    """Return verified cells and values that differ across pages."""
    pdf = FIXTURES / fixture
    res = extract(pdf, parse=parse, key=KEY)  # the five default text engines, 3 must agree
    states = header_states(pdf)
    ok = res[
        (res.status == "verified") & (res.pocc == 1)
    ]  # a code printed twice on a page: ambiguous
    unnamed = ok[[states.get((p, c)) is None for p, c in zip(ok.page, ok.col, strict=True)]]
    assert unnamed.empty, f"verified values in columns without a State header: {len(unnamed)}"
    seen: dict[Cell, set] = {}
    for r in ok.itertuples():
        seen.setdefault((r.code, r.sex, states[(r.page, r.col)]), set()).add(r.value)
    got = {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}
    return got, {k: v for k, v in seen.items() if len(v) > 1}


@pytest.mark.parametrize("m", MANIFEST, ids=[m["year"] for m in MANIFEST])
def test_cell_tally(m: dict) -> None:
    """Pin published values, hard cases, and coverage."""
    got, clashes = _voted(m["fixture"])
    want = _expected(m["expected"])
    wrong = {k: (v, want[k]) for k, v in got.items() if k in want and v != want[k]}
    wrong.update({k: (v, want.get(k)) for k, v in clashes.items()})
    missing = [k for k in want if k not in got]
    print(
        f"\n{m['fixture']}: {len(got)} agreed, {sum(k in want for k in got)} tallied, "
        f"{len(wrong)} wrong, {len(missing)} of {len(want)} missing"
    )
    assert wrong == {}
    hard = HARD_CASES[m["year"]]
    assert {k: want.get(k) for k in hard} == hard, "expected file lost a hard case"
    assert {k: got.get(k) for k in hard} == hard
    assert 1 - len(missing) / len(want) >= MIN_COVERAGE
