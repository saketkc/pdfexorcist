"""National Health Accounts Estimates for India: key indicators, SHA 2011 tables, State tables."""

import csv
import json
import shutil
from pathlib import Path

import nha
import nha_checks
import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "nha"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "nha" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
Y21, Y20, Y15 = (m["fixture"] for m in MANIFEST)

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[dict, pd.DataFrame]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    assert r.exit_code == 0, r.stdout
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return json.loads(r.stdout), table.set_index(["table", "item"])


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    tmp = tmp_path_factory.mktemp("nha")
    return {m["fixture"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def test_every_cell_agreed_and_checks_pass(results) -> None:
    """Pin each fixture's cell count and rows per table; every cell agreed, no check fails."""
    totals, rows = {}, {}
    for fixture, (s, t) in results.items():
        c = s["cells"]
        assert c["verified"] == c["total"] and c["failed_checks"] == 0, fixture
        assert len(s["checks_run"]) == 4
        totals[fixture] = c["total"]
        rows[fixture] = t.index.get_level_values("table").value_counts().to_dict()
    assert totals == {Y21: 950, Y20: 915, Y15: 505}
    assert rows[Y21] == {
        "states_ghe": 31, "HC": 28, "states": 21, "HP": 21, "key": 19, "HF": 16, "FS": 16,
        "rounds": 9, "che": 7, "capital": 6, "uts_ghe": 4,
    }  # fmt: skip
    assert rows[Y15] == {
        "HC": 24,
        "HP": 21,
        "states": 20,
        "key": 19,
        "HF": 16,
        "FS": 16,
        "rounds": 8,
    }


def test_code_tables(results) -> None:
    """Pin rows keyed by SHA 2011 code: footnote marks, wrapped names, reporting items."""
    t = results[Y21][1]
    assert t.loc[("HF", "HF.1.1.1.2"), ["amount", "pct"]].tolist() == ["20718", "2.62"]
    assert t.loc[("HF", "Total"), ["amount", "pct"]].tolist() == ["789760", "100"]
    assert t.loc[("HP", "HP.10"), "amount"] == "21759"
    assert t.loc[("HC", "HC.6.2"), "page"] == "8"  # Table 7 continued without a title
    assert t.loc[("HC", "HC.RI.1"), ["amount", "pct"]].tolist() == ["243562", "30.84"]
    assert t.loc[("FS", "FS.3.4"), "amount"] == "0"
    assert t.loc[("capital", "Total"), "amount"] == "114701"
    # 2020-21 prints the amount on the line below "Union Government Schemes (Employee) 7"
    t = results[Y20][1]
    assert t.loc[("HF", "HF.1.1.1.2"), ["amount", "pct"]].tolist() == ["17273", "2.60"]
    t = results[Y15][1]
    assert t.loc[("HF", "HF.3.3"), ["amount", "pct"]].tolist() == ["320211", "64.7"]


def test_key_indicators(results) -> None:
    """Pin year columns: split over two lines, newest first, continued on a page with no header."""
    t = results[Y21][1]
    assert t.loc[("rounds", "2"), ["2013-14", "2021-22"]].tolist() == ["3638", "6602"]
    assert t.loc[("key", "1"), "2021-22"] == "3.83"
    assert t.loc[("che", "3"), "2021-22"] == "45.1"
    t = results[Y20][1]
    assert t.loc[("key", "19"), ["2017-18", "2020-21", "page"]].tolist() == ["33.4", "29.2", "3"]
    assert "2021-22" not in t.columns
    t = results[Y15][1]
    assert t.loc[("rounds", "1"), ["2004-05", "2015-16"]].tolist() == ["4.2", "3.8"]
    assert t.loc[("key", "11"), "2015-16"] == "64.38"


def test_state_tables(results) -> None:
    """Pin State columns in both orders, rows with no serial, and wrapped names."""
    cols = ["the_cr", "the_pc", "the_pct_gsdp", "oope_pct_the", "population_cr"]
    assert results[Y21][1].loc[("states", "Kerala"), cols].tolist() == [
        "48034", "13343", "5.2", "59.1", "3.6"
    ]  # fmt: skip
    assert results[Y15][1].loc[("states", "Kerala"), cols].tolist() == [
        "25090", "7169", "4.5", "71.3", "3.5"
    ]  # fmt: skip
    assert results[Y20][1].loc[("states", "Assam"), "the_cr"] == "11228"
    t = results[Y21][1]
    assert t.loc[("states_ghe", "Arunachal Pradesh"), "ghe_pc"] == "7825"
    assert t.loc[("states_ghe", "Jammu and Kashmir"), "ghe_cr"] == "6071"
    assert t.loc[("uts_ghe", "Chandigarh"), ["ghe_pc", "ghe_000"]].tolist() == ["19659", "23885628"]


def _cells(table: pd.DataFrame) -> pd.DataFrame:
    """The agreed cells of a table-layout result, one row per cell."""
    long = table.reset_index().melt(id_vars=["table", "item", "label", "page"], var_name="col")
    return long[long.value != ""].reset_index(drop=True)


def test_checks_catch_a_misread(results) -> None:
    """A misread State ratio or key indicator fails its check."""
    cells = _cells(results[Y21][1])
    assert not any(fn(cells).any() for fn in nha_checks.CHECKS)
    for table, item, col, value in [
        ("states", "Kerala", "ghe_pct_the", "23.5"),
        ("uts_ghe", "Chandigarh", "ghe_pc", "19569"),
        ("key", "11", "2019-20", "62.4"),
        ("rounds", "6", "2021-22", "34.9"),
    ]:
        bad = cells.copy()
        at = (bad.table == table) & (bad["item"] == item) & (bad.col == col)
        assert at.sum() == 1
        bad.loc[at, "value"] = value
        assert any(fn(bad)[at].all() for fn in nha_checks.CHECKS), (table, item, col)


def test_table_titles() -> None:
    """Name the tables read and skip the matrices, Table 9 and Table 10."""
    kind = nha.table_kind
    assert (
        kind("Table 4: Current Health Expenditures (2021-22) by Healthcare Financing Schemes.")
        == "codes"
    )
    assert (
        kind("Table 5: Current Health Expenditures (2021-22) by Revenues of Healthcare") == "codes"
    )
    assert (
        kind("Table A 2: Current Health Expenditure (2021-22) by Healthcare Providers and H")
        is None
    )
    assert kind("Table 9: Current Health Expenditure (2021-22) by Primary, Secondary and") is None
    assert kind("Table 10: Health Insurance Expenditure (2021-22) under different schemes") is None
    assert kind("Table 1: Key health financing indicators for India across NHA rounds1") == "rounds"
    assert (
        kind("Table A.6: Key Health Financing Indicators for select States: NHA Estimates")
        == "states"
    )
