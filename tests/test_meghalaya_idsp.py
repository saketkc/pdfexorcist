"""Meghalaya IDSP monthly bulletin: surveillance totals, outbreaks by district, influenza tests."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "meghalaya_idsp"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "meghalaya_idsp" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
SUMMARY = ["event_alerts", "ongoing_outbreaks", "outbreaks"]

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
    tmp = tmp_path_factory.mktemp("meghalaya_idsp")
    return {m["fixture"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def test_every_cell_agreed(results) -> None:
    """Pin each fixture's cell count; every cell agreed and the districts add up."""
    totals = {}
    for fixture, (s, _) in results.items():
        c = s["cells"]
        assert c["verified"] == c["total"] and c["failed_checks"] == 0, fixture
        totals[fixture] = c["total"]
    assert totals == {
        "meghalaya_idsp_2026-07.pdf": 60,
        "meghalaya_idsp_2025-06_p1.pdf": 23,
        "meghalaya_idsp_2023-07_p1_4.pdf": 6,
    }


def test_surveillance(results) -> None:
    """Counts above their Cases/Deaths or Samples Tested/Positive headings, by panel."""
    t = results["meghalaya_idsp_2026-07.pdf"][1].loc["surveillance"]
    assert t.loc["syndromic", ["reporting_status", "cases", "deaths"]].tolist() == [
        "87.73", "23269", "0"
    ]  # fmt: skip
    assert t.loc["presumptive", ["cases", "deaths"]].tolist() == ["69712", "2"]
    assert t.loc["laboratory", ["reporting_status", "cases", "deaths"]].tolist() == [
        "91.59", "3311", "0"
    ]  # fmt: skip
    t = results["meghalaya_idsp_2025-06_p1.pdf"][1].loc["surveillance"]
    assert t.loc["presumptive", ["cases", "deaths"]].tolist() == ["75,063", "1"]
    assert t.loc["laboratory", ["samples_tested", "positive"]].tolist() == ["46,314", "3091"]
    t = results["meghalaya_idsp_2023-07_p1_4.pdf"][1].loc["surveillance"]
    assert t["reporting_status"].tolist() == ["88.91", "90.87", "91.75"]


def test_outbreaks(results) -> None:
    """The district panel beside the score tables, and the summary counts since 1 January."""
    t = results["meghalaya_idsp_2026-07.pdf"][1]
    d = t.loc["outbreaks", "outbreaks"]
    assert len(d) == 13 and d["Meghalaya"] == "31" and d["East Khasi Hills"] == "12"
    assert d["Eastern West Khasi Hills"] == "5" and d["West Khasi Hills"] == "2"
    assert t.loc[("summary", "Meghalaya"), SUMMARY].tolist() == ["263", "16", "31"]
    t = results["meghalaya_idsp_2025-06_p1.pdf"][1]
    assert "East Garo Hills" not in t.loc["outbreaks"].index  # not printed
    assert t.loc[("summary", "Meghalaya"), SUMMARY].tolist() == ["50", "02", "35"]
    t = results["meghalaya_idsp_2023-07_p1_4.pdf"][1]
    assert "outbreaks" not in t.index.get_level_values("table")
    assert t.loc[("summary", "Meghalaya"), SUMMARY].tolist() == ["37", "4", "35"]


def test_influenza(results) -> None:
    """The monthly influenza table, one row per month, its last row on the next page."""
    t = results["meghalaya_idsp_2026-07.pdf"][1].loc["influenza"]
    assert list(t.index) == [f"2026-{m:02d}" for m in range(1, 8)]
    assert t.loc["2026-03", ["tested", "h1n1", "h3n2", "rsv", "covid19"]].tolist() == [
        "44", "0", "0", "0", "0"
    ]  # fmt: skip
    assert t.loc["2026-07", "tested"] == "7"
