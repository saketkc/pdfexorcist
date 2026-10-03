"""NFHS-5 example recipes."""

import json
import shutil
from pathlib import Path

import pandas as pd
from cli_helpers import run

ROOT = Path(__file__).parent.parent
EXAMPLES = ROOT / "examples"
FIXTURES = Path(__file__).parent / "fixtures"


def _extract(fixture: Path, recipe: str) -> tuple[dict, pd.DataFrame]:
    shutil.copy(fixture, "sheet.pdf")
    recipe_path = str(EXAMPLES / recipe)
    r = run(["extract", "sheet.pdf", "--recipe", recipe_path, "--json", "-q", "--force"])
    assert r.exit_code == 0, r.output
    table = pd.read_csv("sheet.csv", dtype=str, keep_default_na=False)
    return json.loads(r.stdout), table.set_index(["geo", "indicator_no"])


def test_example_state_recipe(tmp_path, monkeypatch) -> None:
    """Pin India rows, columns, printed forms, and rules."""
    monkeypatch.chdir(tmp_path)
    s, t = _extract(FIXTURES / "nfhs5_state" / "nfhs5_india_p3-6.pdf", "nfhs5/state.toml")
    assert s["cells"]["verified"] == 524 and s["cells"]["failed_checks"] == 0
    assert len(s["checks_run"]) == 2
    assert len(t) == 131
    assert list(t.columns) == ["level", "nfhs5_urban", "nfhs5_rural", "nfhs5_total", "nfhs4_total"]
    assert t.loc[("India", "3")].tolist() == ["state", "985", "1,037", "1,020", "991"]
    assert t.loc[("India", "6"), "nfhs4_total"] == "na"
    assert t.loc[("India", "22"), "nfhs5_total"] == "2.0"  # TFR


def test_state_blank(tmp_path, monkeypatch) -> None:
    """Pin Chandigarh row 68 as unresolved."""
    monkeypatch.chdir(tmp_path)
    s, t = _extract(FIXTURES / "nfhs5_state" / "nfhs5_chandigarh_p3-6.pdf", "nfhs5/state.toml")
    assert (s["cells"]["verified"], s["cells"]["unresolved"]) == (521, 3)
    assert t.loc[("Chandigarh", "68")].tolist() == ["state", "", "*", "", ""]
    assert t.loc[("Chandigarh", "67")].tolist() == ["state", "(92.8)", "*", "(92.9)", "(93.1)"]


def test_example_district_recipe(tmp_path, monkeypatch) -> None:
    """Pin district comparators and Mahisagar's unresolved row 32."""
    monkeypatch.chdir(tmp_path)
    s, t = _extract(FIXTURES / "nfhs5_district" / "nfhs5_kangra_p31-33.pdf", "nfhs5/district.toml")
    assert s["cells"]["verified"] == 208 and s["cells"]["failed_checks"] == 0
    assert len(t) == 104
    assert t.loc[("Kangra, Himachal Pradesh", "16")].tolist() == ["district", "1.5", "2.4"]
    s, t = _extract(
        FIXTURES / "nfhs5_district" / "nfhs5_mahisagar_p121-123.pdf", "nfhs5/district.toml"
    )
    assert s["cells"]["verified"] == 104
    assert list(t.columns) == ["level", "nfhs5_total"]
    assert t.loc[("Mahisagar, Gujarat", "11"), "nfhs5_total"] == "47.4"  # clean fuel, printed 11
    assert t.loc[("Mahisagar, Gujarat", "32"), "nfhs5_total"] == ""
    review = pd.read_csv("sheet.review.csv", dtype=str)
    assert sorted(review.value) == ["77.2", "83.1"]
