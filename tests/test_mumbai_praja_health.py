"""Praja Mumbai health white paper: cases registered in BMC dispensaries by ward and year."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "mumbai_praja_health"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "mumbai_praja_health" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[dict, pd.DataFrame]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    assert r.exit_code == 0, r.stdout
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return json.loads(r.stdout), table.set_index("row")


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    tmp = tmp_path_factory.mktemp("praja_health")
    return {m["fixture"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def test_financial_years_with_hospitals_and_total(results) -> None:
    """24 wards, three hospital rows (one label wrapped) and Total, five years, all balanced."""
    s, t = results["praja_health_2017_p43.pdf"]
    c = s["cells"]
    assert c["verified"] == c["total"] == 28 * 5 and c["failed_checks"] == 0
    years = ["2012-13", "2013-14", "2014-15", "2015-16", "2016-17"]
    assert sorted(col for col in t.columns if col[0].isdigit()) == years  # population left out
    assert set(t["disease"]) == {"Tuberculosis"} and set(t["table"]) == {"Table 30"}
    assert t.loc["F/S", years].tolist() == ["185", "14", "438", "239", "176"]
    assert t.loc["Other Government Hospital", years].tolist() == ["593", "606", "482", "464", "432"]
    assert t.loc["Total", years].tolist() == ["36417", "41479", "42837", "41172", "50001"]
    assert (t["kind"] == "ward").sum() == 24


def test_calendar_years_with_total_column(results) -> None:
    """Ten calendar years and the Total column; the rate per 1,00,000 is left out."""
    s, t = results["praja_health_2024_p41.pdf"]
    c = s["cells"]
    assert c["verified"] == c["total"] == 24 * 11 and c["failed_checks"] == 0
    years = [str(y) for y in range(2014, 2024)]
    cols = sorted(col for col in t.columns if col[0].isdigit() or col == "Total")
    assert cols == [*years, "Total"]
    assert t.loc["A", [*years, "Total"]].tolist()[8:] == ["2382", "202", "4819"]
    assert t.loc["M/W", "2014"] == "62" and t.loc["F/S", "Total"] == "6114"
    assert "Total" not in t.index
