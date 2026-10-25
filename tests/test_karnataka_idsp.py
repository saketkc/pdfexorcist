"""Karnataka IDSP weekly infectious disease report."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "karnataka_idsp"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "karnataka_idsp" / "recipe.toml"
DISEASES = [
    "SARI", "Influenza", "Acute Diarrhoeal Diseases (ADD)", "Dog Bites & Human Rabies Deaths",
    "Snake bites", "Leptospirosis", "Kyasanur Forest Disease (KFD)", "Dengue", "Chikungunya",
    "Malaria", "Japanese Encephalitis (JE)", "Diphtheria", "Measles", "COVID-19",
]  # fmt: skip

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[int, dict, pd.DataFrame]:
    """(exit code, JSON summary, the CSV table) of the recipe on a copy of a fixture."""
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return r.exit_code, json.loads(r.stdout), table


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[int, tuple[int, dict, pd.DataFrame]]:
    """Each fixture's result by its week."""
    tmp = tmp_path_factory.mktemp("idsp")
    weeks = {41: "karnataka_idsp_2026_week41.pdf", 45: "karnataka_idsp_2023_week45.pdf"}
    weeks[44] = "karnataka_idsp_2023_week44.pdf"
    return {week: _extract(tmp, fixture) for week, fixture in weeks.items()}


@pytest.fixture(scope="module")
def result(results) -> tuple[int, dict, pd.DataFrame]:
    return results[41]


def test_every_disease_by_name(result) -> None:
    """Pin the 14 diseases as printed, in order, every cell agreed."""
    code, s, t = result
    assert code == 0 and s["cells"]["failed_checks"] == 0 and len(s["checks_run"]) == 1
    assert s["cells"]["verified"] == s["cells"]["total"] == 48
    assert list(dict.fromkeys(t.disease)) == DISEASES
    assert set(t.week) == {"41"}


def test_values(result) -> None:
    """Pin values beside the charts, last month for malaria, and the Indian commas."""
    t = result[2].set_index(["disease", "measure"])
    assert t.loc[("SARI", "cases"), ["last_week", "current_year"]].tolist() == ["307", "8050"]
    assert t.loc[("Dog Bites & Human Rabies Deaths", "deaths"), "current_year"] == "47"
    assert t.loc[("Malaria", "tested"), ["last_week", "last_month", "current_year"]].tolist() == [
        "", "1189515", "9529475"
    ]  # fmt: skip
    assert t.loc[("Measles", "reported cases"), "current_year"] == "1714"
    assert t.loc[("COVID-19", "positives"), "current_year"] == "288"


def test_first_layout(results) -> None:
    """2023: "Rabies" heads the dog bite deaths, snake bites have no deaths, no COVID-19 box,
    and the dengue figures run together in the text ("1,01,440 13,338")."""
    code, s, t = results[45]
    assert code == 0 and s["cells"]["verified"] == s["cells"]["total"] == 42
    assert set(t.week) == {"45"} and "COVID-19" not in set(t.disease)
    t = t.set_index(["disease", "measure"])
    assert t.loc[("Dog Bites", "deaths"), ["last_week", "current_year"]].tolist() == ["00", "03"]
    assert t.loc[("Dog Bites", "bites"), "current_year"] == "194121"
    assert ("Snake bites", "deaths") not in t.index
    assert t.loc[("Dengue", "tested"), ["last_week", "current_year"]].tolist() == ["3200", "101440"]
    assert t.loc[("Dengue", "positives"), "current_year"] == "13338"
    assert t.loc[("Malaria", "tested"), "current_year"] == "9563391"


def test_wide_box_without_charts(results) -> None:
    """Week 44 of 2023 spreads COVID-19's tested, positives and deaths wider than its heading."""
    code, s, t = results[44]
    assert code == 0 and s["cells"]["verified"] == s["cells"]["total"] == 46
    covid = t[t.disease == "COVID-19"].set_index("measure")
    assert covid.loc[["tested", "positives", "deaths"], "last_week"].tolist() == ["1259", "10", "0"]
    assert covid.loc[["tested", "positives", "deaths"], "current_year"].tolist() == [
        "1542664", "16870", "51"
    ]  # fmt: skip
