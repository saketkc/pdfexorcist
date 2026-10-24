"""Charts pasted as pictures: settings, matching and voting; OCR runs only when asked."""

import json
import os
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import run

from pdfexorcist._chart_image import match
from pdfexorcist._chart_ocr import _slots, _tokens
from pdfexorcist._chart_settings import ChartSettings
from pdfexorcist._recipe_load import loads
from pdfexorcist._shipped import find_shipped
from pdfexorcist.charts import read_charts
from pdfexorcist.recipe import RecipeError, load

FIXTURES = Path(__file__).parent / "fixtures" / "ncvbdc"
PICTURES = FIXTURES / "mmis_cat1_2020-12_p3-4_7-8.pdf"
VECTOR = FIXTURES / "malaria_2026_08_p3_p4_p17.pdf"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# Graph 1 (BSE, Category 1, December 2020), read from the picture by eye
BSE = {
    "Current": [928282, 1111648, 726388, 325794, 442249, 590491, 625284, 652026, 1200646,
                1322722, 1376420, 1765318],
    "Average": [621214, 736060, 628489, 484402, 588770, 608025, 692377, 737182, 832201,
                910078, 967359, 1048356],
}  # fmt: skip


def test_shipped_recipe() -> None:
    rec = load(find_shipped("ncvbdc_charts"))
    assert (rec.charts.kind, rec.charts.min_agree) == ("image", 2)  # min_agree from [engines]
    assert rec.charts.title == r"GRAPH \d+: MONTH WISE TREND"
    assert len(rec.check_functions()) == 2


@pytest.mark.parametrize(
    "text, says",
    [
        ('kind = "pie"', "kind must be one of auto, vector, image"),
        ('colour = "#ffc000"', "unknown setting 'colour' in [charts]"),
        ('series = { A = "yellow" }', 'series.A should be a color like "#ffc000"'),
        ('crop = { tesseract = "sharp" }', "crop.tesseract must be color or binary"),
        ("box_height = [12]", "box_height needs two whole numbers"),
        ('cells = "nowhere.py:cells"', "file 'nowhere.py' not found"),
    ],
)
def test_bad_settings(text: str, says: str) -> None:
    with pytest.raises(RecipeError, match=None) as e:
        loads(f"[charts]\n{text}\n")
    assert says in e.value.message


def test_cells_function(tmp_path: Path) -> None:
    (tmp_path / "mine.py").write_text("def cells(image, words, settings):\n    return []\n")
    (tmp_path / "r.toml").write_text(
        '[charts]\ncells = "mine.py:cells"\nseries = { A = "#ffc000" }\n'
    )
    settings = load(tmp_path / "r.toml").charts
    assert settings.cells(None, [], settings) == [] and settings.series == {"A": (255, 192, 0)}


def test_match() -> None:
    cats = [(10.0 * i, m) for i, m in enumerate(MONTHS[:5])]
    assert match([0, 10, 21], cats) == ["Jan", "Feb", "Mar"]
    assert match([0, 11, 12, 20, 30, 40], cats) == ["Jan", "Feb", None, "Mar", "Apr", "May"]
    assert match([33], cats) == ["Apr"]


def test_tokens() -> None:
    assert [t for *_, t in _tokens("95,29,475  1,200")] == ["9529475", "1200"]
    assert [t for *_, t in _tokens("928282 1111648 726388")] == ["928282", "1111648", "726388"]


def test_slots_by_position() -> None:
    """Two engines split one crop differently; numbers that overlap share a place."""
    found = pd.DataFrame(
        [
            {"method": "a", "chart": 0, "box": 0, "x0": 0, "x1": 30, "value": "928282"},
            {"method": "a", "chart": 0, "box": 0, "x0": 40, "x1": 70, "value": "726388"},
            {"method": "b", "chart": 0, "box": 0, "x0": 1, "x1": 31, "value": "928282"},
            {"method": "b", "chart": 0, "box": 0, "x0": 41, "x1": 69, "value": "726388"},
        ]
    )
    slots = _slots(found)
    assert slots.groupby("token").value.agg(set).tolist() == [{"928282"}, {"726388"}]


def test_no_ocr_engine_is_one_note() -> None:
    df = read_charts(PICTURES, settings=ChartSettings(kind="image", engines=("no_such_engine",)))
    assert df.empty and not df.attrs["skipped"]
    assert df.attrs["notes"] == ["charts in pictures need an OCR engine (pdfexorcist engines)"]


def test_auto_reads_no_pictures_in_a_vector_report() -> None:
    df = read_charts(VECTOR, [1])
    assert set(df.status) == {"estimated"} and df.attrs["notes"] == []


def test_recipe_checks_fail_the_run(tmp_path: Path) -> None:
    (tmp_path / "mine.py").write_text(
        "def big(df):\n    return df.value > 1e7\n\nbig.__name__ = 'value <= 1e7'\n"
    )
    (tmp_path / "r.toml").write_text(
        '[charts]\nkind = "vector"\n\n[[checks]]\nfunction = "mine.py:big"\n'
    )
    out = tmp_path / "c.csv"
    r = run(
        [
            "charts",
            str(VECTOR),
            "-p",
            "1",
            "--recipe",
            str(tmp_path / "r.toml"),
            "-o",
            str(out),
            "--json",
        ]
    )
    summary = json.loads(r.stdout)
    assert r.exit_code == 1 and summary["failed_checks"] > 0
    assert set(pd.read_csv(out).failed.dropna()) == {"value <= 1e7"}


@pytest.mark.skipif(not os.environ.get("PDFEXORCIST_OCR_TESTS"), reason="slow OCR test")
def test_pictures_with_ocr(tmp_path: Path) -> None:
    """Graph 1 against the eye: right, unresolved, or flagged off its line; never silently wrong."""
    out = tmp_path / "c.csv"
    r = run(["charts", str(PICTURES), "--recipe", "ncvbdc_charts", "-o", str(out), "--json"])
    assert r.exit_code in (0, 1), r.output
    df = pd.read_csv(out)
    g1 = df[(df.page == 1) & (df.chart == 1)]
    right = 0
    for which, values in BSE.items():
        s = g1[g1.series.str.contains(which)].set_index("category")
        for month, want in zip(MONTHS, values, strict=True):
            got = s.loc[month] if month in s.index else None
            if got is not None and got.value == want:
                right += 1
            elif got is not None and got.status == "verified":  # flagged by a check
                assert isinstance(got.failed, str) and got.failed, (which, month, got.value)
    assert right >= 20
    tpc = df[(df.page == 1) & (df.chart == 2) & df.series.str.contains("Average")]
    off = tpc.failed.fillna("").str.contains("value off its line")
    assert off.sum() >= 8  # its labels and its line disagree


def test_legend_names_snap_to_the_settings() -> None:
    from pdfexorcist._chart_legend import _name

    settings = ChartSettings(names=("Current Year", "Average 3 years"))
    assert _name("• TPCAverage 3 years", settings) == "Average 3 years"
    assert _name("BSE Current Year", settings) == "Current Year"
    assert _name("Rainfall", settings) == "Rainfall"  # no near name: kept as read


def test_ncvbdc_checks_pass_without_charts() -> None:
    """Pin the checks on a PDF with no chart (extract --recipe ncvbdc_charts on another report)."""
    from charts_checks import pf_within_tpc, tpr

    cells = pd.DataFrame({"page": [1], "row": ["Kerala#1"], "col": [0], "value": ["12"]})
    assert not tpr(cells).any() and not pf_within_tpc(cells).any()
