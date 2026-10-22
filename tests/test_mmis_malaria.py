"""NCVBDC Monthly Malaria Situation report: tables under the trend graphs."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run
from mmis import MONTHS, tpr

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "mmis"
FIXTURE = "mmis_cat2_2023-10_p3-4_7-8_17-18.pdf"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "mmis_malaria" / "recipe.toml"
EXPECTED = pd.read_csv(FIXTURES / "expected.csv", dtype=str, keep_default_na=False)
ROWS = ["area", "indicator", "series"]

pytestmark = pytest.mark.usefixtures("wide_console")


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> tuple[int, dict, pd.DataFrame]:
    """(exit code, JSON summary, the CSV table) of the recipe on a copy of the fixture."""
    tmp = tmp_path_factory.mktemp("mmis")
    pdf = tmp / "mmis.pdf"
    shutil.copy(FIXTURES / FIXTURE, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    table = pd.read_csv(tmp / "mmis.csv", dtype=str, keep_default_na=False)
    return r.exit_code, json.loads(r.stdout), table


def test_every_value_with_its_graph(result) -> None:
    """Pin every printed value to its area, indicator, series and month."""
    _, s, t = result
    got = {(*r[ROWS], m): r[m] for _, r in t.iterrows() for m in MONTHS if r[m] != ""}
    want = {(*r[ROWS], r.month): r.value for _, r in EXPECTED.iterrows()}
    assert got == want
    assert s["cells"]["verified"] == len(want) == 232 and s["cells"]["unresolved"] == 0


def test_context_from_the_titles(result) -> None:
    """Pin areas and indicators read from the graph titles, which camelot does not see."""
    t = result[2].set_index(ROWS)
    assert set(t.index.get_level_values("area")) == {
        "CATEGORY II STATES/UTs", "CHHATTISGARH", "WEST BENGAL"
    }  # fmt: skip
    assert t.loc[("CATEGORY II STATES/UTs", "BSE", "current"), "Sep"] == "4230022"
    assert t.loc[("CHHATTISGARH", "TPR", "avg3"), "Jan"] == "0.93"
    # the current year runs to September; West Bengal's to April
    assert t.loc[("CHHATTISGARH", "TPC", "current"), "Oct"] == ""
    assert t.loc[("WEST BENGAL", "PF", "current"), ["Apr", "May"]].tolist() == ["82", ""]


def test_the_misplaced_table_is_flagged(result) -> None:
    """Pin Chhattisgarh's PF graph, whose table is the TPC table again."""
    code, s, t = result
    assert code == 1 and s["cells"]["failed_checks"] == 21 and len(s["checks_run"]) == 3
    pf = t.set_index(ROWS).loc[("CHHATTISGARH", "PF", "current")]
    tpc = t.set_index(ROWS).loc[("CHHATTISGARH", "TPC", "current")]
    assert pf.printed == "TPC" and pf[MONTHS].tolist() == tpc[MONTHS].tolist()


def test_tpr_check_allows_rounded_averages() -> None:
    """Pin the rounding slack: 3-year averages only, and only half a case or slide."""

    def cells(series: str, tpr_value: str) -> pd.DataFrame:
        vals = {"BSE": "41562", "TPC": "160", "TPR": tpr_value}
        return pd.DataFrame(
            [{"area": "MEGHALAYA", "series": series, "month": "Aug", "indicator": i, "value": v}
             for i, v in vals.items()]
        )  # fmt: skip

    assert not tpr(cells("avg3", "0.39")).any()  # as printed: 160.5 / 41562 rounds up
    assert tpr(cells("current", "0.39")).all()  # counts are exact
    assert tpr(cells("avg3", "0.40")).all()


def test_2025_labels_wrapped_titles_and_blank_months() -> None:
    """Pin the 2025 row names, a title on two lines, OCR junk before a label, and a blank
    month inside a row (Ladakh's June 2024): values go under their month by x, not by order."""
    from mmis import parse

    xs = [100 + 40 * i for i in range(12)]
    lines = [
        [(0, "GRAPH 1: MONTH WISE TREND OF TESTED IN THE DADRA AND NAGAR HAVELI AND")],
        [(0, "DAMAN AND DIU")],
        [(x, m) for x, m in zip(xs, MONTHS, strict=True)],
        [(0, "ag Tested Current Year")] + [(xs[i], str(i)) for i in (0, 1, 2, 3, 4, 6, 7)],
        [(0, "Tested Avg Last 3 Years")] + [(x, "9") for x in xs],
    ]
    rows = list(parse([(1, lines)]))
    got = {(r["series"], r["month"]): r["value"] for r in rows}
    assert {r["area"] for r in rows} == {"THE DADRA AND NAGAR HAVELI AND DAMAN AND DIU"}
    assert {r["indicator"] for r in rows} == {"TESTED"}
    assert ("current", "Jun") not in got and got[("current", "Jul")] == "6"
    assert got[("current", "Aug")] == "7" and len(got) == 7 + 12
