"""Recipes on the settings docs page."""

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


def _extract(
    tmp_path: Path, fixture: str, recipe: str, *extra: str, out: str = "doc.csv"
) -> tuple[int, dict]:
    """(exit code, JSON summary) of one recipe run on a fixture copy."""
    pdf = tmp_path / "doc.pdf"
    shutil.copy(FIXTURES / fixture, pdf)
    args = ["extract", str(pdf), "--recipe", str(EXAMPLES / recipe), "-o", str(tmp_path / out)]
    r = run([*args, *extra, "--json", "-q"])
    return r.exit_code, json.loads(r.stdout)


def test_rows_unlabelled(tmp_path):
    """Pin exclusion of serial 31 from an arithmetic total."""
    code, s = _extract(tmp_path, "cii/cii_2023_1A.4_p47.pdf", "settings/cii_rows.toml")
    assert code == 1
    assert (s["cells"]["verified"], s["cells"]["unresolved"]) == (352, 9)
    assert s["checks"] == {"Total I = Hit and Run I + Other I": 3}
    review = pd.read_csv(tmp_path / "doc.review.csv", dtype=str)
    failed = review[review.reason.str.startswith("fails")]
    assert sorted(failed.value) == ["2.8", "31", "6.0"]


def test_columns_row(tmp_path):
    code, s = _extract(
        tmp_path, "cii/cii_2023_1A.4_p47.pdf", "settings/cii_columns.toml", out="doc.xlsx"
    )
    assert code == 0 and s["format"] == "xlsx" and s["checks_run"]
    assert (s["cells"]["verified"], s["cells"]["unresolved"]) == (387, 10)
    assert s["engines"]["used"]["pdftotext"] == 387  # tolerance = 0.6
    sheets = pd.read_excel(tmp_path / "doc.xlsx", sheet_name=None, dtype=str)
    assert list(sheets) == ["table", "review"]
    t = sheets["table"]
    unlabelled = t[t.label.isna()].iloc[0]
    assert [unlabelled[c] for c in ("0", "1", "4", "7")] == ["31", "77", "36", "41"]


def test_tolerance_json(tmp_path):
    code, s = _extract(
        tmp_path, "cii/cii_2021_1A.1_p43.pdf", "settings/cii_population.toml", out="doc.json"
    )
    assert code == 0 and s["layout"] == "cells" and s["cells"]["failed_checks"] == 0
    assert s["notes"] == []
    cells = json.loads((tmp_path / "doc.json").read_text())
    assert len(cells) == 234
    total = next(c for c in cells if c["label"] == "TOTAL ALL INDIA" and c["col"] == 3)
    assert total["value"] == "13671.8" and total["votes"] == "13671.8×5"


def test_relative_tolerance_is_needed(tmp_path):
    """Pin the need for rounding tolerance."""
    text = (EXAMPLES / "settings" / "cii_population.toml").read_text()
    recipe = tmp_path / "strict.toml"
    recipe.write_text(text.replace("tolerance = 0.0001", ""))
    pdf = tmp_path / "doc.pdf"
    shutil.copy(FIXTURES / "cii" / "cii_2021_1A.1_p43.pdf", pdf)
    r = run(["extract", str(pdf), "--recipe", str(recipe), "--json", "-q"])
    assert r.exit_code == 1 and json.loads(r.stdout)["cells"]["failed_checks"] > 0


def test_unanimous_with_min_unopposed(tmp_path):
    fixture = "nfhs6_state/nfhs6_chandigarh_p145-147.pdf"
    code, s = _extract(tmp_path, fixture, "nfhs6/state.toml", "-k", "5", "--force")
    assert code == 0 and (s["cells"]["verified"], s["cells"]["unresolved"]) == (260, 144)
    code, s = _extract(tmp_path, fixture, "nfhs6/unanimous.toml", "--force")
    assert code == 0 and s["min_agree"] == 5
    assert (s["cells"]["verified"], s["cells"]["unresolved"]) == (404, 0)


def test_families(tmp_path):
    code, s = _extract(tmp_path, "nfhs5_state/nfhs5_chandigarh_p3-6.pdf", "nfhs5/families.toml")
    assert code == 0 and (s["cells"]["verified"], s["cells"]["unresolved"]) == (477, 47)
    review = pd.read_csv(tmp_path / "doc.review.csv", dtype=str)
    assert "pdfminer" in set(review.sources.str.split("|").explode())


def test_normalize_switch_and_function(tmp_path):
    pytest.importorskip("pyarrow")
    code, s = _extract(
        tmp_path,
        "nfhs5_state/nfhs5_chandigarh_p3-6.pdf",
        "nfhs5/numbers.toml",
        out="doc.parquet",
    )
    assert code == 0 and (s["cells"]["verified"], s["cells"]["unresolved"]) == (490, 3)
    assert (tmp_path / "doc.review.parquet").exists()
    t = pd.read_parquet(tmp_path / "doc.parquet").fillna("").astype(str)
    t = t.set_index(["geo", "indicator_no"])
    assert t.loc[("Chandigarh", "47")].tolist() == ["state", "5586", "*", "5546", "2357"]
    assert t.loc[("Chandigarh", "6"), "nfhs4_total"] == ""  # "na", dropped


def test_original_pages(tmp_path):
    code, s = _extract(tmp_path, "crs/crs_2023_t1_t4.pdf", "crs_state_tables/table4.toml")
    assert code == 0 and s["pages"] == [2]
    assert (s["cells"]["verified"], s["cells"]["unresolved"]) == (324, 9)
    t = pd.read_csv(tmp_path / "doc.csv", dtype=str).set_index(["page", "label"])
    assert t.loc[("2", "Andhra Pradesh"), "Total_Person"] == "1997"


def test_doc_unfitted(tmp_path):
    code, s = _extract(tmp_path, "mccd/mccd_2011.pdf", "mccd/unfitted.toml")
    assert code == 1
    assert (s["cells"]["verified"], s["cells"]["unresolved"]) == (1782, 1782)
    assert s["cells"]["failed_checks"] == 768
    assert s["engines"]["used"]["camelot"] == 3564 and s["engines"]["used"]["pymupdf"] == 1782


def test_cleaning(tmp_path):
    """Pin numeric cleaning before voting and checks."""
    shutil.copy(FIXTURES / "synthetic/cleaning.pdf", tmp_path / "doc.pdf")
    out = tmp_path / "doc.csv"
    args = [
        "extract",
        str(tmp_path / "doc.pdf"),
        "--recipe",
        str(EXAMPLES / "settings/cleaning.toml"),
    ]
    r = run([*args, "-o", str(out), "--json", "-q"])
    s = json.loads(r.stdout)
    assert r.exit_code == 0 and s["cells"]["verified"] == 12 and not s["checks"]
    table = pd.read_csv(out, dtype=str).set_index("label")
    assert table.loc["North", ["0", "1", "2"]].tolist() == ["65.3", "-4.0", "61.3"]
    assert table.loc["South", "1"] == "(7.0)"  # kept as printed; number holds 7.0
    assert table.loc["East", "1"] == "13.4"


@pytest.mark.skipif(
    not __import__("os").environ.get("PDFEXORCIST_OCR_TESTS"),
    reason="slow OCR test; set PDFEXORCIST_OCR_TESTS=1",
)
def test_ocr_image(tmp_path):
    """Pin OCR agreement and values for cleaning.png."""
    shutil.copy(FIXTURES / "synthetic/cleaning.png", tmp_path / "doc.png")
    out = tmp_path / "doc.csv"
    args = [
        "extract",
        str(tmp_path / "doc.png"),
        "--recipe",
        str(EXAMPLES / "settings/cleaning_ocr.toml"),
    ]
    r = run([*args, "-o", str(out), "--json", "-q"])
    table = pd.read_csv(out, dtype=str).set_index("label")
    assert table.loc["North", ["0", "1", "2"]].tolist() == ["65.3", "-4.0", "61.3"]
    assert table.loc["All regions", ["0", "1", "2"]].tolist() == ["577.8", "16.4", "594.2"]
    assert not json.loads(r.stdout)["checks"]
