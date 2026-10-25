"""NHP State/UT tables by year: dengue and H1N1 (NHP 2021), and AES continued on a second
page with its provisional year printed above the others (NHP 2022)."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "nhp_multi_year"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "nhp_multi_year" / "recipe.toml"

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, name: str) -> tuple[dict, pd.DataFrame]:
    pdf = tmp / name
    shutil.copy(FIXTURES / name, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    assert r.exit_code == 0, r.stdout
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return json.loads(r.stdout), table.set_index(["disease", "state"])


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict:
    tmp = tmp_path_factory.mktemp("nhp_multi_year")
    return {n: _extract(tmp, f"{n}.pdf") for n in ("nhp_2021_p188_231", "nhp_2022_p180-181")}


def test_checks_pass(results) -> None:
    for summary, _ in results.values():
        assert summary["cells"]["unresolved"] == 0
        assert summary["checks"] == {}


def test_values(results) -> None:
    t21 = results["nhp_2021_p188_231"][1]
    assert t21.loc[("Dengue", "Kerala"), "2017 Cases"] == "19994"
    assert t21.loc[("Dengue", "India"), "2016 Cases"] == "129166"
    assert t21.loc[("Influenza A H1N1", "Chandigarh"), "2020 (Prov.) Cases"] == "17"  # "17@@"
    t22 = results["nhp_2022_p180-181"][1]
    aes = t22.loc["Acute Encephalitis Syndrome"]
    assert len(aes) == 38  # rows on both pages
    assert aes.loc["Assam", "2021 (Prov.) Cases"] == "488"
    assert aes.loc["India", "2021 (Prov.) Deaths"] == "216"
