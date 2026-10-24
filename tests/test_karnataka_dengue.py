"""Karnataka daily dengue and chikungunya report: counts by district, on the day and cumulative."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "karnataka_dengue"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "karnataka_dengue" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
DAY = ["day_suspected", "day_sampled", "day_igm", "day_ns1", "day_positive", "day_deaths"]
CUM = ["cum_suspected", "cum_sampled", "cum_igm", "cum_ns1", "cum_positive", "cum_deaths"]

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[dict, pd.DataFrame]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    assert r.exit_code == 0, r.stdout
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return json.loads(r.stdout), table.set_index(["disease", "district"])


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    tmp = tmp_path_factory.mktemp("ka_dengue")
    return {m["fixture"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def test_every_cell_agreed_and_balances(results) -> None:
    """Pin each fixture's cell count; every cell agreed and every check passed."""
    totals = {}
    for fixture, (s, t) in results.items():
        c = s["cells"]
        assert c["verified"] == c["total"] and c["failed_checks"] == 0, fixture
        assert len(s["checks_run"]) == 5
        assert set(t.index.get_level_values("disease")) == {"Dengue", "Chikungunya"}
        totals[fixture] = c["total"]
    assert totals == {
        "ka_dengue_2023-08-05.pdf": 802,
        "ka_dengue_2021-12-01.pdf": 768,
        "ka_dengue_2022-02-28.pdf": 744,
    }


def test_districts(results) -> None:
    """30 districts in 2021, 31 from 2023 (Vijaya nagar), plus Total and BBMP on each page."""
    for fixture, n in [("ka_dengue_2021-12-01.pdf", 30), ("ka_dengue_2023-08-05.pdf", 31)]:
        t = results[fixture][1]
        for disease in ("Dengue", "Chikungunya"):
            names = set(t.loc[disease].index)
            assert {"Total", "Bangaluru City (BBMP)", "Bangaluru (U)"} <= names
            assert len(names) == n + 2, (fixture, disease)
    assert "Vijaya nagar" in results["ka_dengue_2023-08-05.pdf"][1].loc["Dengue"].index


def test_blank_day_cells_stay_blank(results) -> None:
    """Pin a row with blank day cells and one with every cell printed."""
    t = results["ka_dengue_2023-08-05.pdf"][1]
    row = t.loc[("Dengue", "Bangaluru (U)")]
    assert row[["blocks", "taluks", "phc", "villages", "population"]].tolist() == [
        "4", "2", "12", "19", "60480"
    ]  # fmt: skip
    assert row[DAY].tolist() == [""] * 6
    assert row[CUM].tolist() == ["101", "52", "20", "0", "20", "0"]
    row = t.loc[("Dengue", "Shivamogga")]
    assert row[DAY].tolist() == ["159", "55", "5", "3", "8", "0"]
    assert row[CUM].tolist() == ["6117", "3185", "72", "75", "147", "0"]


def test_totals_and_bbmp(results) -> None:
    """Pin the State total and the BBMP row, printed apart from the districts."""
    t = results["ka_dengue_2023-08-05.pdf"][1]
    total = t.loc[("Dengue", "Total")]
    assert total[["population", *DAY]].tolist() == ["2538665", "733", "389", "28", "16", "44", "0"]
    assert total[CUM].tolist() == ["57689", "35993", "1576", "863", "2439", "0"]
    bbmp = t.loc[("Dengue", "Bangaluru City (BBMP)")]
    assert bbmp[["blocks", "taluks", *DAY]].tolist() == [
        "", "0", "925", "901", "85", "382", "467", "0"
    ]  # fmt: skip
    assert bbmp["cum_positive"] == "2969"
    t = results["ka_dengue_2021-12-01.pdf"][1]
    assert t.loc[("Dengue", "Total"), "cum_deaths"] == "5"


def test_chikungunya_others(results) -> None:
    """The chikungunya page prints "Others" where dengue prints NS1."""
    t = results["ka_dengue_2021-12-01.pdf"][1]
    total = t.loc[("Chikungunya", "Total")]
    assert total[["cum_igm", "cum_others", "cum_positive", "cum_ns1"]].tolist() == [
        "1779", "0", "1779", ""
    ]  # fmt: skip
    t = results["ka_dengue_2023-08-05.pdf"][1]
    shiv = t.loc[("Chikungunya", "Shivamogga")]
    assert shiv[["day_suspected", "day_igm", "day_others", "day_positive"]].tolist() == [
        "55", "2", "0", "2"
    ]  # fmt: skip


def test_hard_rows(results) -> None:
    """Pin a row whose values the text layer prints below its name, and columns whose
    sideways headings pdfium reads blank."""
    t = results["ka_dengue_2021-12-01.pdf"][1]
    row = t.loc[("Dengue", "Vijayapura")]
    assert row[["blocks", "taluks", "phc", "villages", "population"]].tolist() == [
        "5", "5", "40", "86", "200450"
    ]  # fmt: skip
    assert row[CUM].tolist() == ["2198", "1976", "178", "88", "266", "0"]
    t = results["ka_dengue_2022-02-28.pdf"][1]
    row = t.loc[("Dengue", "Yadageri")]
    assert row[["phc", "cum_suspected", "day_suspected", "day_sampled"]].tolist() == [
        "5", "204", "143", "90"
    ]  # fmt: skip
