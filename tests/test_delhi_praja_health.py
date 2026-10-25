"""Praja State of Health in Delhi: cases by MCD zone, and Delhi's MCD and state facilities."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "delhi_praja_health"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "delhi_praja_health" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[dict, pd.DataFrame]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    assert r.exit_code == 0, r.stdout
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return json.loads(r.stdout), table.set_index(["table", "row"])


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    tmp = tmp_path_factory.mktemp("praja_delhi")
    return {m["fixture"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def test_zones_by_financial_year_with_corporations(results) -> None:
    """15 zones and Total, four years; corporation labels and population left out."""
    s, t = results["praja_delhi_2018_p45.pdf"]
    c = s["cells"]
    assert c["verified"] == c["total"] == 16 * 4 and c["failed_checks"] == 0
    years = ["2014-15", "2015-16", "2016-17", "2017-18"]
    assert sorted(col for col in t.columns if col[0].isdigit()) == years
    z = t.loc["Table 29"]
    assert "EDMC" not in z.index and (z["kind"] == "zone").sum() == 15
    assert z.loc["Shahdara South", years].tolist() == ["1348", "559", "200", "345"]
    assert z.loc["New Delhi Municipal Council", years].tolist() == ["0", "7", "2", "0"]
    assert z.loc["Total", years].tolist() == ["7723", "9445", "6111", "4205"]


def test_delhi_and_zone_tables_on_one_page(results) -> None:
    """The facility rows with deaths, the zone rows with their Total column, % change left out."""
    s, t = results["praja_delhi_2022_p34.pdf"]
    c = s["cells"]
    assert c["verified"] == c["total"] and c["failed_checks"] == 0
    years = [str(y) for y in range(2014, 2022)]
    delhi, zones = t.loc["Table 22"], t.loc["Table 23"]
    assert set(delhi["disease"]) == set(zones["disease"]) == {"Dengue"}
    assert delhi.loc["State Hospital", years].tolist()[:3] == ["508", "17900", "4480"]
    assert delhi.loc["Total Cases", years].tolist()[-1] == "3978"
    assert delhi.loc["Total Deaths", "kind"] == "deaths"
    assert delhi.loc["Total Deaths", years].tolist()[:2] == ["74", "486"]
    assert zones.loc["Shahdara South", "Total"] == "2928" and (zones["kind"] == "zone").sum() == 15


def test_year_repeated_in_change_heading(results) -> None:
    """2022 is printed twice on the year line ("% Change 2022 to 2023"): the first is a year."""
    s, t = results["praja_delhi_2024_p37.pdf"]
    c = s["cells"]
    assert c["verified"] == c["total"] == 8 * 10 and c["failed_checks"] == 0
    d = t.loc["Table 29"]
    assert d.loc["Total Cases", "2022"] == "15459" and d.loc["Total Deaths", "2023"] == "36"
    assert d.loc["State Dispensaries", ["2021", "2022", "2023"]].tolist() == ["933", "912", "3565"]
