"""INSP (DR Congo) Ebola situation reports: cases and deaths by province and health zone."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "insp_sitrep"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "insp_sitrep" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[dict, pd.DataFrame]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    assert r.exit_code == 0, r.stdout
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return json.loads(r.stdout), table.set_index(["table", "province", "zone"])


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    tmp = tmp_path_factory.mktemp("insp")
    return {m["fixture"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def test_every_cell_agreed_and_balances(results) -> None:
    """Pin each fixture's cell count; every cell agreed and every province adds up."""
    totals = {}
    for fixture, (s, _) in results.items():
        c = s["cells"]
        assert c["verified"] == c["total"] and c["failed_checks"] == 0, fixture
        assert len(s["checks_run"]) == 3
        totals[fixture] = c["total"]
    assert totals == {
        "insp_sitrep_026_p4.pdf": 93,
        "insp_sitrep_087_p2.pdf": 204,
        "insp_sitrep_102_p2-3.pdf": 363,
        "insp_sitrep_160_p2-4.pdf": 429,
    }


def test_blank_cells_stay_blank(results) -> None:
    """Pin rows with blank day columns: a value keeps its column instead of moving left."""
    t = results["insp_sitrep_160_p2-4.pdf"][1]
    cols = ["cases", "deaths", "new_cases", "community_deaths", "cte_deaths", "new_deaths"]
    assert t.loc[("zones", "Ituri", "Mongbwalu"), cols].tolist() == ["717", "346", "", "", "", "0"]
    assert t.loc[("zones", "Ituri", "Mangala"), cols].tolist() == ["382", "166", "", "", "1", "1"]
    assert t.loc[("zones", "Nord-Kivu", "Kalunguta"), cols].tolist() == [
        "84", "31", "3", "", "", "0"
    ]  # fmt: skip


def test_rows_across_pages(results) -> None:
    """Pin a continued page's first row (above its first rule) and a zone named as its province."""
    t = results["insp_sitrep_160_p2-4.pdf"][1]
    assert t.loc[("zones", "Ituri", "Mangala"), "page"] == "2"
    assert t.loc[("zones", "Tshopo", "Tshopo"), ["cases", "page"]].tolist() == ["3", "3"]
    assert t.loc[("zones", "Tshopo", "Total"), "cases"] == "76"
    assert "Boma Mangbetu" in t.loc["zones"].loc["Haut-Uélé"].index
    assert "Wanie-Rukula" in t.loc["zones"].loc["Tshopo"].index


def test_merged_label_cells(results) -> None:
    """Pin zones whose names share one drawn cell, with and without rules between rows."""
    t = results["insp_sitrep_160_p2-4.pdf"][1]
    buta = t.loc["zones"].loc["Bas Uélé"]
    assert buta["cases"].to_dict() == {
        "Total": "13", "Buta": "1", "Viadana": "6", "Dakwa": "1", "Ganga": "5"
    }  # fmt: skip
    t = results["insp_sitrep_102_p2-3.pdf"][1]
    assert t.loc["zones"].loc["Bas Uélé"]["cases"].to_dict() == {
        "Total": "3", "Buta": "1", "Viadana": "1", "Ganga": "1"
    }  # fmt: skip
    assert t.loc[("zones", "Total", "Total"), ["cases", "deaths", "new_deaths"]].tolist() == [
        "5656", "2715", "35"
    ]  # fmt: skip
    assert t.loc[("provinces", "Total", ""), "cases"] == "5656"


def test_dotted_rules(results) -> None:
    """Pin a table whose rules are drawn as dots, with provinces as section rows."""
    t = results["insp_sitrep_026_p4.pdf"][1]
    assert t.loc[("zones", "ITURI", "Bunia"), ["cases", "deaths", "cfr"]].tolist() == [
        "173", "15", "8,7%"
    ]  # fmt: skip
    assert t.loc[("zones", "NORD-KIVU", "Total"), "cases"] == "32"  # "Sous-total Nord-Kivu"
    assert t.loc[("zones", "Total", "Total"), "cases"] == "635"


def test_daily_table(results) -> None:
    """Pin the day-only layout, whose province cell is merged over its zones."""
    t = results["insp_sitrep_087_p2.pdf"][1]
    assert set(t.index.get_level_values("table")) == {"zones_daily"}
    assert t.loc[("zones_daily", "Ituri", "Bunia"), ["new_cases", "cte_deaths"]].tolist() == [
        "12", "ND"
    ]  # fmt: skip
    assert t.loc[("zones_daily", "Nord-Kivu", "Total"), "new_deaths"] == "12"
