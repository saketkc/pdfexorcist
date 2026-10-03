"""Recipe format, errors and wizard."""

import json
import os
import shutil
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import make_pdf, run

import pdfexorcist._wizard as wizard
from pdfexorcist import pages_matching, parse_pages
from pdfexorcist.doctor import installed_ocr
from pdfexorcist.recipe import RecipeError, load, loads, parse_rule

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLES = ROOT / "examples"

pytestmark = pytest.mark.usefixtures("wide_console")


def test_parse_rule():
    assert parse_rule("T = M + F") == ("T", "==", ("M", "F"))
    assert parse_rule("All India >= rest") == ("All India", ">=", None)
    assert parse_rule("TOTAL (IPC+SLL) = IPC + SLL") == (
        "TOTAL (IPC+SLL)",
        "==",
        ("IPC", "SLL"),
    )
    with pytest.raises(ValueError):
        parse_rule("T M F")


def test_parse_pages():
    assert parse_pages("1-3, 7", 10) == [1, 2, 3, 7]
    assert parse_pages("9-", 10) == [9, 10]
    for bad in ("0", "3-1", "11", "x"):
        with pytest.raises(ValueError):
            parse_pages(bad, 10)


def test_pages_matching(tmp_path):
    pdf = make_pdf(
        tmp_path / "doc.pdf",
        [[("a", "1")]] * 5,
        titles=[
            "Contents: Table 4 - by States",
            "TABLE 3",
            "TABLE 4 - by STATES",
            "more of it",
            "TABLE 5 -",
        ],
    )
    # the contents page matches too, so the run starts there unless within skips it
    assert pages_matching(pdf, start=r"TABLE\s*4\s*-.*STATES", stop=r"TABLE\s*5") == [
        1,
        2,
        3,
        4,
    ]
    assert pages_matching(
        pdf,
        start=r"TABLE\s*4\s*-.*STATES",
        stop=r"TABLE\s*5",
        within=parse_pages("2-", 5),
    ) == [3, 4]
    assert pages_matching(pdf, match="table 3") == [2]


def test_normalize_rules():
    rec = loads(
        "[normalize]\nraised_dots = true\nremove_commas = true\nremove_footnote_marks = "
        "true\nminus_signs = true\n"
    )
    norm = rec.normalizer()
    assert [norm(v) for v in ("65·3", "1,020", "490*", "−4", "*", "-")] == [
        "65.3",
        "1020",
        "490",
        "-4",
        "*",
        "-",
    ]


def write_recipe(tmp_path: Path, text: str, name: str = "r.toml") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


@pytest.mark.parametrize(
    "text, line, words",
    [
        (
            '[pages]\nselect = "1-3"\n[parser]\ntyp = "rows"\n',
            4,
            ["unknown setting 'typ'", "Did you mean 'type'"],
        ),
        ("[pagez]\nselect = '1'\n", 1, ["unknown section [pagez]", "[pages]"]),
        (
            'name = "x"\n[engines]\nuse = ["pdfplumbr"]\n',
            3,
            ["unknown engine", "pdfplumber"],
        ),
        ('[parser]\nmin_values = "two"\n', 2, ["whole number"]),
        ("[parser]\ntype = rows\n", 2, ["not valid TOML"]),
        ('[[checks]]\ncolumn = "sex"\nrule = "T M F"\n', 3, ["rule", "T = M + F"]),
        ("[pages]\nstop = 'x'\n", 2, ["stop needs a start"]),
        ("[pages]\nstart = '(unclosed'\n", 2, ["regular expression"]),
        ('[parser]\ntype = "custom"\n', 2, ["function"]),
        ('[output]\nlayout = "wide"\n', 2, ["layout"]),
    ],
)
def test_recipe_error_line(tmp_path, text, line, words):
    p = write_recipe(tmp_path, text)
    with pytest.raises(RecipeError) as e:
        load(p)
    assert e.value.line == line, e.value.message
    r = run(["recipe", "check", str(p)])
    assert r.exit_code == 2
    msg = " ".join(r.stderr.split())
    assert f"line {line}" in msg
    for w in words:
        assert w in msg


def test_recipe_function_errors(tmp_path):
    (tmp_path / "good.py").write_text("def parse(pages):\n    return iter(())\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def parse(pages)\n    pass\n", encoding="utf-8")
    cases = {
        'function = "missing.py:parse"': "not found",
        'function = "good.py:prase"': "Did you mean 'parse'",
        'function = "broken.py:parse"': "line 1",
        'function = "../good.py:parse"': "outside the recipe's folder",
        'function = "good.py"': "my_file.py:function_name",
    }
    for setting, words in cases.items():
        p = write_recipe(tmp_path, f'[parser]\ntype = "custom"\n{setting}\n')
        r = run(["recipe", "check", str(p)])
        assert r.exit_code == 2, setting
        assert words in " ".join(r.stderr.split()), (setting, r.stderr)
        assert "Traceback" not in r.output


def test_recipe_show_and_json(tmp_path):
    p = EXAMPLES / "crime_in_india.toml"
    r = run(["recipe", "show", str(p)])
    assert (
        r.exit_code == 0 and "TOTAL ALL INDIA" in r.stdout and "remove thousands commas" in r.stdout
    )
    assert "rule =" in run(["recipe", "show", str(p), "--raw"]).stdout
    j = json.loads(run(["recipe", "show", str(p), "--json"]).stdout)
    assert j["parser"] == "rows" and j["min_values"] == 3 and len(j["checks"]) == 2


def test_empty_rule(states_pdf, tmp_path):
    p = write_recipe(
        tmp_path,
        '[[checks]]\ncolumn = "label"\nrule = "Totl = rest"\nby = ["page", "col"]\n',
    )
    s = json.loads(run(["extract", "states.pdf", "--recipe", str(p), "--json", "-q"]).stdout)
    assert any("found no label named 'Totl'" in n for n in s["notes"])


def test_failed_check(states_pdf, tmp_path):
    p = write_recipe(
        tmp_path,
        '[[checks]]\ncolumn = "label"\nrule = "Goa = Kerala"\nby = ["page", "col"]\n',
    )
    r = run(["extract", "states.pdf", "--recipe", str(p), "--json", "-q"])
    s = json.loads(r.stdout)
    assert r.exit_code == 1 and s["exit_code"] == 1 and s["cells"]["failed_checks"] > 0
    review = pd.read_csv("states.review.csv", dtype=str)
    assert review.reason.str.startswith("fails:").all()


def test_check_passes(states_pdf, tmp_path):
    p = write_recipe(
        tmp_path,
        '[normalize]\nremove_commas = true\n[[checks]]\ncolumn = "label"\nrule = "Total = '
        'rest"\nby = ["page", "col"]\n',
    )
    s = json.loads(run(["extract", "states.pdf", "--recipe", str(p), "--json", "-q"]).stdout)
    assert s["exit_code"] == 0 and s["checks_run"] == [
        "label 'Total' = the rest, within each page, col"
    ]


def test_recipe_new_scripted(states_pdf):
    r = run(
        [
            "recipe",
            "new",
            "states.pdf",
            "--yes",
            "--clean",
            "commas",
            "--min-values",
            "2",
            "--total",
            "label: Total = rest",
            "-o",
            "mine.toml",
        ]
    )
    assert r.exit_code == 0, r.output
    assert "Saved" in r.stdout and "totals add up" in r.stdout
    rec = load(Path("mine.toml"))
    assert rec.remove_commas and rec.min_values == 2 and rec.sample == "states.pdf"
    assert rec.checks[0].total == "Total" and rec.checks[0].by == ("page", "col")
    assert run(["recipe", "check", "mine.toml"]).exit_code == 0
    s = json.loads(run(["extract", "states.pdf", "--recipe", "mine.toml", "--json", "-q"]).stdout)
    assert s["exit_code"] == 0 and s["checks_run"]
    again = run(["recipe", "new", "states.pdf", "--yes", "--no-preview", "-o", "mine.toml"])
    assert again.exit_code == 2 and "already exists" in again.stderr


def test_wizard_no_tty(states_pdf):
    r = run(["recipe", "new"], input="")
    assert r.exit_code == 2 and "sample" in r.stderr.lower()
    r = run(["recipe", "new", "states.pdf", "--no-preview"], input="")
    assert r.exit_code == 0 and Path("states.recipe.toml").exists()


def test_recipe_new_bad_total(states_pdf):
    r = run(["recipe", "new", "states.pdf", "--yes", "--total", "Total = rest"])
    assert r.exit_code == 2 and "COLUMN: RULE" in r.stderr


def test_recipe_new_interactive(states_pdf, monkeypatch):
    monkeypatch.setattr(wizard, "stdin_is_tty", lambda: True)
    answers = [
        "1",  # pages
        "n",  # not a scan
        "rows",  # parser
        "2",  # min values
        "y",  # clean the commas that were seen
        "",  # name: the suggestion
        "y",  # add a total
        "row",
        "",  # total label: the suggestion (Total)
        "",  # parts: all the other rows
        "",  # "="
        "n",  # no other total
        "",  # save: yes
    ]
    r = run(["recipe", "new", "states.pdf"], input="\n".join(answers) + "\n")
    assert r.exit_code == 0, r.output
    assert "First rows of the result" in r.stdout and "totals add up" in r.stdout
    rec = load(Path("states.recipe.toml"))
    assert rec.select == "1" and rec.remove_commas and rec.parser == "rows"
    assert rec.checks[0].total == "Total" and rec.checks[0].parts is None


@pytest.mark.parametrize(
    "recipe",
    sorted(EXAMPLES.rglob("*.toml")),
    ids=lambda p: p.parent.name + "/" + p.name,
)
def test_example_recipes_are_valid(recipe):
    r = run(["recipe", "check", str(recipe)])
    assert r.exit_code == 0, r.output
    assert (recipe.parent / load(recipe).sample).exists()  # the sample it names is a fixture


def test_example_generic_text_table(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    shutil.copy(FIXTURES / "cii" / "cii_2021_1A.1_p43.pdf", "cii.pdf")
    r = run(
        [
            "extract",
            "cii.pdf",
            "--recipe",
            str(EXAMPLES / "crime_in_india.toml"),
            "--json",
            "-q",
        ]
    )
    s = json.loads(r.stdout)
    assert r.exit_code == 0 and s["cells"]["failed_checks"] == 0 and len(s["checks_run"]) == 2
    assert s["notes"] == []  # both rules found their rows
    table = pd.read_csv("cii.csv", dtype=str).set_index("label")
    assert table.loc["TOTAL ALL INDIA", "0"] == "3225597"
    assert len(table) == 39  # 36 States/UTs and three totals; titles and notes skipped


def test_example_custom_parser_mccd(tmp_path, monkeypatch):
    """Pin MCCD state columns and the 2011 spread edge cases."""
    monkeypatch.chdir(tmp_path)
    shutil.copy(FIXTURES / "mccd" / "mccd_2011.pdf", "mccd.pdf")
    r = run(
        [
            "extract",
            "mccd.pdf",
            "--recipe",
            str(EXAMPLES / "mccd" / "table4.toml"),
            "--json",
            "-q",
        ]
    )
    s = json.loads(r.stdout)
    assert r.exit_code == 0, r.output
    assert s["pages"] is None  # both pages lie between the Table 4 and Table 5 titles
    assert s["cells"]["failed_checks"] == 0 and len(s["checks_run"]) == 2
    assert s["notes"] == []  # every rule found its total
    t = pd.read_csv("mccd.csv", dtype=str)
    t = t[t.pocc == "1"].set_index(["code", "sex"])
    assert t.loc[("A40-A41", "T"), "All States (Total)"] == "39408"
    assert t.loc[("A40-A41", "T"), "Andhra Pradesh"] == "2378"
    assert t.loc[("A40-A41", "T"), "Tamil Nadu"] == "3491"


def test_photo_parser():
    """Pin lake-recipe parsing of hand-checked rows."""
    from test_bmc_lake_report import _page, _report

    parse, key = load(EXAMPLES / "lake_photo" / "recipe.toml").parse_and_key()
    assert key == ["lake", "year", "field"]
    got = {tuple(r[k] for k in key): r["value"] for r in parse(_page(_report("2026-09-28")))}
    assert got[("Tansa", "2026", "level")] and got[("", "", "report_date")] == "2026-09-28"


@pytest.mark.skipif(
    not os.environ.get("PDFEXORCIST_OCR_TESTS"),
    reason="slow OCR test; set PDFEXORCIST_OCR_TESTS=1",
)
def test_example_photo_recipe_with_ocr(tmp_path, monkeypatch):
    if len([e for e in installed_ocr() if e != "tesseract"]) < 2:
        pytest.skip("needs two OCR engines")
    monkeypatch.chdir(tmp_path)
    shutil.copy(FIXTURES / "bmc" / "2026-09-28.jpg", "lake.jpg")
    r = run(
        [
            "extract",
            "lake.jpg",
            "--recipe",
            str(EXAMPLES / "lake_photo" / "recipe.toml"),
            "--json",
            "-q",
        ]
    )
    s = json.loads(r.stdout)
    assert r.exit_code == 0 and s["cells"]["verified"] > 50
    t = pd.read_csv("lake.csv", dtype=str)
    assert {"lake", "year", "level", "useful_content_ml"} <= set(t.columns)
