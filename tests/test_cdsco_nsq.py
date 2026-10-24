"""CDSCO alerts of drugs Not of Standard Quality: one row per batch, keyed by serial number."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "cdsco_nsq"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "cdsco_nsq" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
COLS = ["product", "batch", "mfg_date", "expiry_date", "manufacturer", "result", "lab"]

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[dict, pd.DataFrame]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    assert r.exit_code == 0, r.stdout
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return json.loads(r.stdout), table.set_index("sno")


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    tmp = tmp_path_factory.mktemp("cdsco")
    return {m["fixture"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def test_every_cell_agreed(results) -> None:
    """Pin each fixture's records and cells; every cell agreed and the checks pass."""
    got = {}
    for fixture, (s, t) in results.items():
        c = s["cells"]
        assert c["verified"] == c["total"] and c["failed_checks"] == 0, fixture
        assert len(s["checks_run"]) == 2
        assert list(t.columns) == ["page", *COLS], fixture
        got[fixture] = (t.index[0], t.index[-1], len(t), c["total"])
    assert got == {
        "cdsco_nsq_state_2025-05_p1-3.pdf": ("1", "21", 21, 147),
        "cdsco_nsq_state_2025-05_p16-18.pdf": ("102", "128", 27, 189),
        "cdsco_nsq_central_2025-06_p1-2.pdf": ("1", "18", 18, 126),
    }


def test_wrapped_cells(results) -> None:
    """Pin a record whose cells wrap over many lines, joined with single spaces."""
    t = results["cdsco_nsq_state_2025-05_p1-3.pdf"][1]
    assert t.loc["3", COLS].tolist() == [
        "Betamethasone Valerate Ointment IP 0.1% w/w",
        "B73",
        "Aug-24",
        "Jul-26",
        "M/s.Syndicate Pharma, 185/B, 185/B-1, 187/A & 188 Sector - F, Sanwer Road, Indore-452015.",
        "Sample does not conform to IP specification for Betamethasone Valerate Ointment "
        "with respect to the content of Betamethasone in Betamethasone Valerate",
        "Drugs Testing Laboratory, Chennai-06",
    ]


def test_rows_across_page_breaks(results) -> None:
    """Pin rows Word split at a page break: the part on the next page joins its record."""
    t = results["cdsco_nsq_state_2025-05_p1-3.pdf"][1]
    assert t.loc["6", "page"] == "1"
    assert t.loc["6", "manufacturer"] == (
        "M/s.Candour Pharmaceuticals, Vill. OGLI, Suketi Road, Kala Amb, "
        "Distt. Sirmour (H.P), 173030"
    )
    assert t.loc["6", "result"].endswith("Atorvastatin Tablets with respect to Dissolution")
    assert t.loc["14", "product"] == (
        "Entcof Syrup (Ambroxol Hydrochloride, Guaiphenesin, Terbutaline Sulphate Syrup)"
    )
    assert t.loc["15", "batch"] == "NF24007"  # the first row with a serial on page 3
    t = results["cdsco_nsq_state_2025-05_p16-18.pdf"][1]
    assert t.loc["112", "product"] == (
        "Aceclofenac Paracetamol & Serratiopeptidase Tablets. (Aceclofen-SP)"
    )
    assert t.loc["112", "manufacturer"].endswith("The. Nurpur., Kangra-176201 (HP)")


def test_batches_and_dates(results) -> None:
    """Pin wrapped batch numbers and dates, and words that keep their space."""
    t = results["cdsco_nsq_state_2025-05_p16-18.pdf"][1]
    assert t.loc[["102", "103", "104"], "batch"].tolist() == ["TST2301"] * 3
    assert t.loc["102", ["mfg_date", "expiry_date"]].tolist() == ["Not Mentioned", "Apr-27"]
    assert t.loc["128", "batch"] == "MOXG-2404001"
    t = results["cdsco_nsq_central_2025-06_p1-2.pdf"][1]
    assert t.loc["15", ["batch", "mfg_date", "expiry_date"]].tolist() == [
        "20240901", "12-09-2024", "11-09-2026"
    ]  # fmt: skip
    assert t.loc["17", "batch"] == "DXT202412040"
    assert t.loc["1", ["mfg_date", "expiry_date", "lab"]].tolist() == [
        "01/2025", "12/2027", "CDL, Kolkata"
    ]  # fmt: skip
