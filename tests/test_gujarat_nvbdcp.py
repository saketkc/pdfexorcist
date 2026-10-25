"""Gujarat NVBDCP monthly report: district malaria indicators (decks) and highlights."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

FIXTURES = Path(__file__).parent / "fixtures" / "gujarat_nvbdcp"
RECIPES = Path(__file__).parent.parent / "pdfexorcist" / "recipes" / "gujarat_nvbdcp"

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str, recipe: str, index: list[str]) -> tuple[dict, pd.DataFrame]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPES / recipe), "--json", "-q"])
    assert r.exit_code == 0, r.stdout
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return json.loads(r.stdout), table.set_index(index)


@pytest.fixture(scope="module")
def decks(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    tmp = tmp_path_factory.mktemp("gujarat_decks")
    names = ["gujarat_nvbdcp_2018-12_p9.pdf", "gujarat_nvbdcp_2019-06_p9.pdf"]
    return {n: _extract(tmp, n, "recipe.toml", ["page", "measure"]) for n in names}


@pytest.fixture(scope="module")
def highlights(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    tmp = tmp_path_factory.mktemp("gujarat_highlights")
    names = [
        "gujarat_nvbdcp_2026-03.pdf",
        "gujarat_nvbdcp_2020-02.pdf",
        "gujarat_nvbdcp_2025-04.pdf",
    ]
    return {n: _extract(tmp, n, "highlights.toml", ["disease", "area"]) for n in names}


def test_decks_every_cell_agreed(decks) -> None:
    """Four indicators, a value per month from January of the year before."""
    widths = {}
    for fixture, (s, t) in decks.items():
        c = s["cells"]
        assert c["verified"] == c["total"] and c["failed_checks"] == 0, fixture
        assert sorted(t.index.get_level_values("measure")) == ["MBER", "MPI", "SFR", "SPR"]
        widths[fixture] = len(t.columns)
    assert widths == {"gujarat_nvbdcp_2018-12_p9.pdf": 24, "gujarat_nvbdcp_2019-06_p9.pdf": 17}


def test_decks_pinned(decks) -> None:
    t = decks["gujarat_nvbdcp_2018-12_p9.pdf"][1]
    assert t.loc[("1", "SPR"), ["c01", "c09", "c20", "c24"]].tolist() == [
        "0",
        "0.13",
        "0.11",
        "0.01",
    ]
    assert t.loc[("1", "MBER"), ["c01", "c24"]].tolist() == ["2.00", "2.03"]
    t = decks["gujarat_nvbdcp_2019-06_p9.pdf"][1]
    assert t.loc[("1", "MBER"), ["c13", "c17"]].tolist() == ["1.94", "2.12"]


def test_highlights_every_cell_agreed(highlights) -> None:
    for fixture, (s, _) in highlights.items():
        c = s["cells"]
        assert c["verified"] == c["total"] and c["unresolved"] == 0, fixture


def test_highlights_pinned(highlights) -> None:
    """State rates and changes, and shares from the table or the sentence."""
    t = highlights["gujarat_nvbdcp_2026-03.pdf"][1]
    assert t.loc[("Malaria", "Gujarat"), ["MBER", "change"]].tolist() == ["1.9", "-31.1"]
    assert t.loc[("Malaria", "SMC"), "share"] == "34"
    assert t.loc[("Dengue", "Mehsana MC"), "share"] == "4"
    assert t.loc[("Malaria", "Gir Veraval"), "share"] == "4"
    assert t.loc[("Chikungunya", "Bhavnagar"), "share"] == "14"
    t = highlights["gujarat_nvbdcp_2020-02.pdf"][1]
    assert t.loc[("Malaria", "Gujarat"), ["ABER", "change"]].tolist() == ["1.7", "-30.41"]
    assert t.loc[("Chikungunya", "Gujarat"), "change"] == "-19.6"
    assert t.loc[("Dengue", "Ahmedabad Municipal Corporation"), "share"] == "22.0"
    assert t.loc[("Chikungunya", "Vadodara district"), "share"] == "10.4"
    t = highlights["gujarat_nvbdcp_2025-04.pdf"][1]
    for place in ["Jamnagar", "Kutchh", "Surendranagr"]:
        assert t.loc[("Malaria", place), "share"] == "4"
    assert t.loc[("Chikungunya", "RMC"), "share"] == "11"
