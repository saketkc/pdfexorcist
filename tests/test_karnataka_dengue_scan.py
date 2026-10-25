"""Karnataka daily dengue report, scanned: rows named by their count of values."""

import json
import os
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run
from karnataka_dengue_scan import parse

ROOT = Path(__file__).parent.parent
FIXTURE = Path(__file__).parent / "fixtures" / "karnataka_dengue" / "ka_dengue_scan_2025-12-10.pdf"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "karnataka_dengue" / "scan.toml"
DAY = ["day_suspected", "day_sampled", "day_igm", "day_ns1", "day_positive", "day_deaths"]
CUM = ["cum_suspected", "cum_sampled", "cum_igm", "cum_ns1", "cum_positive", "cum_deaths"]


def _read(*lines: list[str], title: str = "Daily Report of Dengue in Karnataka State - 2025"):
    """parse() on one page of the given lines, as {(disease, district): {col: value}}."""
    page = [[(0, title)], *[[(i, t) for i, t in enumerate(ln)] for ln in lines]]
    out: dict = {}
    for r in parse([(1, page)]):
        out.setdefault((r["disease"], r["district"]), {})[r["col"]] = r["value"]
    return out


def test_values_named_by_count() -> None:
    """17 values: area, day and cumulative; 11: the day cells were blank."""
    # GLM-OCR's lines from the fixture; it gives each blank cell as ""
    t = _read(
        ["1", "Bangaluru (U)", "4", "4", "30", "97", "92662", "6", "6", "1", "0", "1", "0",
         "1161", "922", "137", "40", "177", "0"],
        ["4", "Kolar", "5", "3", "4", "4", "1502", "", "", "", "", "", "",
         "6203", "3548", "97", "70", "167", "0"],
    )  # fmt: skip
    u = t[("Dengue", "Bangaluru (U)")]
    assert [u[c] for c in DAY] == ["6", "6", "1", "0", "1", "0"]
    assert u["population"] == "92662" and u["cum_positive"] == "177"
    k = t[("Dengue", "Kolar")]
    assert not set(DAY) & set(k)
    assert [k[c] for c in CUM] == ["6203", "3548", "97", "70", "167", "0"]


def test_bbmp_has_no_block_count() -> None:
    t = _read(
        ["Bangaluru City(BBMP)", "0", "0", "0", "0", "532", "324", "5", "3", "8", "0",
         "17725", "13046", "1502", "1926", "3428", "0"],
    )  # fmt: skip
    b = t[("Dengue", "Bangaluru City (BBMP)")]
    assert "blocks" not in b and b["taluks"] == "0"
    assert [b[c] for c in DAY] == ["532", "324", "5", "3", "8", "0"]


def test_unclear_rows_are_left_out() -> None:
    """A dropped zero or a garbled token would shift the values; such rows give nothing."""
    t = _read(
        ["Udupi", "20", "35", "59401", "6062", "4132", "107", "46", "153"],  # Apple Vision
        ["|", "2", "|[Bangaluru(R)", "|", "4", "|", "3{", "19| 40|", "23590] 29] as]"],
        ["31", "Kodagu", "3", "1", "1", "1", "125", "6159", "1912", "1", "19", "20", "0l"],
    )
    assert t == {}


def test_margin_note_and_foreign_digits() -> None:
    """A note printed sideways in the margin, read onto the end of the first row, is not a
    value; a Thai seven (which \\d takes) is not a number."""
    t = _read(
        # OXR on DR-11-08-2025 (an upright Adobe Scan, July-November 2025 layout)
        ["1", "Bangaluru (U)", "4", "4", "27", "58", "9155", "", "", "", "", "", "",
         "652", "463", "65", "14", "79", "0", "On the reported cases are as per the reports"],
        ["10", "Belagavi", "10", "1", "4", "4", "284", "10", "3", "0", "0", "0", "0",
         "415", "123", "11", "0", "11", "\u0e57"],
    )  # fmt: skip
    u = t[("Dengue", "Bangaluru (U)")]
    assert [u[c] for c in CUM] == ["652", "463", "65", "14", "79", "0"]
    assert ("Dengue", "Belagavi") not in t  # 16 values once the seven is dropped


def test_misread_names_snap_to_the_printed_ones() -> None:
    t = _read(
        ["5", "Chikkaba lapura", "6", "5", "20", "27", "4012", "8452", "3079", "20", "37", "57",
         "0"],
        ["31", "|Kodagu", "3", "1", "1", "1", "125", "6159", "1912", "1", "19", "20", "0"],
        ["9", "Not a district", "7", "5", "50", "69", "82789", "3490", "3488", "86", "61", "147",
         "0"],
    )  # fmt: skip
    assert set(t) == {("Dengue", "Chikkaballapura"), ("Dengue", "Kodagu")}


def test_chikungunya_others_and_report_date() -> None:
    t = _read(
        ["No.: NVBDCP/HS/2 (1)/2025", "Date:", "10", "-", "12", "-", "2025"],
        ["Total Chikungunya affected", "Cumalative (from 01-01-2025)"],
        ["3", "Ramanagar", "4", "2", "6", "7", "485", "32", "15", "3", "0", "3", "0",
         "493", "245", "30", "0", "30", "0"],
        title="Daily Report of Chikungunya in Karnataka State - 2025",
    )  # fmt: skip
    r = t[("Chikungunya", "Ramanagar")]
    assert r["day_others"] == "0" and r["cum_igm"] == "30" and "cum_ns1" not in r
    assert t[("", "")] == {"report_date": "2025-12-10", "cum_year": "2025"}


@pytest.mark.skipif(
    not os.environ.get("PDFEXORCIST_OCR_TESTS"), reason="slow OCR test; set PDFEXORCIST_OCR_TESTS=1"
)
@pytest.mark.usefixtures("wide_console")
def test_scan_end_to_end(tmp_path: Path) -> None:
    """Pin the agreed share and rows checked by hand against the page image."""
    pdf = tmp_path / FIXTURE.name
    shutil.copy(FIXTURE, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    s = json.loads(r.stdout)
    assert s["cells"]["verified"] / s["cells"]["total"] > 0.95
    t = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    t = t.set_index(["disease", "district"])
    total = t.loc[("Dengue", "Total")]
    assert total[[*DAY, *CUM]].tolist() == [
        "415", "255", "2", "5", "7", "0", "191962", "89794", "2169", "1382", "3551", "0"
    ]  # fmt: skip
    assert t.loc[("Dengue", "Mandya"), DAY].tolist() == ["81", "44", "0", "3", "3", "0"]
    assert t.loc[("", ""), ["report_date", "cum_year"]].tolist() == ["2025-12-10", "2025"]
