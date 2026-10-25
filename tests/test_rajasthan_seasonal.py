"""Rajasthan seasonal disease status: cumulative positives and deaths by district."""

import csv
import json
import os
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run
from rajasthan_seasonal import _diseases, parse

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "rajasthan_seasonal"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "rajasthan_seasonal" / "recipe.toml"
SCAN_RECIPE = RECIPE.with_name("scan.toml")
# https://rajswasthya.rajasthan.gov.in/admin/upload/mausami/Dengue%20Status.pdf as captured
# on 25 October 2026 (Readiris scan, no text layer); the site overwrites it in place
SCAN = FIXTURES / "rj_dengue_scan_2026-10-22.pdf"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
COLS = ["positive", "deaths"]

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
    tmp = tmp_path_factory.mktemp("rj_seasonal")
    return {m["fixture"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def test_every_cell_agreed_and_balances(results) -> None:
    """42 districts and Total per disease: every cell agreed and every check passed."""
    totals = {}
    for fixture, (s, t) in results.items():
        c = s["cells"]
        assert c["verified"] == c["total"] and c["failed_checks"] == 0, fixture
        assert len(s["checks_run"]) == 2, fixture
        for disease in set(t.index.get_level_values("disease")):
            names = set(t.loc[disease].index)
            assert len(names) == 43 and {"Total", "Jaipur", "Jaipur 2"} <= names, fixture
        totals[fixture] = c["total"]
    assert totals == {
        "rj_scrub_typhus_2025-05-23.pdf": 85,  # one blank cell
        "rj_h1n1_2025-05-16.pdf": 86,
        "rj_leptospirosis_2025-05-08.pdf": 172,
    }


def test_diseases_side_by_side(results) -> None:
    """Leptospirosis and brucellosis share a row; each count goes to its own disease."""
    t = results["rj_leptospirosis_2025-05-08.pdf"][1]
    assert set(t.index.get_level_values("disease")) == {"Leptospirosis", "Brucellosis"}
    assert t.loc[("Leptospirosis", "Bikaner"), COLS].tolist() == ["11", "0"]
    assert t.loc[("Brucellosis", "Bikaner"), COLS].tolist() == ["47", "0"]
    assert t.loc[("Brucellosis", "Total"), COLS].tolist() == ["220", "0"]
    assert t.loc[("Leptospirosis", "Kotputli-Bharoad"), "positive"] == "6"


def test_blank_cell_and_digit_in_name(results) -> None:
    """Jaipur 2's blank positives stay blank; its 2 is not read as a count."""
    t = results["rj_scrub_typhus_2025-05-23.pdf"][1]
    assert t.loc[("Scrub Typhus", "Jaipur 2"), COLS].tolist() == ["", "0"]
    assert t.loc[("Scrub Typhus", "Kota"), COLS].tolist() == ["35", "0"]
    assert t.loc[("Scrub Typhus", "DIDWANA-KUCHAMAN"), "positive"] == "1"
    assert t.loc[("Scrub Typhus", "Total"), "positive"] == "197"
    t = results["rj_h1n1_2025-05-16.pdf"][1]
    assert t.loc[("H1N1", "Jaipur 2"), COLS].tolist() == ["0", "0"]
    assert t.loc[("H1N1", "Jaipur"), COLS].tolist() == ["5", "0"]
    assert t.loc[("H1N1", "Total"), COLS].tolist() == ["8", "0"]


def test_disease_names() -> None:
    """Names in printed order, from a title or the column heading."""
    assert _diseases("Comparative Status of Influenza A(H1N1)") == ["H1N1"]
    assert _diseases("Leptospirosis   Brucellosis") == ["Leptospirosis", "Brucellosis"]
    assert _diseases("Dengue Malaria Chikungunya") == ["Dengue", "Malaria", "Chikungunya"]
    assert _diseases("District Name") == []


def test_scan_lines_three_diseases() -> None:
    """Lines as OCR reads the dengue status scan; x is the token's column (Total has no S.No)."""
    lines = [
        ["Seasonal Disease Status 2026", "Up to", "22 Oct 2026"],
        ["Dengue", "Malaria", "Chikungunya"],
        ["S.No", "District", "Positive", "Death", "Positive", "Death", "Positive", "Death"],
        ["1", "Ajmer", "111", "0", "14", "0", "0", "0"],
        ["21", "Jaipur 2", "91", "0", "1", "0", "8", "0"],
        ["", "Total", "1805", "0", "934", "0", "183", "0"],
    ]
    page = [[(float(i), t) for i, t in enumerate(ln)] for ln in lines]
    got = {(r["disease"], r["district"], r["col"]): r["value"] for r in parse([(1, page)])}
    assert got[("Dengue", "Ajmer", "positive")] == "111"
    assert got[("Malaria", "Ajmer", "positive")] == "14"
    assert got[("Chikungunya", "Jaipur 2", "positive")] == "8"
    assert got[("Malaria", "Total", "positive")] == "934"
    assert len(got) == 18


@pytest.mark.skipif(
    not os.environ.get("PDFEXORCIST_OCR_TESTS"), reason="slow OCR test; set PDFEXORCIST_OCR_TESTS=1"
)
def test_scan_end_to_end(tmp_path: Path) -> None:
    """Every district count agreed; the rows add up to the printed Total (checked by eye)."""
    pdf = tmp_path / SCAN.name
    shutil.copy(SCAN, pdf)
    r = run(["extract", str(pdf), "--recipe", str(SCAN_RECIPE), "--json", "-q"])
    s = json.loads(r.stdout)
    assert s["cells"]["failed_checks"] == 0
    t = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    t = t.set_index(["disease", "district"])
    for disease, total in (("Dengue", "1805"), ("Malaria", "934"), ("Chikungunya", "183")):
        assert len(t.loc[disease]) == 43
        assert t.loc[(disease, "Total"), COLS].tolist() == [total, "0"]
    assert t.loc[("Malaria", "Pratapgarh"), "positive"] == "118"
    assert t.loc[("Dengue", "Jaipur 2"), "positive"] == "91"
