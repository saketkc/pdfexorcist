"""CBHI National Health Profile: State/UT wise cases and deaths by sex, one disease a table."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

from pdfexorcist.checks import validate
from pdfexorcist.recipe import load

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "cbhi_nhp"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "cbhi_nhp" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
COLS = ["Male Cases", "Male Deaths", "Female Cases", "Female Deaths", "Total Cases", "Total Deaths"]
RABIES = "nhp_2023_p130_p148.pdf"

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[int, dict, pd.DataFrame]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return r.exit_code, json.loads(r.stdout), table.set_index(["table", "state"])


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[int, dict, pd.DataFrame]]:
    tmp = tmp_path_factory.mktemp("cbhi_nhp")
    return {m["fixture"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def test_every_cell_agreed(results) -> None:
    """Pin each fixture's cell count; every cell is agreed by at least three engines."""
    totals = {}
    for fixture, (_, s, t) in results.items():
        c = s["cells"]
        assert c["verified"] == c["total"] and c["unresolved"] == 0, fixture
        assert len(s["checks_run"]) == 3
        totals[fixture] = (c["total"], len(t))
    assert totals == {
        "nhp_2011_p19.pdf": (221, 37),
        "nhp_2019_p154.pdf": (228, 38),
        "nhp_2022_p225.pdf": (232, 39),
        RABIES: (468, 78),
    }


def test_tables_disease_and_year(results) -> None:
    """Pin the table, disease and year read from each title."""
    got = {
        (table, d, y)
        for _, _, t in results.values()
        for (table, _), d, y in zip(t.index, t.disease, t.year, strict=True)
    }
    assert got == {
        ("3.1.1.6(B)", "Cholera", "2011"),
        ("3.1.29(A)", "Chicken Pox", "2017"),
        ("3.1.29(A)", "Chicken Pox", "2020"),
        ("3.1.7(A)", "Cholera Infection", "2021"),
        ("3.1.16(A)", "Rabies Infection", "2021"),
    }


def test_hard_cells(results) -> None:
    """Pin blank cells, wrapped names, footnote marks, NA and the India rows."""
    t11 = results["nhp_2011_p19.pdf"][2]
    # no male deaths printed; the Reference Period column ("Dec.,11") is not read
    assert t11.loc[("3.1.1.6(B)", "Arunachal Pradesh"), COLS].tolist() == [
        "0", "", "0", "0", "0", "0"
    ]  # fmt: skip
    assert t11.loc[("3.1.1.6(B)", "India"), COLS].tolist() == [
        "1195", "8", "1146", "2", "2341", "10"
    ]  # fmt: skip
    assert t11.loc[("3.1.1.6(B)", "Kashmir Div"), "Male Cases"] == "0"
    t19 = results["nhp_2019_p154.pdf"][2]
    assert t19.loc[("3.1.29(A)", "Arunachal Pradesh"), "Total Cases"] == "400"
    assert t19.loc[("3.1.29(A)", "India"), "Total Cases"] == "75288"
    t22 = results["nhp_2022_p225.pdf"][2]
    assert t22.loc[("3.1.29(A)", "Arunachal Pradesh"), COLS].tolist() == [
        "195", "0", "142", "0", "337", "0"
    ]  # fmt: skip
    assert t22.loc[("3.1.29(A)", "Puducherry"), COLS].tolist() == [
        "49", "", "56", "", "105", "0"
    ]  # fmt: skip
    assert t22.loc[("3.1.29(A)", "Odisha"), "Male Cases"] == "345"  # printed "Odisha*"
    assert t22.loc[("3.1.29(A)", "Ladakh"), "Total Cases"] == "8"
    t23 = results[RABIES][2]
    assert t23.loc[("3.1.7(A)", "India"), COLS].tolist() == ["123", "4", "141", "2", "264", "6"]
    assert t23.loc[("3.1.7(A)", "West Bengal"), COLS].tolist() == ["NA"] * 6
    assert t23.loc[("3.1.7(A)", "Andaman and Nicobar Islands"), "Total Cases"] == "0"


def test_checks_pass_except_misprints(results) -> None:
    """Pin the checks: they pass everywhere but on the misprinted NHP 2023 rabies table."""
    for fixture, (code, s, _) in results.items():
        if fixture != RABIES:
            assert code == 0 and s["cells"]["failed_checks"] == 0, fixture
    code, s, _ = results[RABIES]
    # 4 columns of 39 rows do not add up to India; Delhi's 0 + 6 cases total 0
    assert code == 1 and s["cells"]["failed_checks"] == 4 * 39 + 2


def test_a_wrong_total_is_flagged(results) -> None:
    """Pin both rules on cells built from a fixture: one changed value fails both."""
    t = results["nhp_2019_p154.pdf"][2]
    cells = (
        t[COLS]
        .reset_index()
        .melt(id_vars=["table", "state"], var_name="col", value_name="value")
        .assign(page=1)
    )
    assert (validate(cells, load(RECIPE).check_functions()).failed == "").all()
    goa = (cells.state == "Goa") & (cells.col == "Male Cases")
    cells.loc[goa, "value"] = str(int(cells.loc[goa, "value"].iloc[0]) + 1)
    out = validate(cells, load(RECIPE).check_functions())
    bad = out[out.failed != ""]
    assert set(bad[bad.state != "Goa"].col) == {"Male Cases"}
    assert set(bad[bad.state == "Goa"].col) == {"Male Cases", "Female Cases", "Total Cases"}
