"""Pravah dam report."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run
from pravah_dams import COLS, pct_of_live

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "pravah"
FIXTURE = "pravah_2026-10-03_p5-8.pdf"
RECIPE = ROOT / "examples" / "pravah_dams" / "recipe.toml"
EXPECTED = pd.read_csv(FIXTURES / "expected.csv", dtype=str, keep_default_na=False)

# agreed-share floor; slack for an engine upgrade that loses a row
MIN_COVERAGE = 0.95

pytestmark = pytest.mark.usefixtures("wide_console")


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> tuple[int, dict, pd.DataFrame]:
    """(exit code, JSON summary, the CSV table) of the recipe on a copy of the fixture."""
    tmp = tmp_path_factory.mktemp("pravah")
    pdf = tmp / "pravah.pdf"
    shutil.copy(FIXTURES / FIXTURE, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    table = pd.read_csv(tmp / "pravah.csv", dtype=str, keep_default_na=False)
    return r.exit_code, json.loads(r.stdout), table


def test_values_tally_with_the_page(result) -> None:
    """Pin correct table values and coverage."""
    code, s, t = result
    assert code == 0 and s["cells"]["failed_checks"] == 0 and len(s["checks_run"]) == 2
    got = {(r["dam"], c): r[c] for _, r in t.iterrows() for c in COLS if r[c] != ""}
    want = {(r["dam"], c): r[c] for _, r in EXPECTED.iterrows() for c in COLS}
    tallied = [k for k in want if k in got]
    wrong = {k: (got[k], want[k]) for k in tallied if got[k] != want[k]}
    missing = [k for k in want if k not in got]
    print(
        f"\n{FIXTURE}: {len(got)} agreed, {len(tallied)} tallied, {len(wrong)} wrong, "
        f"{len(missing)} of {len(want)} missing"
    )
    assert wrong == {}
    assert set(got) <= set(want)
    assert len(tallied) / len(want) >= MIN_COVERAGE


def test_mumbai_dams(result) -> None:
    """Pin Mumbai supply dams with their region and district."""
    t = result[2].set_index("dam")
    assert t.loc["Bhatsa", ["live", "pct_live"]].tolist() == ["929.20", "98.63"]
    assert t.loc["Upper Vaitarna", ["region", "district", "date"]].tolist() == [
        "Nashik", "Nashik", "03/10/2026"
    ]  # fmt: skip
    assert t.loc["Middle Vaitarna", ["region", "district"]].tolist() == ["Kokan", "Palghar"]
    assert t.loc["Modaksagar", "gross"] == "177.23"
    assert t.loc["Tansa", ["district", "time"]].tolist() == ["Thane", "07:35 AM"]


def test_wrapped_names_and_headings(result) -> None:
    """Pin wrapped names and cross-page district headings."""
    t = result[2].set_index("dam")
    assert t.loc["Kinwat ( Mangrul ) H L B", "sr"] == "7"
    assert t.loc["Wanjarkheda High level Barrage", "district"] == "Latur"
    assert t.loc["Lower Dudhana", "district"] == "Parbhani"
    assert t.loc["Radhanagari H E P", ["region", "district"]].tolist() == ["Pune", "Kolhapur"]
    # headings on pages before the fixture: Chhatrapati Sambhajinagar Region, Nanded
    assert t.loc["Digadi H L B", ["region", "district"]].tolist() == ["", ""]


def test_pct_check_catches_a_misread() -> None:
    """Pin detection of Bhatsa's missing decimal."""
    row = EXPECTED[EXPECTED.dam == "Bhatsa"].iloc[0]
    cells = pd.DataFrame([{"page": 4, "id": "bhatsa", "col": c, "value": row[c]} for c in COLS])
    assert not pct_of_live(cells).any()
    cells.loc[cells.col == "live", "value"] = "92920"
    assert set(cells[pct_of_live(cells)].col) == {"live", "live_cap", "pct_live"}
