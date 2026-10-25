"""Haryana daily influenza report: H1N1 and H3N2 cases and deaths by district."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "haryana_influenza"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "haryana_influenza" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
COLS = ["day_cases", "cum_cases", "cum_deaths"]

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[dict, pd.DataFrame]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    assert r.exit_code == 0, r.stdout
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return json.loads(r.stdout), table.set_index(["subtype", "district"])


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    tmp = tmp_path_factory.mktemp("hr_influenza")
    return {m["fixture"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def test_every_cell_agreed_and_balances(results) -> None:
    """22 districts and Total, two subtypes, three counts: every cell agreed and checked."""
    for fixture, (s, t) in results.items():
        c = s["cells"]
        assert c["verified"] == c["total"] == 23 * 2 * 3, fixture
        assert c["failed_checks"] == 0 and len(s["checks_run"]) == 3, fixture
        assert set(t.index.get_level_values("subtype")) == {"H1N1", "H3N2"}
        names = set(t.loc["H1N1"].index)
        assert len(names) == 23 and {"Total", "Charkhi Dadri", "Yamunanagar", "Nuh"} <= names


def test_pinned_rows(results) -> None:
    """Pin rows against the printed table, the state status table left out."""
    t = results["hr_influenza_2026-09-29_p1.pdf"][1]
    assert t.loc[("H1N1", "Sonipat"), COLS].tolist() == ["6", "24", "2"]
    assert t.loc[("H3N2", "Palwal"), COLS].tolist() == ["1", "1", "0"]
    assert t.loc[("H1N1", "Total"), COLS].tolist() == ["11", "554", "14"]
    assert "Confirmed cases" not in t.loc["H1N1"].index
    t = results["hr_influenza_2026-10-23_p1.pdf"][1]
    assert t.loc[("H1N1", "Kurukshetra"), COLS].tolist() == ["1", "30", "2"]
    assert t.loc[("H3N2", "Yamunanagar"), COLS].tolist() == ["0", "2", "1"]
    assert t.loc[("H1N1", "Total"), COLS].tolist() == ["1", "579", "17"]
    assert t.loc[("H3N2", "Total"), COLS].tolist() == ["0", "24", "1"]
