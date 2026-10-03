"""NFHS-6 example recipes."""

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
    """Pin Chandigarh rows, columns, placeholders, and rules."""
    monkeypatch.chdir(tmp_path)
    s, t = _extract(FIXTURES / "nfhs6_state" / "nfhs6_chandigarh_p145-147.pdf", "nfhs6/state.toml")
    assert s["cells"]["verified"] == 404 and s["cells"]["failed_checks"] == 0
    assert len(s["checks_run"]) == 2
    assert len(t) == 101
    assert list(t.columns) == ["level", "nfhs6_urban", "nfhs6_rural", "nfhs6_total", "nfhs5_total"]
    assert t.loc[("Chandigarh", "6")].tolist() == ["state", "96.4", "(97.7)", "96.5", "96.8"]
    assert t.loc[("Chandigarh", "17")].tolist() == ["state", "*", "*", "*", "*"]
    assert t.loc[("Chandigarh", "18"), "nfhs6_total"] == "1.8"  # TFR


def test_example_district_recipe(tmp_path, monkeypatch) -> None:
    """Pin district comparator availability."""
    monkeypatch.chdir(tmp_path)
    s, t = _extract(
        FIXTURES / "nfhs6_district" / "nfhs6_anantapur_p15-17.pdf", "nfhs6/district.toml"
    )
    assert s["cells"]["verified"] == 186 and s["cells"]["failed_checks"] == 0
    assert len(t) == 93
    assert t.loc[("Anantapur, Andhra Pradesh", "17")].tolist() == ["district", "(13.0)", "*"]
    s, t = _extract(
        FIXTURES / "nfhs6_district" / "nfhs6_jhargram_p51-53.pdf", "nfhs6/district.toml"
    )
    assert s["cells"]["verified"] == 93
    assert list(t.columns) == ["level", "nfhs6_total"]
    assert t.loc[("Jhargram, West Bengal", "41"), "nfhs6_total"] == "85.3"
