"""Example recipes."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run
from imd_layout import KEY

from pdfexorcist._shipped import find_shipped

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLES = ROOT / "pdfexorcist" / "recipes"

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp_path: Path, fixture: str, recipe: str) -> tuple[int, dict, pd.DataFrame]:
    """(exit code, JSON summary, the CSV table) of one recipe run on a fixture copy."""
    pdf = tmp_path / "doc.pdf"
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(EXAMPLES / recipe), "--json", "-q"])
    return r.exit_code, json.loads(r.stdout), pd.read_csv(tmp_path / "doc.csv", dtype=str)


def test_mccd_table2(tmp_path):
    """Pin Table 2 spread parsing and state names."""
    code, s, t = _extract(tmp_path, "mccd/mccd_2019_t2_p68-69.pdf", "mccd/table2.toml")
    assert code == 0 and s["cells"]["failed_checks"] == 0 and s["notes"] == []
    t = t.set_index(["code", "sex"])
    assert t.loc[("A00-B99", "T"), "All States (Total)"] == "154576"
    assert t.loc[("ALL", "M"), "Odisha"] == "26909"
    assert t.loc[("ALL", "T"), "West Bengal"] == "77603"


def test_mccd_table5(tmp_path):
    """Pin Table 5 age headings and F/T pregnancy block."""
    code, s, t = _extract(tmp_path, "mccd/mccd_2018_t5_p104.pdf", "mccd/table5.toml")
    assert code == 0 and s["cells"]["failed_checks"] == 0 and len(s["checks_run"]) == 3
    t = t.set_index(["group", "sex"])
    assert list(t.columns) == ["<1", "1-4", "5-14", "15-24", "25-34", "35-44", "45-54",
                               "55-64", "65-69", "70+", "N.S.", "TOTAL"]  # fmt: skip
    assert t.loc[("ALL", "T"), "65-69"] == "151802"
    assert t.loc[("XV", "F"), "25-34"] == "3092"
    assert ("XV", "M") not in t.index


def test_mccd_table9_flags_the_misprint(tmp_path):
    """Pin Table 9 year headings and isolated 2018 failure."""
    code, s, t = _extract(tmp_path, "mccd/mccd_2019_t9_p194.pdf", "mccd/table9.toml")
    assert code == 1 and s["cells"]["failed_checks"] == 22 and s["cells"]["verified"] == 708
    t = t.set_index(["group", "sex"])
    assert t.loc[("XII", "T"), "2018"] == "4910"  # printed; M + F = 4510
    assert t.loc[("ALL", "T"), "2019"] == "1571540"
    review = pd.read_csv(tmp_path / "doc.review.csv", dtype=str)
    assert set(review.year) == {"2018"}


def test_srs_life_table(tmp_path):
    code, s, t = _extract(tmp_path, "srs/srs_2019-23.pdf", "srs_life_table/recipe.toml")
    assert code == 0 and s["cells"]["failed_checks"] == 0 and s["cells"]["unresolved"] == 0
    t = t.set_index(["state", "category", "age"])
    assert t.loc[("West Bengal", "Urban", "0-1"), "female_ex"] == "76.3"  # the corrigendum
    assert t.loc[("India", "Urban", "1-5"), "total_lx"] == "98036"  # the row srsindia added
    assert t.loc[("India", "Total", "0-1"), "total_ex"] == "70.3"


def test_census_iips_district(tmp_path):
    code, s, t = _extract(
        tmp_path, "iips/iips_p281_rajasthan_sirohi.pdf", "census_iips_district/recipe.toml"
    )
    assert code == 0 and s["cells"]["failed_checks"] == 0 and s["cells"]["unresolved"] == 0
    t = t.set_index(["district", "block", "year", "age"])
    # block 0 holds 2012-2016 but is headed 2027-2031; the year stays as printed
    assert t.loc[("Sirohi", "0", "2027", "All ages"), "Males"] == "543156"
    assert {y for _, b, y, _ in t.index if b == "1"} == {str(y) for y in range(2017, 2022)}


def test_census_mohfw_state(tmp_path):
    code, s, t = _extract(
        tmp_path, "mohfw/mohfw_india_p165-166.pdf", "census_mohfw_state/recipe.toml"
    )
    assert code == 0 and s["cells"]["failed_checks"] == 0 and len(s["checks_run"]) == 3
    assert s["notes"] == []
    t = t.set_index(["year", "age"])
    assert t.loc[("2011", "0-4"), "Person"] == "119827"
    assert t.loc[("2026", "0-4"), "Male"] == "56522"  # censusindia: 56943
    assert t.loc[("2036", "Total"), "Female"] == "742586"  # printed on the next page


def test_census_mohfw_misprinted_title(tmp_path):
    code, _, t = _extract(
        tmp_path, "mohfw/mohfw_uttarakhand_p182.pdf", "census_mohfw_state/recipe.toml"
    )
    assert code == 0 and set(t.title) == {"PUNJAB"}
    assert t.set_index(["year", "age"]).loc[("2011", "Total"), "Person"] == "10086"


def test_crs_state_tables(tmp_path):
    """Pin CRS wrapped DNHDD and Lakshadweep placeholders."""
    code, s, t = _extract(tmp_path, "crs/crs_2023_t1_t4.pdf", "crs_state_tables/recipe.toml")
    assert code == 0 and s["cells"]["failed_checks"] == 0 and len(s["checks_run"]) == 2
    assert s["notes"] == []
    t = t.set_index(["page", "label"])
    assert t.loc[("1", "Bihar"), "Rural_Male"] == "916009"
    assert t.loc[("1", "Dadra and Nagar Haveli and Daman and Diu"), "Total_Person"] == "12948"
    assert t.loc[("1", "Lakshadweep"), "Urban_Person"] == "-"
    assert t.loc[("2", "Rajasthan"), "Total_Person"] == "19804"


def test_crs_deaths_by_age(tmp_path):
    """Pin CRS Table 6: fake-bold State rows, and age groups adding up to them."""
    code, s, t = _extract(tmp_path, "crs/crs_2023_t6_fakebold.pdf", "crs_state_tables/table6.toml")
    assert code == 0 and s["cells"]["failed_checks"] == 0 and len(s["checks_run"]) == 3
    t = t.set_index(["page", "label", "age"])
    assert t.loc[("1", "Delhi", "All Ages"), "Total_Person"] == "132391"
    assert t.loc[("1", "Ladakh", "All Ages"), "Rural_Male"] == "388"


def test_crs_districts(tmp_path):
    """Pin CRS District Tables 7 and 8 with slanted Not Available."""
    code, s, t = _extract(
        tmp_path, "crs/crs_2016_district_rotated.pdf", "crs_district_tables/recipe.toml"
    )
    assert code == 0 and s["cells"]["failed_checks"] == 0 and len(s["checks_run"]) == 3
    t = t.set_index(["page", "label"])
    assert t.loc[("1", "Malkangiri"), "SRB"] == "951"
    assert t.loc[("2", "Cuttack"), "Total_Person"] == "31433"


def test_imd_1961_1990_abu(tmp_path):
    """Pin Abu's pages, stored with /Rotate 90 and Hindi in a legacy font."""
    fixture = "imd/imd_1961_1990_abu_p106-107.pdf"
    code, s, t = _extract(tmp_path, fixture, "imd_climatological_tables/recipe_1961_1990.toml")
    assert code == 0 and (s["cells"]["verified"], s["cells"]["unresolved"]) == (1297, 0)
    t = t.fillna("").set_index(KEY)
    jan_i = t.loc[("1", "left", "1", "I", "stn_level_pressure_hpa")]
    assert (jan_i.value, jan_i.n_agree) == ("883.9", "5")  # every engine reads the rotated page
    assert {t.loc[(p, "meta", "0", "", "station"), "value"] for p in ("1", "2")} == {"Abu"}


# examples the home page leaves out: OCR does not run in the browser; settings shows options
HIDDEN = {"mybmc_lakes", "nta_toppers", "ncvbdc_charts", "settings", "nacnet"}


def test_home_page_lists_every_example():
    listed = json.loads((ROOT / "web" / "examples.json").read_text())
    for ex in listed:  # an example names a recipe, or reads charts (pdfexorcist charts)
        assert (ROOT / ex["pdf"]).exists() and ex.get("charts", "recipe" in ex), ex["id"]
        assert "recipe" not in ex or find_shipped(ex["recipe"]), ex["id"]
    dirs = {p.name for p in EXAMPLES.iterdir() if p.is_dir() and p.name != "__pycache__"}
    assert dirs - HIDDEN == {ex["recipe"].split("/")[0] for ex in listed if "recipe" in ex}
