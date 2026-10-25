"""State Health Society Bihar IDSP: weekly disease bulletin and monthly outbreak summary."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
RECIPES = ROOT / "pdfexorcist" / "recipes"
WEEK = ["prev_week", "week", "prev_cum", "cum"]
MONTH = ["outbreaks", "cases", "deaths"]

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, dataset: str, fixture: str, index: list[str]) -> tuple[dict, pd.DataFrame]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / dataset / fixture, pdf)
    recipe = RECIPES / dataset / "recipe.toml"
    r = run(["extract", str(pdf), "--recipe", str(recipe), "--json", "-q"])
    assert r.exit_code == 0, r.stdout
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return json.loads(r.stdout), table.set_index(index)


def _all(tmp: Path, dataset: str, index: list[str]) -> dict[str, tuple[dict, pd.DataFrame]]:
    manifest = csv.DictReader((FIXTURES / dataset / "manifest.csv").open(encoding="utf-8"))
    return {m["fixture"]: _extract(tmp, dataset, m["fixture"], index) for m in manifest}


@pytest.fixture(scope="module")
def weekly(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    return _all(
        tmp_path_factory.mktemp("bihar_weekly"), "bihar_idsp_weekly", ["disease", "measure"]
    )


@pytest.fixture(scope="module")
def monthly(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    index = ["disease", "district", "n"]
    return _all(tmp_path_factory.mktemp("bihar_monthly"), "bihar_idsp_monthly", index)


def test_weekly_every_cell_agreed(weekly) -> None:
    """All 22 diseases, every cell agreed and the three checks pass."""
    for fixture, (s, t) in weekly.items():
        c = s["cells"]
        assert c["verified"] == c["total"] and c["failed_checks"] == 0, fixture
        assert len(s["checks_run"]) == 3, fixture
        assert t.index.get_level_values("disease").nunique() == 22, fixture
    assert weekly["bihar_weekly_2016_w13.pdf"][0]["cells"]["total"] == 122
    assert weekly["bihar_weekly_2013_w30.pdf"][0]["cells"]["total"] == 116


def test_weekly_pinned(weekly) -> None:
    """Counts, tested/positive pairs and stars as printed."""
    t = weekly["bihar_weekly_2016_w13.pdf"][1]
    assert t.loc[("Malaria", "cases"), WEEK].tolist() == ["523", "535", "5703", "6428"]
    assert t.loc[("Acute Diarrhoeal Disease", "cases"), WEEK].tolist() == [
        "10825", "10307", "130304", "113072"
    ]  # fmt: skip
    assert t.loc[("Typhoid Fever", "tested"), WEEK].tolist() == ["631", "520", "5963", "5549"]
    assert t.loc[("Typhoid Fever", "positive"), WEEK].tolist() == ["305", "220", "2108", "2004"]
    assert t.loc[("Chikungunya", "starred"), WEEK].tolist() == ["1", "1", "1", "1"]
    assert t.loc[("Dengue", "starred"), WEEK].tolist() == ["1", "", "", ""]
    t = weekly["bihar_weekly_2013_w30.pdf"][1]
    # counts between "Acute Encephalitis Syndrome/" and "Japanese Encephalitis", one clipped
    assert t.loc[("AES/JE", "tested"), WEEK].tolist() == ["26", "0", "219", "114"]
    assert t.loc[("AES/JE", "positive"), WEEK].tolist() == ["6", "0", "11", "9"]
    assert t.loc[("Measles", "cases"), WEEK].tolist() == ["2", "3", "2781", "674"]
    assert ("Measles", "starred") not in t.index


def test_monthly_every_cell_agreed(monthly) -> None:
    """Each row read; the 2017 rows add up to their Total row."""
    rows = {}
    for fixture, (s, t) in monthly.items():
        c = s["cells"]
        assert c["verified"] == c["total"] and c["failed_checks"] == 0, fixture
        rows[fixture] = len(t)
    assert rows == {"bihar_monthly_2017-08_p5.pdf": 20, "bihar_monthly_2012-09_p4.pdf": 19}


def test_monthly_pinned(monthly) -> None:
    """Rows as printed, wrapped names joined to the row they belong to."""
    t = monthly["bihar_monthly_2017-08_p5.pdf"][1]
    assert t.loc[("Total", "", "1"), MONTH].tolist() == ["24", "198", "7"]
    assert t.loc[("Acute Diarrhoea", "Jahanabad", "1"), MONTH].tolist() == ["2", "17", "3"]
    assert t.loc[("H1N1 A (Influenza)", "Gopalganj", "1"), MONTH].tolist() == ["1", "3", "0"]
    t = monthly["bihar_monthly_2012-09_p4.pdf"][1]
    event = "Unusual event (related to consumption of Albendazole tablets)"
    assert t.loc[(event, "Gopalganj", "1"), MONTH].tolist() == ["1", "34", "0"]
    assert t.loc[("Food Poisoning", "East Champaran", "1"), MONTH].tolist() == ["1", "93", "0"]
    assert t.loc[("Diarrhoea", "Siwan", "1"), MONTH].tolist() == ["11", "54", "3"]


@pytest.fixture(scope="module")
def sheets(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    index = ["page", "table", "district"]
    return _all(tmp_path_factory.mktemp("bihar_sheets"), "bihar_idsp_sheets", index)


def test_sheets_every_cell_agreed(sheets) -> None:
    """38 districts and the TOTAL row, every cell agreed, districts add up to the total."""
    months = {}
    for fixture, (s, t) in sheets.items():
        c = s["cells"]
        assert c["verified"] == c["total"] and c["failed_checks"] == 0, fixture
        assert s["checks_run"] == ["districts = total"], fixture
        assert len(t) == 39, fixture
        months[fixture] = len(t.columns)
    assert months == {
        "bihar_sheets_2016-06_p77.pdf": 6,
        "bihar_sheets_2013-12_p86.pdf": 12,
        "bihar_sheets_2012-09_p88.pdf": 9,
    }


def test_sheets_pinned(sheets) -> None:
    """Counts as printed, months named by their first three letters."""
    t = sheets["bihar_sheets_2016-06_p77.pdf"][1]
    assert t.loc[("1", "1", "ARARIA")].tolist() == ["973", "511", "1299", "1679", "1614", "1692"]
    assert t.loc[("1", "1", "Total"), "JUN"] == "41829"
    t = sheets["bihar_sheets_2013-12_p86.pdf"][1]
    assert t.loc[("1", "1", "SARAN"), ["OCT", "NOV", "DEC"]].tolist() == ["430", "0", "2"]
    assert t.loc[("1", "1", "Total"), "DEC"] == "50709"
    t = sheets["bihar_sheets_2012-09_p88.pdf"][1]
    assert t.loc[("1", "1", "WEST CHAMPARAN (BETTIAH)"), "SEP"] == "2968"
    assert t.loc[("1", "1", "Total"), "SEP"] == "89222"
