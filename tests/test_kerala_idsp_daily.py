"""Kerala DHS communicable diseases daily report: counts by district and for the State."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run
from kerala_idsp_daily import KNOWN, tot_is_state
from kerala_layouts import LAYOUTS, pick

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "kerala_idsp_daily"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "kerala_idsp_daily" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
KEY = ["table", "area", "disease", "subgroup", "measure", "period"]

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[dict, pd.DataFrame]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    summary = json.loads(r.stdout)
    assert r.exit_code == (1 if summary["cells"]["failed_checks"] else 0), r.stdout
    return summary, pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    tmp = tmp_path_factory.mktemp("kerala_daily")
    return {m["report_date"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def _value(t: pd.DataFrame, *key: str) -> str:
    return t.set_index(KEY).loc[key, "value"]


def test_every_cell_agreed(results) -> None:
    """Every cell is agreed by the four engines; one layout per report; five checks run."""
    seen = {}
    for date, (s, t) in results.items():
        c = s["cells"]
        assert c["verified"] == c["total"], date
        assert len(s["checks_run"]) == 5, date
        layout = set(t.loc[t["table"] == "district", "layout"])
        assert len(layout) == 1, date
        (name,) = layout
        n = t["table"].value_counts()
        # 15 rows (14 districts and TOT) of the layout's columns; 14 dengue list counts
        assert n["district"] == 15 * len(LAYOUTS[name]) and n["dengue_list"] == 14, date
        seen[date] = (name, c["total"], c["failed_checks"])
    assert seen == {
        "2026-10-24": ("measles_2026", 760, 0),
        "2024-01-05": ("aesje_2023", 737, 0),
        "2018-03-01": ("typhoid_2016", 689, 2),
        "2016-03-02": ("kfd_2016", 759, 0),
    }


def test_pinned_counts(results) -> None:
    """Counts against the printed reports."""
    t = results["2026-10-24"][1]
    assert _value(t, "district", "MPM", "Fever", "OP", "cases", "day") == "1546"
    assert _value(t, "district", "TOT", "Dengue", "", "suspected", "day") == "169"
    assert _value(t, "district", "IDK", "Malaria", "PV imported", "confirmed", "day") == "2"
    assert _value(t, "district", "TOT", "Influenza", "", "confirmed", "day") == "26"
    assert _value(t, "dengue_list", "KKD", "Dengue", "", "confirmed", "day") == "12"
    assert _value(t, "state", "Kerala", "Dengue", "", "suspected", "year") == "34386"
    assert _value(t, "state", "Kerala", "Malaria", "imported", "confirmed", "year") == "1062"
    assert _value(t, "state", "Kerala", "Amoebic meningoencephalitis", "", "deaths", "year") == "45"
    # blank cells are not read as counts
    state = t[(t["table"] == "state") & (t["disease"] == "JE")]
    assert set(state["measure"]) == {"confirmed", "deaths"}
    t = results["2024-01-05"][1]
    assert _value(t, "district", "WYD", "Fever", "OP", "cases", "day") == "451"
    assert _value(t, "district", "EKM", "Dengue", "", "confirmed", "day") == "19"
    assert _value(t, "dengue_list", "TVM", "Dengue", "", "confirmed", "day") == "19"
    assert _value(t, "state", "Kerala", "Dengue", "", "confirmed", "month") == "261"
    assert not t["disease"].str.contains("Draft|by |MANAGER").any()
    t = results["2016-03-02"][1]
    assert _value(t, "district", "TOT", "ADD", "", "cases", "day") == "2705"
    assert _value(t, "district", "TOT", "Malaria", "PF indigenous", "confirmed", "day") == "1"
    assert _value(t, "district", "TOT", "KFD", "", "confirmed", "day") == "0"


def test_printed_inconsistency_flagged(results) -> None:
    """1 March 2018 prints a suspected scrub typhus case on the day but none in the month."""
    t = results["2018-03-01"][1]
    bad = t[t["failed"] != ""]
    assert set(bad["disease"]) == {"Scrub typhus"} and set(bad["period"]) == {"day", "month"}


def test_tot_is_state_catches_a_misread(results) -> None:
    """Change one TOT count and the TOT-against-State check fails it and the State's count."""
    t = results["2026-10-24"][1][[*KEY, "value"]].copy()
    assert not tot_is_state(t).any()
    hit = (t["table"] == "district") & (t["area"] == "TOT") & (t["disease"] == "Dengue")
    t.loc[hit & (t["measure"] == "confirmed"), "value"] = "64"
    bad = t[tot_is_state(t)]
    assert set(bad["table"]) == {"district", "state"} and set(bad["disease"]) == {"Dengue"}


def test_unknown_layout() -> None:
    """A district table of another width is not given a layout."""
    assert pick(["x"] * 31) is None
    assert pick(["x"] * 34) == "kfd_2016"


def test_disease_names(results) -> None:
    """Every disease takes one spelling; death notes beside a row are not names."""
    for date, (_, t) in results.items():
        assert set(t["disease"]) <= KNOWN, date
