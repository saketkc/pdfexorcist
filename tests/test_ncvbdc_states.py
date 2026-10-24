"""NCVBDC State/UT situation tables: dengue, chikungunya and malaria by year."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

from pdfexorcist.checks import validate
from pdfexorcist.recipe import load

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "ncvbdc_states"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "ncvbdc_states" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
DENGUE = "ncvbdc_dengue_2021-2026.pdf"
CHIK = "ncvbdc_chikungunya_2021-2026.pdf"
MALARIA = "ncvbdc_malaria_2022-2026.pdf"
MALARIA_FEB = "ncvbdc_malaria_2021-2025.pdf"
MALARIA_JUN = "ncvbdc_malaria_2021-2025_jun.pdf"

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """(JSON summary, the table by State, one row per cell) for one fixture."""
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    assert r.exit_code == 0, r.stdout
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    out = tmp / f"{pdf.stem}_cells.csv"
    args = ["extract", str(pdf), "--recipe", str(RECIPE), "--layout", "cells", "-o", str(out)]
    c = run([*args, "-q"])
    assert c.exit_code == 0, c.stdout
    cells = pd.read_csv(out, dtype=str, keep_default_na=False)
    return json.loads(r.stdout), table.set_index("state"), cells


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict:
    tmp = tmp_path_factory.mktemp("ncvbdc")
    return {m["fixture"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def test_every_cell_agreed_and_adds_up(results) -> None:
    """Pin each fixture's cell count; every cell agreed and the States add up to Total."""
    totals = {}
    for fixture, (s, _, _) in results.items():
        c = s["cells"]
        assert c["verified"] == c["total"] and c["unresolved"] == 0, fixture
        assert c["failed_checks"] == 0 and len(s["checks_run"]) == 1, fixture
        totals[fixture] = c["total"]
    # rows x (years x measures): 37 + Total x 12, 35 + Total x 12, 36 + India x 20
    assert totals == {DENGUE: 456, CHIK: 432, MALARIA: 740, MALARIA_FEB: 740, MALARIA_JUN: 740}


def test_columns_by_year_and_measure(results) -> None:
    """Pin the columns each disease prints and the provisional year's period."""
    malaria = ["tested", "positive", "pf", "deaths"]
    chik = ["suspected cases", "confirmed cases"]
    jun = ["tested", "malaria cases", "pf cases", "deaths"]
    want = {  # fixture: (disease, years, measures, rows, the last year's period)
        DENGUE: ("dengue", "2021-2026", ["cases", "deaths"], 38, "Prov till 30th April"),
        CHIK: ("chikungunya", "2021-2026", chik, 36, "Prov. till 30th April"),
        MALARIA: ("malaria", "2022-2026", malaria, 37, "Upto August"),
        MALARIA_FEB: ("malaria", "2021-2025", malaria, 37, "Provisional"),
        MALARIA_JUN: ("malaria", "2021-2025", jun, 37, "Upto June"),
    }  # fmt: skip
    for fixture, (disease, span, measures, rows, period) in want.items():
        _, t, cells = results[fixture]
        first, last = map(int, span.split("-"))
        assert t.columns.tolist() == ["sno", "disease"] + [
            f"{y} {m}" for y in range(first, last + 1) for m in measures
        ], fixture
        assert len(t) == rows and t.disease.unique().tolist() == [disease], fixture
        periods = cells.drop_duplicates("year").set_index("year").period
        assert periods.loc[str(last)] == period, fixture
        assert set(periods.drop(str(last))) == {""}, fixture


def test_dengue_rows(results) -> None:
    """Pin footnoted and NR cells, the merged serial and the Non endemic row."""
    t = results[DENGUE][1]
    cols = ["2023 cases", "2024 cases", "2025 cases", "2025 deaths"]
    assert t.loc["West Bengal", cols].tolist() == ["30683*", "441**", "NR", "NR"]
    assert t.loc[["D&N Haveli", "Daman & Diu"], "sno"].tolist() == ["32", "32"]
    assert t.loc["Daman & Diu", "2023 deaths"] == "1"
    assert set(t.loc["Ladakh"].iloc[2:]) == {"Non endemic"}
    assert t.loc["Total"].iloc[2:6].tolist() == ["193245", "346", "233251", "303"]
    assert t.loc["Kerala", ["2023 deaths", "2026 cases", "2026 deaths"]].tolist() == [
        "153", "1403", "10"
    ]  # fmt: skip


def test_chikungunya_merged_nr(results) -> None:
    """Pin NR merged over one year's two columns and over two years."""
    t = results[CHIK][1]
    cols = ["2021 suspected cases", "2021 confirmed cases", "2022 suspected cases"]
    assert t.loc["Chhattisgarh", cols].tolist() == ["NR", "NR", "252"]
    assert t.loc["Nagaland", [*cols, "2022 confirmed cases", "2023 suspected cases"]].tolist() == [
        "NR", "NR", "NR", "NR", "72"
    ]  # fmt: skip
    assert t.loc["West Bengal", ["2023 suspected cases", "2025 suspected cases"]].tolist() == [
        "762*", "NR"
    ]  # fmt: skip
    assert t.loc["Total", "2026 confirmed cases"] == "995"


def test_malaria_rows(results) -> None:
    """Pin the India row (named Total) and the wrapped UT name."""
    t = results[MALARIA][1]
    assert t.loc["Total", ["2022 tested", "2026 deaths"]].tolist() == ["152049892", "33"]
    dnh = "The Dadra And Nagar Haveli And Daman And Diu"
    assert t.loc[dnh, ["sno", "2022 tested", "2023 deaths"]].tolist() == ["32", "131198", "1"]


def test_malaria_serial_in_the_state_cell(results) -> None:
    """Pin serials some engines read into the name ("2Andhra Pradesh", "1Islands")."""
    t = results[MALARIA_FEB][1]
    first = ["Andaman And Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh"]
    assert t.index[:3].tolist() == first
    assert t.sno[:3].tolist() == ["1", "2", "3"]
    assert t.loc["Andhra Pradesh", ["2021 tested", "2025 deaths"]].tolist() == ["7336198", "8"]
    # the same counts in two releases
    jun = results[MALARIA_JUN][1].loc["Andhra Pradesh"]
    assert jun["2021 malaria cases"] == t.loc["Andhra Pradesh", "2021 positive"] == "1315"


def test_numbers_for_the_checks(results) -> None:
    """Pin number: footnote marks dropped, NR and Non endemic left empty."""
    cells = results[DENGUE][2].set_index(["state", "col"])
    assert cells.loc[("West Bengal", "2023 cases"), "number"] in ("30683", "30683.0")
    assert cells.loc[("West Bengal", "2025 cases"), "number"] == ""
    assert cells.loc[("Ladakh", "2021 cases"), "number"] == ""


def test_a_wrong_total_is_flagged(results) -> None:
    """Pin the check failing the one column whose part is off by one."""
    cells = results[DENGUE][2].copy()
    cells["number"] = pd.to_numeric(cells.number, errors="coerce")
    kerala = (cells.state == "Kerala") & (cells.col == "2023 cases")
    cells.loc[kerala, "number"] += 1
    out = validate(cells, load(RECIPE).check_functions())
    assert set(out[out.failed != ""].col) == {"2023 cases"}
