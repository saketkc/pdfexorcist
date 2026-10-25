"""NCVBDC malaria annual report: district rows of every column layout, 2010-2024."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "ncvbdc_malaria_district"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "ncvbdc_malaria_district" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[dict, pd.DataFrame]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    summary = json.loads(r.stdout)
    # exit code 1: a check failed (lossy "#DIV/0!" cells, a printed total)
    assert r.exit_code == (1 if summary["cells"]["failed_checks"] else 0), r.stdout
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return summary, table.set_index(["block", "row"])


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    tmp = tmp_path_factory.mktemp("ncvbdc_malaria")
    return {
        m["fixture"][len("ncvbdc_malaria_") : -4]: _extract(tmp, m["fixture"]) for m in MANIFEST
    }


def test_blocks_and_checks(results) -> None:
    """One block per State (and India); totals add up, except where the source does not."""
    blocks = {k: sorted(set(t.index.get_level_values("block"))) for k, (_, t) in results.items()}
    assert blocks["2010_p1-2"] == ["andamanandnicobarislands", "andhrapradesh",
                                   "arunachalpradesh", "assam"]  # fmt: skip
    assert blocks["2018_p1_45"] == ["andhrapadesh", "india"]
    assert blocks["2021_p3_7"] == ["assam", "chhattisgarh"]
    assert blocks["2024_p1"] == ["andhrapradesh", "arunachalpradesh"]
    for key, (s, _) in results.items():
        failed = {k: v for k, v in s["checks"].items() if k != "lossy value"}
        if key == "2022_p1_49":  # the printed India smears collected: 2 more than the States
            assert failed == {"districts = State total": 36}
        else:
            assert failed == {}, key
        if key != "2021_p3_7":  # there one engine splits Chhattisgarh's block: no quorum
            assert s["cells"]["unresolved"] <= 1, key


@pytest.mark.parametrize(
    ("key", "block", "row", "cols", "want"),
    [
        ("2010_p1-2", "andamanandnicobarislands", "nicobars", ["bse", "positive", "api"],
         ["42339", "1460", "33.95"]),
        ("2010_p1-2", "arunachalpradesh", "Total", ["positive", "deaths"], ["17944", "103"]),
        ("2017_p6", "chhattisgarh", "Total", ["pf_pct", "deaths_pf"], ["81.37", "79"]),
        ("2018_p1_45", "andhrapadesh", "1", ["district", "pf_pct", "sfr"],
         ["Srikakulam", "81.44", "0.05"]),
        ("2018_p1_45", "india", "Total", ["pf_pct", "deaths_pf"], ["48.19", "88"]),
        ("2019_p2", "arunachalpradesh", "17", ["district", "positive"],
         ["Tirap (Longding district)", "10"]),
        ("2020_p1", "andhrapradesh", "1", ["tested", "positive"], ["391604", "34"]),
        ("2021_p3_7", "chhattisgarh", "2", ["district", "positive", "rt", "deaths_pf"],
         ["Bijapur", "6843", "6843", "6"]),
        ("2021_p3_7", "chhattisgarh", "6", ["rt", "deaths_pf"], ["2324", "3"]),
        ("2021_p3_7", "assam", "5", ["district", "mixed", "positive"], ["Chirang", "0", "20"]),
        ("2022_p1_49", "india", "Total", ["positive", "deaths_pf"], ["176522", "78"]),
        ("2023_p1", "andhrapradesh", "1", ["positive", "pf_pct"], ["3675", "88.8"]),
        ("2024_p1", "andhrapradesh", "7", ["district", "tested"], ["Dr. B.R. Ambedkar", "270575"]),
        ("2024_p1", "andhrapradesh", "1", ["positive", "deaths_pf"], ["3693", "1"]),
    ],
)  # fmt: skip
def test_pinned_rows(results, key: str, block: str, row: str, cols: list, want: list) -> None:
    assert results[key][1].loc[(block, row), cols].tolist() == want
