"""NACO HIV tables by State/UT: Sankalak and the India HIV Estimates."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "naco_hiv"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "naco_hiv" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
S23 = "sankalak_2023_p97_p110_p119.pdf"
S24 = "sankalak_2024_p106_p120_p133.pdf"
E21 = "hiv_estimates_2021_p6_p14-15_p25.pdf"
E22 = "hiv_estimates_2022_p63.pdf"
E24 = "hiv_estimates_2024_p85.pdf"
JKL = "Jammu & Kashmir and Ladakh"

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[dict, pd.DataFrame]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--layout", "cells", "--json", "-q"])
    summary = json.loads(r.stdout)
    assert r.exit_code == summary["exit_code"], r.stdout
    cells = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return summary, cells


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    tmp = tmp_path_factory.mktemp("naco")
    return {m["fixture"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def _table(results: dict, fixture: str, table: str) -> pd.DataFrame:
    """One table as State/UT rows by column."""
    c = results[fixture][1]
    return c[c.table == table].pivot(index="state", columns="col", values="value")


def _failed(results: dict, fixture: str) -> pd.DataFrame:
    c = results[fixture][1]
    return c[c.failed != ""]


def test_every_cell_agreed(results) -> None:
    """Pin each fixture's cell count and failed checks; all four engines agree on every cell."""
    totals = {}
    for fixture, (s, _) in results.items():
        c = s["cells"]
        assert c["verified"] == c["total"], fixture
        assert s["agreement"] == {"4": c["total"]}, fixture
        assert s["checks_run"] == ["States/UTs = India", "lower <= estimate <= upper"]
        totals[fixture] = (c["total"], c["failed_checks"])
    assert totals == {
        S23: (896, 36),
        S24: (847, 190),
        E21: (1890, 3),
        E22: (805, 0),
        E24: (805, 0),
    }


def test_tables_and_states(results) -> None:
    """Pin the tables of each fixture and their State/UT rows."""
    tables = {f: c.groupby("table").state.nunique().to_dict() for f, (_, c) in results.items()}
    assert tables == {
        S23: {"Table 7.1": 39, "Table 8.1": 35, "Table 10.1": 35},
        S24: {"Table 7.1": 38, "Table 8.1": 35, "Table 10.1": 35},
        E21: {"Table 2": 35, "Table 6": 35, "Table 11": 35},
        E22: {"Annexure 5": 35},
        E24: {"Annexure 4": 35},
    }
    t = _table(results, S23, "Table 7.1")
    # SACS rows: Mumbai beside Maharashtra; DNH and Daman & Diu apart
    assert {"Mumbai", "Dadra & Nagar Haveli", "Daman & Diu", "Lakshadweep"} <= set(t.index)


def test_sankalak_values(results) -> None:
    """Pin Indian digit grouping, >= values and the same table in two editions."""
    t = _table(results, S24, "Table 10.1")
    assert t.loc["Andhra Pradesh", ["1", "2"]].tolist() == ["122433", "203454"]
    assert t.loc["India", ["1", "2"]].tolist() == ["867656", "1378262"]
    assert t.loc["Dadra & Nagar Haveli and Daman & Diu", "1"] == "-"
    t = _table(results, S23, "Table 10.1")
    assert t.loc["India", ["1", "2"]].tolist() == ["935259", "1230249"]
    t = _table(results, S23, "Table 8.1")
    ap = ["54", "213796", "3959", "10467", "≥95", "80", "86", "5"]
    assert t.loc["Andhra Pradesh"].tolist() == ap
    t = _table(results, S24, "Table 8.1")
    assert t.loc["India", "2"] == "1688965"


def test_states_add_up_to_india(results) -> None:
    """Pin the printed totals that do not add up; the other count columns do."""
    f = _failed(results, S23)
    assert f.groupby(["table", "col", "failed"]).size().to_dict() == {
        ("Table 10.1", "1", "States/UTs = India"): 35,  # off by 151, the A&N Islands value
        ("Table 7.1", "12", "lossy value"): 1,
    }
    assert f[f.failed == "lossy value"][["state", "value"]].values.tolist() == [
        ["Lakshadweep", "#DIV/0!"]
    ]
    f = _failed(results, S24)
    # Table 7.1 of 2024 prints no Ladakh row; its counts add up to less than India
    assert set(f.table) == {"Table 7.1"}
    assert sorted(set(f.col), key=int) == ["1", "2", "3", "4", "5"]
    assert "Ladakh" not in set(_table(results, S24, "Table 7.1").index)


def test_intervals(results) -> None:
    """Pin intervals split into three cells, and the one printed outside its bounds."""
    t = _table(results, E22, "Annexure 5")
    # printed "158.97 (134.99–186.68" without its closing bracket
    assert t.loc["Telangana", ["plhiv", "plhiv_lower", "plhiv_upper"]].tolist() == [
        "158.97", "134.99", "186.68"
    ]  # fmt: skip
    assert t.loc["Sikkim", ["deaths", "deaths_lower", "deaths_upper"]].tolist() == [
        "0.003", "0.001", "0.01"
    ]  # fmt: skip
    assert t.loc["India", ["new_infections_change", "evth_need"]].tolist() == ["-42.17", "20737"]
    t = _table(results, E24, "Annexure 4")
    assert t.loc["India", ["plhiv", "plhiv_lower", "plhiv_upper", "deaths"]].tolist() == [
        "2561.16", "2189.20", "3066.52", "32162"
    ]  # fmt: skip
    assert t.loc["Arunachal Pradesh", "new_infections_change"] == "+455.93"
    f = _failed(results, E21)
    assert f[["table", "state", "col", "value"]].values.tolist() == [
        ["Table 6", "India", "2018", "0.30"],
        ["Table 6", "India", "2018_lower", "0.19"],
        ["Table 6", "India", "2018_upper", "0.29"],
    ]


def test_jammu_kashmir_and_ladakh(results) -> None:
    """Pin the row whose name is printed over two lines, with its values between or beside."""
    assert _table(results, E22, "Annexure 5").loc[JKL, "plhiv"] == "6.67"
    assert _table(results, E24, "Annexure 4").loc[JKL, "plhiv"] == "6.77"
    assert _table(results, S24, "Table 10.1").loc[JKL].tolist() == ["3322", "2389"]
    # printed "65,28 (3,795-10,213)"
    t = _table(results, E21, "Table 2")
    assert t.loc[JKL, ["plhiv", "plhiv_lower", "plhiv_upper"]].tolist() == ["6528", "3795", "10213"]
    assert t.loc["India", "plhiv"] == "2401284"


def test_year_columns(results) -> None:
    """Pin columns named by their years over two pages, and wrapped State names."""
    t = _table(results, E21, "Table 6")
    years = [str(y) for y in range(2010, 2022)]
    assert [c for c in t.columns if "_" not in c] == years
    assert t.loc["Andhra Pradesh", ["2010", "2010_lower", "2010_upper", "2021"]].tolist() == [
        "1.27", "1.09", "1.50", "0.67"
    ]  # fmt: skip
    t = _table(results, E21, "Table 11")  # years repeat over three groups: numbered
    assert t.loc["Andhra Pradesh"].reindex([str(i) for i in range(1, 13)]).tolist() == [
        "74", "78", "80", "82", "75", "76", "75", "78", "60", "80", "81", "86"
    ]  # fmt: skip
    assert t.loc["Kerala", "5"] == ">=95"
