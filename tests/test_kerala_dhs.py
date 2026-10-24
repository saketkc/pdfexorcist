"""Kerala DHS communicable disease data: cases and deaths by district and disease."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "kerala_dhs"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "kerala_dhs" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
COLS = ["cases", "deaths"]
FEVER = ["op", "ip", "deaths"]

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    summary = json.loads(r.stdout)
    assert r.exit_code == (1 if summary["cells"]["failed_checks"] else 0), r.stdout
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    review = pdf.with_suffix(".review.csv")
    failed = pd.read_csv(review, dtype=str) if review.exists() else pd.DataFrame()
    return summary, table.set_index(["area", "disease"]), failed


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict:
    tmp = tmp_path_factory.mktemp("kerala")
    return {m["report_date"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def test_every_cell_agreed(results) -> None:
    """Pin each fixture's cell count; every cell is agreed and both checks run."""
    totals = {}
    for year, (s, t, _) in results.items():
        c = s["cells"]
        assert c["verified"] == c["total"], year
        assert s["checks_run"] == [
            "districts = Kerala",
            "col 'cases' >= deaths, within each area, disease",
        ]
        assert set(t["year"]) == {year}
        totals[year] = (c["total"], t.index.get_level_values("area").nunique(), c["failed_checks"])
    # 2021: 15 areas x (24 diseases x 2 + fever 3); 2022: 30 diseases; 2024: 33; 2025: 4 areas
    assert totals == {
        "2017": (41, 1, 0),
        "2021": (765, 15, 15),
        "2022": (945, 15, 0),
        "2024": (1035, 15, 2),
        "2025": (252, 4, 0),
    }


def test_districts_add_up(results) -> None:
    """The districts add up to Kerala, except where a district page misprints a value."""
    _, t, failed = results["2021"]
    assert t.loc[("Ernakulam", "Dengue Fever"), COLS].tolist() == ["955", "6"]  # its grid: 945
    assert t.loc[("Kerala", "Dengue Fever"), COLS].tolist() == ["3251", "27"]
    assert set(failed["disease"]) == {"Dengue Fever"} and set(failed["col"]) == {"cases"}
    assert set(failed["failed"]) == {"districts = Kerala"} and len(failed) == 15
    t = results["2024"][1]
    areas = t.drop("Kerala", level="area")
    for col in ["cases", "deaths"]:
        sums = areas[col].replace("", pd.NA).dropna().astype(int).groupby(level="disease").sum()
        kerala = t.loc["Kerala"][col].replace("", pd.NA).dropna().astype(int)
        assert sums.reindex(kerala.index).tolist() == kerala.tolist()


def test_missing_district_page(results) -> None:
    """2025 has no Alappuzha page: Kerala may exceed the districts printed."""
    t = results["2025"][1]
    assert set(t.index.get_level_values("area")) == {
        "Kerala", "Thiruvananthapuram", "Ernakulam", "Kasaragod"
    }  # fmt: skip
    assert t.loc[("Kerala", "Amoebic Meningo Encephalitis"), COLS].tolist() == ["201", "47"]
    # the footnote under the table ("5 Cases & 1 Death From other state") is not a row
    assert t.loc[("Thiruvananthapuram", "Amoebic Meningo Encephalitis"), COLS].tolist() == [
        "74",
        "13",
    ]
    assert len(t.loc["Thiruvananthapuram"]) == 31


def test_names_differ_between_pages(results) -> None:
    """A disease printed under another name on one page keeps the State page's name."""
    t = results["2025"][1]
    assert t.loc[("Kasaragod", "AES"), COLS].tolist() == ["2", "2"]  # "Acute Encephalitis Syndrome"
    assert t.loc[("Kerala", "AES"), COLS].tolist() == ["168", "18"]
    t = results["2022"][1]
    assert t.loc[("Kerala", "Chicken Pox"), COLS].tolist() == ["9927", "14"]  # "C.pox"
    assert t.loc[("Kerala", "Prob: Hepatitis - A"), COLS].tolist() == [
        "894",
        "1",
    ]  # "Prob:Hepatitis - A"


def test_wrapped_name(results) -> None:
    """A name printed above and below its numbers is joined (2017, the State page only)."""
    t = results["2017"][1]
    hfmd = t.loc[("Kerala", "Hand Foot and Mouth Disease (HFMD)")]
    assert hfmd[["sl", *COLS]].tolist() == ["16", "408", "0"]
    assert t.loc[("Kerala", "Lyme Disease"), ["sl", *COLS]].tolist() == ["17", "0", "0"]
    assert t.loc[("Kerala", "Fever"), FEVER].tolist() == ["3417968", "109974", "76"]


def test_fever_rows(results) -> None:
    """Fever prints OP and IP cases on two lines with one death count between them."""
    assert results["2025"][1].loc[("Kerala", "Fever"), FEVER].tolist() == ["2665004", "37387", "2"]
    assert results["2021"][1].loc[("Kerala", "Fever"), FEVER].tolist() == ["1463517", "12458", "0"]
    t = results["2024"][1]
    assert t.loc[("Kerala", "Fever"), FEVER].tolist() == ["2879108", "43294", "8"]
    assert t.loc[("Kannur", "Fever"), [*FEVER, "sl"]].tolist() == ["175101", "2843", "0", ""]


def test_margin_note_and_misnumbered_rows(results) -> None:
    """The sideways approval note is dropped; rows are keyed by name, not Sl.No."""
    t = results["2022"][1]
    assert t.loc[("Kerala", "Dengue Fever"), COLS].tolist() == ["4468", "58"]
    assert t.loc[("Kerala", "Malaria"), COLS].tolist() == ["439", "0"]  # printed 439*
    mlp = t.loc["Malappuram"]
    assert mlp.loc["Probable Rabies", ["sl", *COLS]].tolist() == ["26", "1", "1"]
    assert mlp.loc["Zika", ["sl", *COLS]].tolist() == ["26", "0", "0"]
    assert mlp.loc["Monkey Pox", ["sl", *COLS]].tolist() == ["28", "4", "0"]
    assert mlp.loc["Fever", FEVER].tolist() == ["436684", "1835", "1"]


def test_cases_below_deaths(results) -> None:
    """Wayanad 2024 prints 0 JE cases and 1 death; the check names both cells."""
    failed = results["2024"][2]
    assert set(
        zip(failed["area"], failed["disease"], failed["col"], failed["value"], strict=True)
    ) == {
        ("Wayanad", "Japanese Encephalitis (JE)", "cases", "0"),
        ("Wayanad", "Japanese Encephalitis (JE)", "deaths", "1"),
    }
