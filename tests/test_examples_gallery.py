"""Example recipes."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLES = ROOT / "examples"

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
