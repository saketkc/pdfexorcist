"""TB India district notification: the 2018 report's Annexure 1b (States wrapped around rows)."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "tb_india_district" / "tb_india_district_sample.pdf"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "tb_india_district" / "recipe.toml"

pytestmark = pytest.mark.usefixtures("wide_console")


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict, pd.DataFrame]:
    pdf = tmp_path_factory.mktemp("tb_india") / FIXTURE.name
    shutil.copy(FIXTURE, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    assert r.exit_code == 0, r.stdout
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return json.loads(r.stdout), table.set_index(["state", "district"])


def test_all_cells_agree(result) -> None:
    summary, table = result
    assert summary["cells"]["unresolved"] == 0
    assert summary["checks"] == {}
    assert len(table) == 42


@pytest.mark.parametrize(
    ("state", "district", "col", "want"),
    [
        ("Andhra Pradesh", "Anantapur", "population", "4257381"),
        ("Andhra Pradesh", "Anantapur", "total_notified", "6270"),
        ("Andhra Pradesh", "East Godavari", "private_notified", "1036"),  # name over 2 lines
        ("Andaman and Nicobar", "North & Middle Andaman", "public_notified", "64"),
        ("Arunachal Pradesh", "Dibang Valley", "treatment_initiated_pct", "78%"),
    ],
)
def test_values(result, state: str, district: str, col: str, want: str) -> None:
    assert result[1].loc[(state, district), col] == want
