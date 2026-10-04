"""Command line."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import STATES, make_pdf, run

from pdfexorcist.cli import main
from pdfexorcist.extractors import EXTRACTORS

FIXTURES = Path(__file__).parent / "fixtures"
ANSI = re.compile(r"\x1b\[")

pytestmark = pytest.mark.usefixtures("wide_console")


def test_welcome():
    r = run([])
    assert r.exit_code == 0
    for cmd in (
        "pdfexorcist extract report.pdf",
        "pdfexorcist inspect",
        "recipe new",
        "pdfexorcist engines",
    ):
        assert cmd in r.stdout
    assert "--help" in r.stdout


def test_version():
    r = run(["--version"])
    assert r.exit_code == 0 and r.stdout.startswith("pdfexorcist ")


@pytest.mark.parametrize(
    "cmd",
    [
        ["extract"],
        ["inspect"],
        ["engines"],
        ["recipe", "new"],
        ["recipe", "check"],
        ["recipe", "show"],
    ],
)
def test_help_examples(cmd):
    r = run([*cmd, "--help"])
    assert r.exit_code == 0
    assert "Example" in r.stdout


def test_python_dash_m():
    r = subprocess.run(
        [sys.executable, "-m", "pdfexorcist", "--version"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert r.returncode == 0 and "pdfexorcist" in r.stdout


def test_bad_option():
    r = run(["extract", "x.pdf", "--frobnicate"])
    assert r.exit_code == 2


def test_file_shorthand_runs_extract(states_pdf, capsys):
    with pytest.raises(SystemExit) as e:
        main([str(states_pdf), "--quiet"])
    assert e.value.code == 0
    assert (states_pdf.parent / "states.csv").exists()


def test_engine_help():
    r = run(["engines"])
    assert r.exit_code == 0
    for name in EXTRACTORS:
        assert name in r.stdout
    j = json.loads(run(["engines", "--json"]).stdout)
    rows = {e["name"]: e for e in j["engines"]}
    assert set(rows) == set(EXTRACTORS)
    assert set(next(iter(rows.values()))) == {
        "name",
        "installed",
        "default",
        "reads",
        "about",
        "fix",
    }
    assert all(e["fix"] for e in rows.values() if not e["installed"])
    assert all(e["fix"] == "" for e in rows.values() if e["installed"])
    assert rows["chandra"]["reads"] == "pixels (OCR)" and not rows["chandra"]["default"]


def test_doctor_is_an_alias_of_engines():
    assert json.loads(run(["doctor", "--json"]).stdout) == json.loads(
        run(["engines", "--json"]).stdout
    )


def test_inspect_text(states_pdf):
    r = run(["inspect", "states.pdf"])
    assert r.exit_code == 0
    assert "pdfexorcist extract states.pdf" in r.stdout and "--ocr" not in r.stdout
    j = json.loads(run(["inspect", "states.pdf", "--json"]).stdout)
    assert j["pages"][0]["chars"] > 20 and j["pages"][0]["scan"] is False
    assert j["suggested"] == "pdfexorcist extract states.pdf"


def test_inspect_scan_suggests_ocr():
    r = run(["inspect", str(FIXTURES / "adsi" / "1995_t2A_p6.pdf"), "--json"])
    j = json.loads(r.stdout)
    assert j["pages"][0]["scan"] and j["suggested"].endswith("--ocr")


def test_inspect_image_suggests_ocr():
    j = json.loads(run(["inspect", str(FIXTURES / "bmc" / "2026-09-28.jpg"), "--json"]).stdout)
    assert j["kind"] == "image" and j["suggested"].endswith("--ocr")


def test_extract_output(states_pdf):
    r = run(["extract", "states.pdf"])
    assert r.exit_code == 0, r.output
    table = pd.read_csv("states.csv", dtype=str)
    assert list(table.columns) == ["page", "label", "0", "1", "2"]
    assert table.set_index("label").loc["Kerala"].tolist() == ["1", "1,020", "7", "8.0"]
    assert not Path("states.review.csv").exists()  # nothing to review
    assert "Wrote" in r.stderr and "Agreed" in r.stderr


def test_overwrite(states_pdf):
    assert run(["extract", "states.pdf", "-q"]).exit_code == 0
    r = run(["extract", "states.pdf"])
    assert r.exit_code == 2 and "already exists" in r.stderr and "--force" in r.stderr
    assert run(["extract", "states.pdf", "-q", "--force"]).exit_code == 0


def test_extract_json_summary(states_pdf):
    r = run(["extract", "states.pdf", "--json", "--quiet"])
    assert r.exit_code == 0
    s = json.loads(r.stdout)
    assert {
        "pdfexorcist",
        "input",
        "outputs",
        "review",
        "format",
        "layout",
        "pages",
        "engines",
        "min_agree",
        "cells",
        "agreement",
        "table",
        "checks",
        "checks_run",
        "notes",
        "exit_code",
    } <= set(s)
    assert s["cells"]["verified"] == 9 and s["cells"]["unresolved"] == 0
    assert sum(s["agreement"].values()) == 9
    assert s["exit_code"] == 0 and s["outputs"] == ["states.csv"] and s["review"] is None
    assert len(s["engines"]["used"]) >= 3
    assert r.stderr == ""


def test_cells_layout(states_pdf):
    pytest.importorskip("openpyxl")
    assert run(["extract", "states.pdf", "-q", "--layout", "cells", "-o", "out/"]).exit_code == 0
    cells = pd.read_csv("out/states.csv", dtype=str)
    assert {"value", "status", "votes", "sources", "dissent"} <= set(cells.columns)
    assert run(["extract", "states.pdf", "-q", "-o", "res.json"]).exit_code == 0
    assert json.loads(Path("res.json").read_text(encoding="utf-8"))[0]["label"] == "Kerala"
    assert run(["extract", "states.pdf", "-q", "-o", "res.xlsx"]).exit_code == 0
    assert pd.read_excel("res.xlsx", sheet_name=None).keys() == {"table"}
    r = run(["extract", "states.pdf", "-o", "res.txt"])
    assert r.exit_code == 2 and ".csv" in r.stderr


def test_output_folder(states_pdf):
    r = run(["extract", "states.pdf", "-q", "-o", "results"])
    assert r.exit_code == 0 and Path("results/states.csv").stat().st_size > 0


def test_page_numbers(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    make_pdf(tmp_path / "three.pdf", [[("Notes", "1")], STATES, STATES])
    r = run(["extract", "three.pdf", "--pages", "2-3", "--json", "-q"])
    s = json.loads(r.stdout)
    assert s["pages"] == [2, 3]
    assert set(pd.read_csv("three.csv").page) == {2, 3}


def test_missing_file(states_pdf):
    r = run(["extract", "stats.pdf"])
    assert r.exit_code == 2
    assert "File not found" in r.stderr and "states.pdf" in r.stderr
    assert "Traceback" not in r.output


def test_not_a_pdf(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("notes.txt").write_text("hi")
    r = run(["extract", "notes.txt"])
    assert r.exit_code == 2 and "not a PDF" in r.stderr


def test_unknown_engine_suggests(states_pdf):
    r = run(["extract", "states.pdf", "--engines", "pdfplumbr,pymupdf"])
    assert r.exit_code == 2 and "pdfplumber" in r.stderr


def test_too_few_engines_explains(states_pdf):
    r = run(["extract", "states.pdf", "--engines", "pdfplumber,pymupdf"])
    assert r.exit_code == 1 and "pdfexorcist engines" in r.stderr


def test_bad_pages(states_pdf):
    r = run(["extract", "states.pdf", "--pages", "4"])
    assert r.exit_code == 2 and "1 page" in r.stderr


def test_scan_without_ocr_suggests_ocr(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shutil.copy(FIXTURES / "adsi" / "1995_t2A_p6.pdf", "scan.pdf")
    r = run(["extract", "scan.pdf"])
    assert r.exit_code == 2 and "pdfexorcist extract scan.pdf --ocr" in r.stderr


def test_errors_in_json_mode_are_json(states_pdf):
    r = run(["extract", "nope.pdf", "--json"])
    assert r.exit_code == 2
    assert json.loads(r.stdout)["exit_code"] == 2


def test_error_trace(states_pdf, monkeypatch):
    import pdfexorcist._run as run_mod

    def boom(*a, **k):
        raise ValueError("kaboom")

    monkeypatch.setattr(run_mod, "extract", boom)
    r = run(["extract", "states.pdf"])
    assert r.exit_code == 1 and "kaboom" in r.stderr and "--debug" in r.stderr
    assert "Traceback" not in r.output
    r = run(["extract", "states.pdf", "--debug", "--force"])
    assert r.exit_code == 1 and "Traceback" in r.output


def test_plain_output(states_pdf):
    env = {**os.environ, "NO_COLOR": "1"}
    r = subprocess.run(
        [sys.executable, "-m", "pdfexorcist", "extract", "states.pdf"],
        capture_output=True,
        check=False,
        text=True,
        env=env,
    )
    assert r.returncode == 0
    assert not ANSI.search(r.stdout + r.stderr)
    assert "readings" in r.stderr  # one plain line per engine


def test_parallel_output(states_pdf):
    assert run(["extract", "states.pdf", "-q", "-o", "one.csv"]).exit_code == 0
    assert run(["extract", "states.pdf", "-q", "-o", "two.csv", "--jobs", "2"]).exit_code == 0
    assert Path("one.csv").read_text() == Path("two.csv").read_text()
    assert run(["extract", "states.pdf", "-q", "-j", "0"]).exit_code == 2  # at least 1


def test_table_leaves_out_rows_and_columns_with_no_agreed_value(tmp_path):
    """CWC basin table: header words and stray columns go to the review file only."""
    pdf = tmp_path / "bull.pdf"
    shutil.copy(FIXTURES / "cwc" / "cwc_2018-02-01_p4.pdf", pdf)
    r = run(["extract", str(pdf), "--json", "-q"])
    s = json.loads(r.stdout)
    assert r.exit_code == 0 and s["cells"]["unresolved"] > 0
    t = pd.read_csv(tmp_path / "bull.csv", dtype=str).set_index("label")
    assert len(t) == 14 and list(t.columns) == ["page", *map(str, range(8))]
    assert t.loc["GANGA"].tolist() == [
        "1",
        "28.096",
        "12.859",
        "45.77%",
        "17.358",
        "61.78%",
        "12.678",
        "45.12%",
        "1.43",
    ]
    assert t.loc["TOTAL", "1"] == "69.887"
    assert not t.drop(columns="page").isna().all(axis=1).any()  # no all-blank row
    review = pd.read_csv(tmp_path / "bull.review.csv", dtype=str)
    assert len(review) == s["cells"]["unresolved"]
