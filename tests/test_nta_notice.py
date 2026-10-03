"""NEET 2024 press release."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run
from nta_notice import COLUMNS

FIXTURES = Path(__file__).parent / "fixtures" / "nta_notice"
RECIPE = Path(__file__).parent.parent / "examples" / "nta_notice" / "recipe.toml"
EXPECTED = pd.read_csv(FIXTURES / "expected.csv", dtype=str, keep_default_na=False)

# agreed-share floor; slack for an engine upgrade that loses a row
MIN_COVERAGE = 0.95

pytestmark = pytest.mark.usefixtures("wide_console")


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> tuple[int, dict, Path]:
    """(exit code, JSON summary, output folder) of one CLI run on a fixture copy."""
    out = tmp_path_factory.mktemp("nta_notice")
    pdf = out / "doc.pdf"
    shutil.copy(FIXTURES / "nta_notice_2024_p2-6.pdf", pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    return r.exit_code, json.loads(r.stdout), out


def _cells(path: Path) -> pd.DataFrame:
    """The table CSV as one row per cell: table, row, col, value."""
    t = pd.read_csv(path, dtype=str, keep_default_na=False)
    return t.melt(id_vars=["table", "row"], var_name="col").query("value != ''")


def test_vote_tallies_with_expected(result) -> None:
    """Pin correct agreed values and coverage."""
    _, s, out = result
    got = {(r.table, r.row, r.col): r.value for r in _cells(out / "doc.csv").itertuples()}
    want = {(r.table, r.row, r.col): r.value for r in EXPECTED.itertuples()}
    tallied = [k for k in want if k in got]
    wrong = {k: (got[k], want[k]) for k in tallied if got[k] != want[k]}
    print(f"\n{len(got)} agreed, {len(tallied)} tallied, {len(wrong)} wrong of {len(want)}")
    assert wrong == {}
    assert set(got) <= set(want)
    assert len(tallied) / len(want) >= MIN_COVERAGE
    assert s["cells"]["unresolved"] == 0


def test_every_table_is_read(result) -> None:
    """Pin all nine tables in print order."""
    _, _, out = result
    t = pd.read_csv(out / "doc.csv", dtype=str, keep_default_na=False)
    assert list(dict.fromkeys(t.table)) == list(COLUMNS)


def test_misprint_fails_a_check(result) -> None:
    """Pin the isolated 2021 Un-Reserved misprint failure."""
    code, s, out = result
    assert code == 1
    assert s["checks"] == {"Table 1: registered >= categories": 6}
    assert len(s["checks_run"]) == 4
    review = pd.read_csv(out / "doc.review.csv", dtype=str, keep_default_na=False)
    assert set(review.col) == {"2021"} and set(review.table) == {"highlights"}
    misprint = review[review.row == "Un-Reserved"]
    assert misprint.value.tolist() == ["46-853"]


def test_misprint_reads_460853() -> None:
    """Pin passing 2021 category totals with the corrected value."""
    t1 = EXPECTED[(EXPECTED.table == "highlights") & (EXPECTED.col == "2021")]
    v = dict(zip(t1.row, t1.value, strict=True))
    parts = sum(int(v[r]) for r in ("SC", "ST", "OBC", "EWS"))
    assert parts + 460853 == int(v["Number of Candidates registered"])


def test_cities_and_placeholders(result) -> None:
    """Pin city-count detail and printed placeholders."""
    _, _, out = result
    t = pd.read_csv(out / "doc.csv", dtype=str, keep_default_na=False)
    t = t.set_index(["table", "row"])
    assert t.loc[("highlights", "Number of Cities"), "2022"] == "497"
    assert t.loc[("highlights", "PIO"), "2021"] == "---"
    assert t.loc[("highlights", "Number of invigilators"), "2024"] == "210105"
    assert t.loc[("language", "Malayalam"), "2019"] == "NA"
    assert t.loc[("qualifying", "UR/EWS"), "criteria"] == "50th Percentile"
