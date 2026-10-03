"""MCCD Tables 2, 5 and 9."""

import csv
from functools import cache
from pathlib import Path

import mccd_table4
import mccd_tables
import pandas as pd
import pytest

from pdfexorcist import extract, total_check, validate

FIXTURES = Path(__file__).parent / "fixtures" / "mccd"
MANIFEST = {
    m["fixture"]: m
    for m in csv.DictReader((FIXTURES / "mccd_tables_manifest.csv").open(encoding="utf-8"))
}
EXPECTED = pd.read_csv(FIXTURES / "mccd_tables_expected.csv", dtype=str, keep_default_na=False)
# Share of expected cells the vote must agree on, with slack for an engine
# upgrade that loses a row.
MIN_COVERAGE = 0.97

Cell = tuple[str, str, str]  # group, sex, column (State, age group or year)


@cache
def _voted(fixture: str) -> pd.DataFrame:
    """extract() result with group and column, read once per session."""
    pdf = FIXTURES / fixture
    table = MANIFEST[fixture]["table"]
    if table == "2":
        res = extract(pdf, parse=mccd_table4.parse, key=mccd_table4.KEY)
        states = mccd_table4.header_states(pdf)
        names = [states.get((p, c)) for p, c in zip(res.page, res.col, strict=True)]
        return res.assign(group=res.code, column=names)
    res = extract(pdf, parse=mccd_tables.parse, key=mccd_tables.KEY)
    if table == "5":
        return mccd_tables.name_ages(res, pdf).rename(columns={"age": "column"})
    return mccd_tables.name_years(res, pdf).rename(columns={"year": "column"})


def _got(res: pd.DataFrame) -> dict[Cell, str]:
    ok = res[res.status == "verified"]
    assert ok.column.notna().all(), "agreed values in a column without a heading"
    got: dict[Cell, set] = {}
    for r in ok.itertuples():
        got.setdefault((r.group, r.sex, r.column), set()).add(r.value)
    assert all(len(v) == 1 for v in got.values()), "one cell read two ways on different pages"
    return {k: next(iter(v)) for k, v in got.items()}


@pytest.mark.parametrize("fixture", sorted(MANIFEST))
def test_vote_tallies_with_expected(fixture: str) -> None:
    """Pin correct values, known mccdindia errors, and coverage."""
    got = _got(_voted(fixture))
    e = EXPECTED[EXPECTED.fixture == fixture]
    want = {(r.group, r.sex, r.column): r.value for r in e.itertuples()}
    fixed = [k for k, f in zip(want, e.fix, strict=True) if f]
    tallied = [k for k in want if k in got]
    wrong = {k: (got[k], want[k]) for k in tallied if got[k] != want[k]}
    print(
        f"\n{fixture}: {len(got)} agreed, {len(tallied)} tallied, {len(wrong)} wrong, "
        f"{len(want) - len(tallied)} of {len(want)} missing ({len(fixed)} mccdindia cells fixed)"
    )
    assert wrong == {}
    assert [k for k in fixed if k not in got] == []
    assert len(tallied) / len(want) >= MIN_COVERAGE


def test_mccd_fixes() -> None:
    """Pin all manifest-listed corrections."""
    n = EXPECTED[EXPECTED.fix != ""].groupby(["fixture", "fix"]).size().to_dict()
    assert n == {
        ("mccd_2018_t5_p104.pdf", "absent"): 26,  # XV (24) and ALL CAUSES T 55-64, TOTAL
        ("mccd_2018_t5_p104.pdf", "corrected"): 3,  # ALL CAUSES T 65-69, 70+, N.S.
        ("mccd_2019_t2_p68-69.pdf", "absent"): 6,  # ALL CAUSES Nagaland, West Bengal
        ("mccd_2019_t2_p68-69.pdf", "corrected"): 30,  # ALL CAUSES Odisha .. Uttar Pradesh
    }


def _checks(total: str | None = None) -> list:
    """The tables' arithmetic: T = M + F, ALL CAUSES = the chapters, total = the columns."""
    out = [
        total_check("sex", "T", ["M", "F"], by=["group", "column"], name="T = M + F"),
        total_check("group", "ALL", None, by=["sex", "column"], name="ALL = rest"),
    ]
    if total:
        out.append(total_check("column", total, None, by=["group", "sex"], name="TOTAL = rest"))
    return out


def test_table5_arithmetic_holds() -> None:
    res = validate(_voted("mccd_2018_t5_p104.pdf"), _checks("TOTAL"))
    assert (res.failed == "").all(), res[res.failed != ""].to_string()


def test_table9_misprint() -> None:
    """Pin the Table 9 misprint and its two failed checks."""
    res = validate(_voted("mccd_2019_t9_p194.pdf"), _checks())
    bad = res[res.failed != ""]
    xii = bad[bad.failed.str.contains("T = M \\+ F")]
    assert set(zip(xii.group, xii.sex, xii.column, xii.value, strict=True)) == {
        ("XII", "M", "2018", "2878"),
        ("XII", "F", "2018", "1632"),
        ("XII", "T", "2018", "4910"),
    }
    assert set(bad.column) == {"2018"}
    assert len(bad[bad.failed.str.contains("ALL = rest")]) == 20  # 19 chapters + ALL, T 2018


def test_table2_reads_the_whole_spread() -> None:
    """Pin both pages of the 2019 spread."""
    got = _got(_voted("mccd_2019_t2_p68-69.pdf"))
    assert got[("A00-B99", "T", "All States (Total)")] == "154576"
    assert got[("ALL", "M", "Odisha")] == "26909"  # mccdindia: 5751, Puducherry's
    assert got[("ALL", "T", "West Bengal")] == "77603"  # mccdindia: none
