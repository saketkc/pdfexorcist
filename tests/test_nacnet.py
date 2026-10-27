"""NCDC NAC-NET reports: values printed on bar and pie charts, tables, and line charts."""

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

from pdfexorcist.charts import read_charts

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "nacnet"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "nacnet" / "recipe.toml"
OLD = "nacnet_2017-2021_p19-22_26.pdf"
NEW = "nacnet_2024_p21-22_25_34_42.pdf"

pytestmark = pytest.mark.usefixtures("wide_console")


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    tmp = tmp_path_factory.mktemp("nacnet")
    out = {}
    for fixture in (OLD, NEW):
        pdf = tmp / fixture
        shutil.copy(FIXTURES / fixture, pdf)
        r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
        assert r.exit_code == 0, r.stdout
        out[fixture] = (
            json.loads(r.stdout),
            pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False),
        )
    return out


def _value(t: pd.DataFrame, item: str, category: str, series: str, field: str = "label") -> str:
    hit = t[
        (t["item"] == item) & (t.category == category) & (t.series == series) & (t.field == field)
    ]
    assert len(hit) == 1, (item, category, series, hit)
    return hit.value.iloc[0]


def test_no_value_breaks_a_check(results) -> None:
    for fixture, (s, t) in results.items():
        assert s["cells"]["failed_checks"] == 0, fixture
        assert (t.status != "unresolved").all(), t[t.status == "unresolved"]


def test_stacked_bars_and_pies(results) -> None:
    """Figure 5 as the report's text gives it; a thin Reserve segment's label above the stack;
    a pie label printed against the year in its hole."""
    t = results[OLD][1]
    assert [_value(t, "Figure 5", y, "Watch") for y in ("2017", "2018", "2021")] == [
        "51.8",
        "72.7",
        "62.7",
    ]
    assert _value(t, "Figure 5", "2019", "Reserve") == "4.7"
    assert _value(t, "Figure 6", "2017", "Access", "pct") == "43%"
    assert _value(t, "Figure 10", "Tab. Amoxycillin & Clavulanic Acid 625mg", "#92d050") == "14.7"


def test_tables_and_sections(results) -> None:
    """Table 1 runs on to a page without a caption; its section rows name the state network."""
    t = results[NEW][1]
    cells = t[t.field == "cell"]
    gj = cells[(cells.category == "G-SACNET SITES 19") & (cells.series == "Bed Strength")]
    assert gj.value.tolist() == ["330"]
    assert _value(t, "Figure 4b", "GJ19", "#4472c4") == "856"
    assert _value(t, "Figure 10", "", "Access", "value") == "55.1"
    assert _value(t, "Figure 10", "", "Access", "pct") == "42%"
    labels = t[(t["item"] == "Figure 7a")]
    assert (
        set(labels.category) >= {"NAC 4", "NAC 32"}
        and not labels.category.str.contains("J01").any()
    )


def test_line_charts_match_their_printed_labels() -> None:
    """Values from the vector paths agree with the numbers printed on the points (Figure 4);
    a dashed 'Annual' series in each colour stays a series of its own (Figure 7)."""
    df = read_charts(FIXTURES / OLD)
    f4 = df[df.title.str.startswith("Figure 4")].set_index(["series", "category"]).value
    for (year, month), printed in {
        ("2018", "Oct"): 146.4,
        ("2017", "Nov"): 119.4,
        ("2021", "Apr"): 112.3,
    }.items():
        assert abs(f4[(year, month)] - printed) < 0.1
    assert {"Access", "Access Annual"} <= set(df.series)
