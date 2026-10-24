"""India TB Report annexures: State/UT notification, characteristics and treatment outcomes."""

import csv
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
import tb_report_checks
from cli_helpers import run

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "tb_report"
RECIPE = ROOT / "pdfexorcist" / "recipes" / "tb_report" / "recipe.toml"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
Y2024 = "tb_report_2024_p199-218.pdf"
Y2023 = "tb_report_2023_p213-248.pdf"

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str) -> tuple[dict, pd.DataFrame]:
    pdf = tmp / fixture
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    assert r.exit_code == 0, r.stdout
    table = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    return json.loads(r.stdout), table.set_index(["table", "state", "col"])


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[dict, pd.DataFrame]]:
    tmp = tmp_path_factory.mktemp("tb")
    return {m["fixture"]: _extract(tmp, m["fixture"]) for m in MANIFEST}


def test_every_cell_agreed_and_checks_pass(results) -> None:
    """Pin each fixture's cell count; every cell agreed and every check passed."""
    totals = {}
    for fixture, (s, _) in results.items():
        c = s["cells"]
        assert c["verified"] == c["total"] and c["failed_checks"] == 0, fixture
        assert len(s["checks_run"]) == 3
        totals[fixture] = c["total"]
    assert totals == {Y2024: 978, Y2023: 771}


def test_tables_and_states(results) -> None:
    """Pin the tables read and their rows: a sideways 2023 table is named by its header."""
    t = results[Y2024][1]
    rows = t.reset_index().groupby("table")["state"].nunique().to_dict()
    assert rows == {"2.1": 37, "2.13": 37, "3.1": 21}
    t = results[Y2023][1]
    rows = t.reset_index().groupby("table")["state"].nunique().to_dict()
    assert rows == {"notification": 18, "3.1": 37}
    assert t.loc[("3.1", "India", "0"), "page"] == "3"  # the second page continues 3.1


def test_wrapped_percentages(results) -> None:
    """Pin "count (%)" cells whose % is printed on the line below the count."""
    t = results[Y2023][1]
    assert t.loc[("3.1", "Andhra Pradesh", "1"), ["value", "pct"]].tolist() == ["31713", "52.1"]
    assert t.loc[("3.1", "India", "4"), ["value", "pct"]].tolist() == ["35222", "2.3"]
    t = results[Y2024][1]
    assert t.loc[("2.13", "Uttar Pradesh", "0"), ["value", "pct"]].tolist() == ["112391", "59.1"]
    assert t.loc[("2.13", "India", "2"), ["value", "pct"]].tolist() == ["647440", "64.7"]


def test_names_and_blanks(results) -> None:
    """Pin wrapped and "&" State names, NA and "-" kept as printed, and the column names."""
    t = results[Y2023][1]
    dnh = "Dadra and Nagar Haveli and Daman and Diu"  # "Dadra And Nagar Haveli And Daman And Diu"
    assert t.loc[("notification", dnh, "3"), ["value", "pct"]].tolist() == ["1294", "132"]
    assert t.loc[("notification", "Andaman and Nicobar Islands", "4"), "pct"] == "240"
    assert t.loc[("notification", "Jammu and Kashmir", "8"), "value"] == "81.9"
    t = results[Y2024][1]
    assert t.loc[("2.13", "Lakshadweep", "1"), "value"] == "NA"
    assert t.loc[("2.1", "Lakshadweep", "1"), "value"] == "-"
    assert t.loc[("3.1", "Lakshadweep", "0"), "column"] == "TB patients notified"
    hiv = "TB patients with known HIV status, n (%) / Total"
    assert t.loc[("2.1", "India", "2"), "column"] == hiv


def _cells(rows: list[tuple]) -> pd.DataFrame:
    cols = ["table", "state", "col", "column", "field", "value"]
    return pd.DataFrame([dict(zip(cols, r, strict=True)) for r in rows]).assign(kind="outcome")


def test_misprint_fails_both_checks() -> None:
    """2024 Annexure 3.13 prints Uttar Pradesh's regimen change as 662 (1.2): 2662 is 1.2%."""
    rows = [
        ("3.13", "Uttar Pradesh", 0, "TB patients notified", "value", "221277"),
        ("3.13", "Uttar Pradesh", 6, "Regimen change, n(%)", "value", "662"),
        ("3.13", "Uttar Pradesh", 6, "Regimen change, n(%)", "pct", "1.2"),
        ("3.13", "Bihar", 0, "TB patients notified", "value", "100"),
        ("3.13", "Bihar", 6, "Regimen change, n(%)", "value", "1"),
        ("3.13", "Bihar", 6, "Regimen change, n(%)", "pct", "1"),
        ("3.13", "India", 0, "TB patients notified", "value", "221377"),
        ("3.13", "India", 6, "Regimen change, n(%)", "value", "2663"),
        ("3.13", "India", 6, "Regimen change, n(%)", "pct", "1.2"),
    ]
    df = _cells(rows)
    assert df[tb_report_checks.pct_matches(df)].state.tolist() == ["Uttar Pradesh"]
    assert df[tb_report_checks.states_sum_to_india(df)][["state", "col"]].values.tolist() == [
        ["India", 6]
    ]
    df.loc[1, "value"] = "2662"
    assert not tb_report_checks.pct_matches(df).any()
    assert not tb_report_checks.states_sum_to_india(df).any()
