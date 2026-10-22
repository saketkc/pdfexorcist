"""IDSP weekly outbreak report."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "idsp_outbreaks"
FIXTURE = FIXTURES / "idsp_outbreaks_2026_week09_p3-4_11_27-28_31_35-36.pdf"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "idsp_outbreaks" / "recipe.toml"

pytestmark = pytest.mark.usefixtures("wide_console")


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> tuple[int, dict, pd.DataFrame]:
    """(exit code, JSON summary, the CSV table) of the recipe on a copy of the fixture."""
    tmp = tmp_path_factory.mktemp("outbreaks")
    pdf = tmp / "ob.pdf"
    shutil.copy(FIXTURE, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    table = pd.read_csv(tmp / "ob.csv", dtype=str, keep_default_na=False)
    return r.exit_code, json.loads(r.stdout), table.set_index("id")


def test_every_outbreak_agreed(result) -> None:
    """Pin the 17 outbreaks on the fixture's pages, 5 of them reported late."""
    code, s, t = result
    assert code == 0 and s["cells"]["failed_checks"] == 0 and len(s["checks_run"]) == 1
    assert s["cells"]["verified"] == s["cells"]["total"] == 131
    assert t.table.value_counts().to_dict() == {"week": 12, "late": 5}
    assert set(t.status) == {"Under Control", "Under Surveillance"}


def test_names_as_printed(result) -> None:
    """Pin names joined from wrapped lines and from words broken without a hyphen."""
    t = result[2]
    assert t.loc["AP/ANA/2026/9/304", ["district", "disease"]].tolist() == [
        "Ananthapuramu", "Acute Diarrhoeal Disease"
    ]  # fmt: skip
    assert t.loc["WB/PAR/2026/9/355", ["district", "disease"]].tolist() == [
        "24 Paraganas South", "Suspected Food Poisoning"
    ]  # fmt: skip
    assert t.loc["MH/CHH/2026/9/368", ["state", "district"]].tolist() == [
        "Maharashtra", "Chhatrapati Sambhajinagar"
    ]  # fmt: skip
    assert "Acute Gastroenteritis" in set(t.disease)
    assert t.loc["RJ/BHI/2026/9/370", "disease"] == "Hepatitis A & E"


def test_values(result) -> None:
    """Pin numbers and dates joined across lines; a late outbreak has no reporting date."""
    t = result[2]
    row = t.loc["AP/ANA/2026/9/303"]
    assert row[["cases", "deaths", "start", "reported"]].tolist() == [
        "14", "0", "24-02-2026", "28-02-2026"
    ]  # fmt: skip
    late = t.loc["MG/EAS/2026/9/369"]
    assert late[["cases", "deaths", "start", "reported"]].tolist() == ["2", "2", "24-01-2026", ""]


def _table(pdf: Path, tmp: Path) -> pd.DataFrame:
    """The voted table, after checking every cell resolved."""
    shutil.copy(pdf, tmp / pdf.name)
    r = run(["extract", str(tmp / pdf.name), "--recipe", str(RECIPE), "--json", "-q"])
    assert r.exit_code == 0 and json.loads(r.stdout)["cells"]["unresolved"] == 0
    return pd.read_csv(tmp / f"{pdf.stem}.csv", dtype=str, keep_default_na=False)


def test_merged_state_cells(tmp_path: Path) -> None:
    """Pin a pre-2017 report: no unique IDs, one State cell merged over each state's rows.

    Karnataka's cell breaks across pages 3 and 4 and prints the name on page 4 only; its
    rows on page 3 still get it, through the state number (7.) they share.
    """
    t = _table(FIXTURES / "idsp_outbreaks_2013_week20_p2-5.pdf", tmp_path)
    assert len(t) == 22 and list(t.numeral[:3]) == ["i.", "ii.", "iii."]
    karnataka = t[t.serial == "7."]
    assert set(karnataka.state) == {"Karnataka"} and set(karnataka.page) == {"3", "4"}
    row = t.set_index("numeral").loc["i."]
    assert row[["state", "district", "disease", "cases", "deaths", "start"]].tolist() == [
        "Andhra Pradesh", "Mahabubnagar", "Food Poisoning", "124", "0", "13/05/13"
    ]  # fmt: skip


def test_line_end_hyphen(tmp_path: Path) -> None:
    """Pin a 2011 cell whose disease breaks after a hyphen ("Crimean-" / "Congo").

    PDFium reads that hyphen as U+FFFE; the engine maps it back, so all three agree.
    """
    t = _table(FIXTURES / "idsp_outbreaks_2011_week20_p2.pdf", tmp_path)
    row = t.set_index("numeral").loc["iii."]
    assert row[["state", "district", "disease", "cases", "deaths"]].tolist() == [
        "Gujarat", "Mehsana", "Crimean-Congo Hemorrhagicfever (CCHF)", "1", "1"
    ]  # fmt: skip


def test_wrapped_ids(tmp_path: Path) -> None:
    """Pin 2025 rows whose Unique ID wraps in its narrow cell ("AS/DAR/2025/23/9" "59")."""
    t = _table(FIXTURES / "idsp_outbreaks_2025_week23_p3-4.pdf", tmp_path)
    assert list(t.id) == [f"{p}/2025/23/{n}" for p, n in [
        ("AS/DAR", 959), ("AS/DAR", 960), ("AS/GOA", 961), ("AS/JOR", 962), ("AS/NAG", 963)
    ]]  # fmt: skip


def test_late_and_follow_up_tables(tmp_path: Path) -> None:
    """Pin 2015 week 38: the late table opens under a banner inside its ruled box, and the
    follow-up table (updates on outbreaks already counted, numbered from i. again) is left
    out. PDFium reads its heading as "FOLLOW UP OFDISEASE OUTBREAKS".
    """
    t = _table(FIXTURES / "idsp_outbreaks_2015_week38_p7-10.pdf", tmp_path)
    assert t.table.value_counts().to_dict() == {"late": 16, "week": 2}
    assert t.numeral.iloc[-1] == "lii." and "All districts" not in set(t.district)


def test_shaded_merged_cells(tmp_path: Path) -> None:
    """Pin 2012 week 27: a shaded band every line inside each merged State cell.

    The shading is drawn as filled rectangles, which pdfplumber's default finder takes for
    cell edges; grid.tables keeps only rules, so Haryana's cell spans all three of its
    rows. The numerals there have no dot ("vii Acute Diarrhoeal Disease").
    """
    t = _table(FIXTURES / "idsp_outbreaks_2012_week27_p2-3.pdf", tmp_path)
    haryana = t[t.district.isin(["Kurukshetra", "Kaithal"])]
    assert set(haryana.state) == {"Haryana"} and list(haryana.numeral) == ["vii", "viii", "ix"]
    assert haryana.disease.iloc[0] == "Acute Diarrhoeal Disease"


def test_rules_drawn_as_paths(tmp_path: Path) -> None:
    """Pin 2011 week 31: the Disease column's rules are paths, not rectangles.

    Without them the table splits in two at that column and neither half has a header.
    """
    t = _table(FIXTURES / "idsp_outbreaks_2011_week31_p2.pdf", tmp_path)
    assert len(t) == 6
    first = t.iloc[0][["state", "district", "disease", "cases", "deaths"]].tolist()
    assert first == ["Andhra Pradesh", "Warangal", "Acute Diarrhoeal Disease", "20", "0"]


def test_serial_and_unique_id_columns(tmp_path: Path) -> None:
    """Pin 2025 week 22: both an S.No. and a Unique ID column. The ID is the row's key."""
    t = _table(FIXTURES / "idsp_outbreaks_2025_week22_p3.pdf", tmp_path)
    assert len(t)
    assert t.id.str.fullmatch(r"[A-Z]{2,3}/[A-Z]{2,5}/2025/22/\d+").all()
    assert "serial" not in t or t.serial.eq("").all()
