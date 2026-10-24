"""MoHFW Rural Health Statistics: health staff by State/UT, one cadre a table."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "rhs"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "rhs" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
COLS = ["required", "sanctioned", "in_position", "vacant", "shortfall"]

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[dict, pd.DataFrame, int]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return json.loads(r.stdout), table.set_index(["table", "sno"]), r.exit_code


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame, int]]:
    tmp = tmp_path_factory.mktemp("rhs")
    return {m["fixture"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def test_every_cell_agreed(results) -> None:
    """Pin each fixture's cell count and failed checks; every cell agreed."""
    seen = {}
    for fixture, (s, _, code) in results.items():
        c = s["cells"]
        assert c["verified"] == c["total"], fixture
        assert len(s["checks_run"]) == 3
        assert code == (1 if c["failed_checks"] else 0)
        seen[fixture] = (c["total"], c["failed_checks"])
    assert seen == {
        "rhs_2021-22_t12-17-76.pdf": (513, 0),
        "rhs_2020-21_t49.pdf": (185, 3),
        "rhs_2016-17_t15-28A.pdf": (259, 0),
    }


def test_states_and_totals(results) -> None:
    """Pin the All India row, wrapped State names and the surplus marks."""
    t = results["rhs_2021-22_t12-17-76.pdf"][1]
    assert set(t.index.get_level_values("table")) == {"12", "17", "76"}
    assert t.loc[("12", "total"), COLS].tolist() == ["157935", "208235", "180769", "28800", "8208"]
    assert t.loc[("12", "total"), "state"] == "All India"
    assert t.loc[("12", "31"), "state"] == "Dadra & Nagar Haveli and Daman & Diu"
    assert t.loc[("12", "29"), COLS].tolist() == ["124", "148", "145", "3", "*"]
    assert t.loc[("12", "30"), COLS].tolist() == ["0", "N App", "N App", "N App", "N App"]
    assert t.loc[("12", "2"), ["sanctioned", "vacant"]].tolist() == ["NA", "NA"]
    assert t.loc[("12", "1"), ["title", "area", "page"]].tolist() == [
        "HEALTH WORKER [FEMALE] / ANM AT SUB CENTRE in Rural Areas", "rural", "1"
    ]  # fmt: skip


def test_facilities_column(results) -> None:
    """Pin a table that prints the PHCs functioning in place of required and shortfall."""
    t = results["rhs_2021-22_t12-17-76.pdf"][1]
    row = t.loc[("17", "total"), ["facilities", "sanctioned", "in_position", "vacant", "required"]]
    assert row.tolist() == ["24935", "10949", "8473", "2917", ""]
    assert t.loc[("17", "1"), "facilities"] == "1142"


def test_tribal_table(results) -> None:
    """Pin a tribal-area table: no All India row, a footnote mark dropped from the State."""
    t = results["rhs_2021-22_t12-17-76.pdf"][1]
    tribal = t.loc["76"]
    assert "total" not in tribal.index and len(tribal) == 36
    assert set(tribal["area"]) == {"tribal"}
    assert tribal.loc["34", ["state", *COLS]].tolist() == ["Ladakh", "288", "50", "46", "4", "242"]
    assert tribal.loc["36", "state"] == "Puducherry"


def test_older_layout(results) -> None:
    """Pin RHS 2016-17: footnote marks after names, a table with sanctioned and in position only."""
    t = results["rhs_2016-17_t15-28A.pdf"][1]
    assert t.loc[("15", "17"), ["state", "sanctioned"]].tolist() == ["Meghalaya", "903"]
    assert t.loc[("15", "total"), COLS].tolist() == ["156231", "186479", "198356", "26172", "6104"]
    assert t.loc[("28A", "total"), ["sanctioned", "in_position", "vacant"]].tolist() == [
        "14859", "14350", ""
    ]  # fmt: skip


def test_misprint_fails(results) -> None:
    """Telangana prints a surplus mark for 28 vacant doctors (manifest note)."""
    s, t, _ = results["rhs_2020-21_t49.pdf"]
    assert t.loc[("49", "24"), ["sanctioned", "in_position", "vacant"]].tolist() == [
        "498", "470", "*"
    ]  # fmt: skip
    assert s["checks"] == {"vacant = sanctioned - in position": 3}
    review = pd.read_csv(s["review"], dtype=str, keep_default_na=False)
    assert set(zip(review["sno"], review["col"], strict=True)) == {
        ("24", "sanctioned"), ("24", "in_position"), ("24", "vacant")
    }  # fmt: skip
    assert t.loc[("49", "total"), "vacant"] == "1530"
