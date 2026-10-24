"""ICMR AMRSN annual reports, 2017-2023."""

import json
import os
import shutil
from pathlib import Path

import pandas as pd
import pytest
from amrsn import _rows
from amrsn_cells import _cell, pct_matches
from amrsn_pictures import _clean, _model_heading, _model_tables, _row_key, picture_pages
from amrsn_pictures import parse as parse_pictures
from cli_helpers import run

from pdfexorcist.cells import BoxCell
from pdfexorcist.doctor import status

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "amrsn"
RECIPES = ROOT / "pdfexorcist" / "recipes" / "amrsn"

pytestmark = pytest.mark.usefixtures("wide_console")


def _extract(tmp: Path, fixture: str, recipe: str) -> tuple[int, dict, pd.DataFrame]:
    """(exit code, JSON summary, the CSV table) of one recipe on a copy of a fixture."""
    pdf = tmp / "doc.pdf"
    shutil.copy(FIXTURES / fixture, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPES / recipe), "--json", "-q"])
    table = pd.read_csv(tmp / "doc.csv", dtype=str, keep_default_na=False)
    return r.exit_code, json.loads(r.stdout), table


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> tuple[int, dict, pd.DataFrame]:
    return _extract(tmp_path_factory.mktemp("amrsn"), "amrsn_2017-2023.pdf", "recipe.toml")


FIELDS = {"r", "n", "pct", "rank", "value", "text", "column"}


def _cell_at(t: pd.DataFrame, page: int, label: str, col: int, entry: str = "") -> dict:
    """The fields of the one cell in that row and column."""
    rows = t[(t.page == str(page)) & t.label.str.startswith(label) & (t.col == str(col))]
    rows = rows[rows.entry == entry]
    assert len(rows) == 1, rows
    return {k: v for k, v in rows.iloc[0].items() if v and k in FIELDS}


def test_only_the_misprint_fails(result) -> None:
    """Pin a clean vote: the one failed cell is a misprint in the 2023 report."""
    _, s, t = result
    assert s["checks_run"] == ["pct_matches"]
    assert s["cells"]["failed_checks"] == 3  # r, n and pct of one cell
    # 2023 Table 1.20 prints 6767 / 108465 as 6.1%. The correct value is 6.24%.
    assert _cell_at(t, 10, "Total Enterococcus", 2) == {
        "column": "Year-2019 (%)", "r": "6767", "n": "108465", "pct": "6.1"
    }  # fmt: skip
    assert s["cells"]["unresolved"] == 0


def test_count_over_percent(result) -> None:
    """Pin "R/n" over "(%)" cells, the labels beside them and the column headings."""
    t = result[2]
    assert _cell_at(t, 1, "Amikacin", 0) == {
        "column": "Blood n=545", "r": "172", "n": "542", "pct": "31.7"
    }  # fmt: skip
    assert _cell_at(t, 3, "Colistin", 0) == {"column": "Year-2016 (S%)", "r": "0", "n": "0"}
    # 2021 Table 4.8 rules only its rows, and only its left half
    assert _cell_at(t, 5, "Mupirocin High Level", 5)["r"] == "1436"
    assert set(t[t.page == "5"].label) >= {"Trimethoprim-sulfamethoxazole", "Cefoxitin"}
    # 2023: "23069 / 99492" over "(23.19%)" and a rank under it
    assert _cell_at(t, 9, "Escherichia coli", 0) == {
        "column": "All Specimen", "r": "23069", "n": "99492", "pct": "23.19", "rank": "1"
    }  # fmt: skip
    # 2023 Table 1.20 breaks the pair after the slash: "2403/" over "45521"
    assert _cell_at(t, 10, "Total Enterococcus", 0)["n"] == "45521"
    # two tables on one page, each with its caption
    assert set(t[t.page == "11"].title.str[:9]) == {"Table 3.4", "Table 3.5"}


def test_2018_layout(result) -> None:
    """Pin a lone count over "(%)", Range(%) columns and a total wrapped onto the next line."""
    t = result[2]
    assert _cell_at(t, 2, "Ampicillin", 0) == {
        "column": "National (n=101) n= (%)", "r": "98", "n": "101", "pct": "97"
    }  # fmt: skip
    assert _cell_at(t, 2, "Ampicillin", 1)["value"] == "98"  # the Range column
    assert _cell_at(t, 2, "Ceftriaxone", 0)["n"] == "101"  # printed "101/10" over "1"


def test_gene_entries(result) -> None:
    """Pin entries named in a cell ("erm C: 72/145 (49.6%)") under the agent of their band."""
    t = result[2]
    erm_c = _cell_at(t, 4, "2 Erythromycin", 0, entry="ermC")
    assert (erm_c["r"], erm_c["n"], erm_c["pct"]) == ("72", "145", "49.6")  # 49.66, cut


def test_other_tables(result) -> None:
    """Pin tables without "count over (%)": serial-numbered lists, decimals, unruled tables."""
    t = result[2]
    assert _cell_at(t, 7, "1 Klebsiella spp.", 0) == {
        "column": "(Percentage)", "r": "159", "pct": "20.5"
    }  # fmt: skip
    gentamicin = t[(t.page == "8") & (t.label == "Gentamicin")].set_index("col").text
    assert gentamicin.to_dict() == {"0": "Gentamicin", "1": "16.7", "2": "25.0", "3": "1/1 (100)"}
    rates = t[(t.page == "6") & t.title.str.startswith("Table 9.5")].set_index("label").text
    assert "6.51" in rates.values


def test_suggest_prefers_the_text_recipe() -> None:
    """Pin recipe suggest on a text report: amrsn fits despite the report's one misprint, and
    comes before the OCR-only picture recipe."""
    r = run(["recipe", "suggest", str(FIXTURES / "amrsn_2017-2023.pdf"), "--json"])
    best = json.loads(r.stdout)["recipes"][0]
    assert (best["recipe"], best["fits"], best["failed_checks"]) == ("amrsn", True, ["pct_matches"])


def test_heading_groups_the_rows_below() -> None:
    """Pin a heading across the table as the group of the rows below it."""
    lines = [
        (5, [("Amikacin", (10, 0, 50, 10)), ("172/542", (100, 0, 140, 10))]),
        (15, [("(31.7)", (100, 10, 140, 20))]),
        (25, [("Carbapenem", (10, 20, 60, 30)), ("resistant", (65, 20, 100, 30))]),
        (35, [("Colistin", (10, 30, 50, 40)), ("8/193", (100, 30, 140, 40))]),
        (45, [("(4.1)", (100, 40, 140, 50))]),
    ]
    rows, groups = _rows(lines, [0, 3], [0, 20, 30, 50], [(100, 140)])
    assert rows == {"1.0": [0, 1], "3.0": [3, 4]}
    assert groups == {"1.0": "", "3.0": "Carbapenem resistant"}


def test_picture_pages() -> None:
    """Pin the pages of tables pasted as pictures, and none in a report's text tables."""
    assert picture_pages(str(FIXTURES / "amrsn_pictures.pdf")) == [1, 2]
    assert picture_pages(str(FIXTURES / "amrsn_2017-2023.pdf")) == []


def test_picture_caption_carried_over() -> None:
    """Pin a caption at the foot of a page naming the picture that opens the next page, and
    "RC 01" read as one label ("RC01")."""

    def right(end: float, text: str) -> BoxCell:  # a number set flush right
        return BoxCell(end - 6 * len(text), text, (end - 6 * len(text), 0.0, end, 10.0))

    pages = [
        (1, [[_box(50, "Table 4.4: Location-wise susceptible percentage")],
             [_box(50, "45 AMR surveillance network Indian Council of Medical Research")]]),
        (2, [[_box(50, "RC"), _box(70, "01"), right(212, "71"), right(312, "65")],
             [_box(50, "RC"), _box(70, "02"), right(212, "9"), right(260, "3"), right(312, "40")],
             [_box(50, "RC"), _box(70, "03"), right(260, "5"), right(312, "7")]]),
    ]  # fmt: skip
    cells = list(parse_pictures(pages))
    got = {(c["label"], c["col"]): c["value"] for c in cells}
    assert {c["table"] for c in cells} == {"4.4"}
    # most rows have blanks: each value takes the column of its right edge
    assert got == {
        ("RC01", 0): "71", ("RC01", 2): "65",
        ("RC02", 0): "9", ("RC02", 1): "3", ("RC02", 2): "40",
        ("RC03", 1): "5", ("RC03", 2): "7",
    }  # fmt: skip


def test_cell_entries() -> None:
    """Pin how one cell's text splits into entries and fields."""
    assert list(_cell(["172/542", "(31.7)"])) == [
        ("", "r", "172"),
        ("", "n", "542"),
        ("", "pct", "31.7"),
    ]
    assert list(_cell(["mecA:", "102/105", "(97.1%)"])) == [
        ("mecA", "r", "102"), ("mecA", "n", "105"), ("mecA", "pct", "97.1")
    ]  # fmt: skip
    assert list(_cell(["101/10", "1", "(100)"]))[1] == ("", "n", "101")
    assert next(iter(_cell(["vanC1/C2:", "0/97"]))) == ("vanC1/C2", "r", "0")
    assert list(_cell(["91.3-100"])) == [("", "range", "91.3-100")]
    assert list(_cell(["Np"])) == [("", "text", "Np")]
    assert list(_cell(["-"])) == [("", "value", "-")]  # "Rifampicin -": not tested


def test_pct_check() -> None:
    """Pin the check: rounded or cut digits pass, a wrong percentage fails."""
    rows = [
        ("a", "r", "72"),
        ("a", "n", "145"),
        ("a", "pct", "49.6"),  # 49.66 cut
        ("b", "r", "72"),
        ("b", "n", "145"),
        ("b", "pct", "49.7"),  # rounded
        ("c", "r", "189"),
        ("c", "n", "1438"),
        ("c", "pct", "27.7"),  # 189/1438 is 13.1 (2017 p39)
    ]
    df = pd.DataFrame(
        [{"id": i, "col": 0, "entry": "", "field": f, "value": v} for i, f, v in rows]
    )
    assert df[pct_matches(df)].id.unique().tolist() == ["c"]


@pytest.mark.skipif(
    not (
        os.environ.get("PDFEXORCIST_OCR_TESTS")
        and all(status(e).installed for e in ("doctr", "indra", "ocrmac"))
    ),
    reason="slow OCR test; set PDFEXORCIST_OCR_TESTS=1 and install doctr, indra and ocrmac",
)
def test_picture_tables(tmp_path) -> None:
    """Pin a table pasted as a picture (2020 Table 3.2), read by OCR."""
    code, _, t = _extract(tmp_path, "amrsn_pictures.pdf", "pictures.toml")
    assert code == 0
    t = t[t.title.str.startswith("Table 3.2")].set_index(["label", "column"]).value
    # columns named by the headings in the picture
    assert t[("Amikacin", "opd / n")] == "1411" and t[("Amikacin", "total / %s")] == "81"
    assert t[("Pip-taz", "ward / %s")] == "52"


def _box(x: float, text: str, y: float = 0.0) -> BoxCell:
    return BoxCell(x, text, (x, y, x + 6 * len(text), y + 10.0))


def test_picture_wrapped_caption_carried_over() -> None:
    """Pin a caption wrapped onto a second line at the foot of a page (2018 Table 4.4): its
    picture opens the next page."""
    pages = [
        (1, [[_box(50, "Table 4.4: Location-wise susceptible percentage of P. aeruginosa")],
             [_box(50, "from all samples (except faeces) across OPD, Ward and ICU.")],
             [_box(50, "45 AMR surveillance network Indian Council of Medical Research")]]),
        (2, [[_box(50, "Amikacin"), _box(200, "71"), _box(300, "65")],
             [_box(50, "Cefepime"), _box(200, "60"), _box(300, "55")]]),
    ]  # fmt: skip
    cells = list(parse_pictures(pages))
    assert {c["table"] for c in cells} == {"4.4"}
    assert cells[0]["title"].endswith("across OPD, Ward and ICU.")
    assert len(cells) == 4


def test_picture_count_over_percent() -> None:
    """Pin an "R/n" over "(%)" picture table (2018): the label centred between the two lines
    joins the row, a misread count stays out of the label, prose ends the table, and a
    single column of values is a table."""
    pages = [
        (1, [[_box(50, "Table 5.2 Susceptible pattern of Aeromonas spp isolated in 2018")],
             [_box(200, "All Specimens")],
             [_box(200, "37/56")],
             [_box(50, "Cefixime")],
             [_box(203, "(66.1)")],
             [_box(50, "Imipenem"), _box(200, "75/142"), _box(120, "1933/25/2")],
             [_box(203, "(52.8)")],
             [_box(50, "The susceptibility of these isolates was low to most antibiotics")]]),
    ]  # fmt: skip
    got = {(c["row"], c["col"], c["field"]): c["value"] for c in parse_pictures(pages)}
    assert got == {
        ("cefixime#1", 0, "value"): "37/56", ("cefixime#1", 0, "pct"): "(66.1)",
        ("imipenem#1", 0, "value"): "75/142", ("imipenem#1", 0, "pct"): "(52.8)",
    }  # fmt: skip


def test_picture_model_cells(monkeypatch) -> None:
    """Pin a model's table cells (no word boxes) keyed like the word-box engines: the caption
    from the text layer, the row by its label, the column by its index after the label."""
    import amrsn_pictures

    monkeypatch.setattr(
        amrsn_pictures, "_picture_captions", lambda page, pdf=None: [("5.2", "Table 5.2 x")]
    )
    lines = [
        [(0, "Among Aeromonas spp isolated in 2018, susceptibility was 10% overall")],
        [(0, "AMA"), (1, "All Specimens")],
        [(0, "Cefixime"), (1, "37/56 (66.1)")],
        [(0, "Norfloxacin"), (1, "*9/12 (-)")],
    ]
    got = {(c["table"], c["row"], c["col"], c["field"]): c["value"]
           for c in parse_pictures([(7, lines)])}  # fmt: skip
    assert got == {
        ("5.2", "cefixime#1", 0, "value"): "37/56", ("5.2", "cefixime#1", 0, "pct"): "(66.1)",
        ("5.2", "norfloxacin#1", 0, "value"): "*9/12", ("5.2", "norfloxacin#1", 0, "pct"): "(-)",
    }  # fmt: skip


def test_picture_caption_number_misread() -> None:
    """Pin a caption number OCR read with a letter for a digit (2019 "Tablez.2.2")."""
    from amrsn_pictures import OCR_CAPTION, _caption_number

    def num(text: str) -> str | None:
        m = OCR_CAPTION.match(text)
        return _caption_number(m[1]) if m else None

    assert num("Tablez.2.2: Comparison of susceptibility") == "2.2.2"
    assert num("TABLE 4 . 4: Location-wise") == "4.4"
    assert num("Table 1.18b: Isolate percentages") == "1.18b"
    assert num("Table shows the trend") is None
    from amrsn_pictures import CAPTION_IN_PROSE

    assert CAPTION_IN_PROSE.match("Table 4.11 depicts sample-wise susceptible trend")
    assert not CAPTION_IN_PROSE.match("Table 4.11: Sample-wise susceptible percentage")


def test_label_line_with_counts() -> None:
    """Pin a label line holding counts of its own ("RC5  0 / 0 (-)", 2024 Table 2.15): the
    counts printed above it, with no label, join its row."""
    from amrsn import _join_unlabelled

    above = ("1.0", "1", [], [(0, "", "r", "249"), (0, "", "n", "401")])
    rc5 = ("1.1", "1", ["RC5"], [(0, "", "pct", "62.1"), (1, "", "r", "0"), (1, "", "n", "0")])
    out = _join_unlabelled([above, rc5])
    assert len(out) == 1 and out[0][2] == ["RC5"]
    assert [v[:3] for v in out[0][3]] == [
        (0, "", "r"),
        (0, "", "n"),
        (0, "", "pct"),
        (1, "", "r"),
        (1, "", "n"),
    ]
    # the same field read twice: two rows, not one
    twice = ("1.0", "1", [], [(0, "", "pct", "50")])
    assert len(_join_unlabelled([twice, rc5])) == 2


def test_picture_headings_from_model(monkeypatch) -> None:
    """Pin headings printed sideways (2018 Table 2.2) taken from a model where it read the same
    label and value, and only there."""
    import amrsn_pictures

    lines = [
        [(0, "Table 2.2 Susceptibility of E. coli and Klebsiella spp from blood.")],
        [(1, "Amikacin"), (2, "Cefotax")],
        [(0, "*E. coli*"), (1, "82"), (2, "19")],
        [(0, "*Klebsiella*"), (1, "45"), (2, "21")],
    ]
    monkeypatch.setattr(amrsn_pictures, "_model_pages", lambda pdf, engine: iter([(1, lines)]))
    monkeypatch.setattr(
        amrsn_pictures, "_picture_captions", lambda page, pdf=None: [("2.2", "Table 2.2")]
    )
    cells = pd.DataFrame({
        "page": [1, 1, 1], "table": ["2.2"] * 3, "row": ["ecoli#1", "ecoli#1", "klebsiella#1"],
        "col": [0, 1, 1], "value": ["82", "19", "22"], "column": ["", "s", ""],
        "field": ["value"] * 3, "status": ["verified"] * 3,
    })  # fmt: skip
    out = amrsn_pictures.name_columns(cells, "x.pdf")
    assert out.column.tolist() == ["amikacin", "cefotax", ""]  # 22 is not the model's 21


def test_group_headings() -> None:
    """Pin a heading over blocks of columns (2024 Table 6.2): every column of a block takes it."""
    from amrsn import _headers

    cols = [(100.0 + 40 * i, 130.0 + 40 * i) for i in range(8)]
    group = [("S.", (160.0, 0, 170.0, 5)), ("aureus", (172.0, 0, 200.0, 5)),
             ("MRSA", (330.0, 0, 360.0, 5))]  # fmt: skip
    setting = [
        (t, (100.0 + 40 * i, 10, 125.0 + 40 * i, 15))
        for i, t in enumerate(["Total", "OPD", "Ward", "ICU"] * 2)
    ]
    got = _headers([(0.0, group), (10.0, setting)], cols)
    assert got[0] == "S. aureus Total" and got[3] == "S. aureus ICU" and got[4] == "MRSA Total"


def test_wrapped_names_are_not_group_headings() -> None:
    """Pin the first halves of wrapped names ("Piperacillin-" over one column, 2024 Table 2.15):
    they head their own column only."""
    from amrsn import _headers

    cols = [(100.0 + 40 * i, 130.0 + 40 * i) for i in range(12)]
    first = [("Piperacillin-", (100.0, 0, 140.0, 5)), ("Trimethoprim-", (460.0, 0, 500.0, 5))]
    got = _headers([(0.0, first)], cols)
    assert got.get(0) == "Piperacillin-" and got.get(9) == "Trimethoprim-" and 1 not in got


def test_centre_rows_key_alike_across_engines() -> None:
    # 2022 p89: doctr, Indra and Apple Vision read RC01 and RC04 with bar marks and fused values
    assert {_row_key(x) for x in ["RC01", "RCC01", "RC 01 O", "RCO01"]} == {"rc01"}
    assert _row_key("RCC04") == "rc04"
    assert _row_key("RC113") == "rc11"
    assert _row_key("Overrall") == "overall"
    assert _clean(("1", "RC14 1479D 773_ 89.9-", None))[1] == "RC14 1479 773 89.9-"


def test_model_table_spans_blank_centres_and_spanning_headings() -> None:
    # OXR, 2022 p89: "RC 02" has no isolates; "Pip-taz" spans its n and %S columns
    lines = [
        [(0, ""), (1.5, "Pip-taz"), (3.5, "Cephazolin")],
        [(0, ""), (1, "n"), (2, "%S"), (3, "n"), (4, "%S")],
        [(0, "RC 01"), (1, "699"), (2, "54"), (3, "687"), (4, "14")],
        [(0, "RC 02"), (1, ""), (2, ""), (3, ""), (4, "")],
        [(0, "Overall"), (1, "11723"), (2, "56"), (3, "4794"), (4, "20")],
    ]
    tables = _model_tables(lines)
    assert len(tables) == 1 and len(tables[0][1]) == 2
    maps = [dict(h) for h in tables[0][0]]
    assert [_model_heading(maps, j) for j in (1, 2, 3)] == [
        "Pip-taz / n",
        "Pip-taz / %S",
        "Cephazolin / n",
    ]


def test_model_columns_skip_data_bar_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    # OXR, 2021 p73: each data bar is an empty column between n and %S ("324", "", "24")
    import amrsn_pictures

    monkeypatch.setattr(
        amrsn_pictures, "_picture_captions", lambda p, pdf=None: [("2.14", "Table 2.14")]
    )
    lines = [
        [(0, ""), (1, "n"), (2.5, "%S"), (4, "n"), (5.5, "%S")],
        [(0, "RC 01"), (1, "324"), (2, ""), (3, "24"), (4, "324"), (5, ""), (6, "12")],
        [(0, "Overall"), (1, "3403"), (2, ""), (3, "41"), (4, "1120"), (5, ""), (6, "18")],
    ]
    cells = list(amrsn_pictures._model_page(73, lines))
    assert [(c["row"], c["col"], c["value"]) for c in cells[:4]] == [
        ("rc01#1", 0, "324"), ("rc01#1", 1, "24"), ("rc01#1", 2, "324"), ("rc01#1", 3, "12"),
    ]  # fmt: skip
    assert [c["column"] for c in cells[:2]] == ["n", "%s"]


def test_model_table_drifting_under_blank_heading_is_skipped() -> None:
    # OXR, 2022 p90: "352", "", "27" in one row, "214", "51" in another; heading "n", "%S", "", "n"
    from amrsn_pictures import _drifts

    bottom = [(0.0, ""), (1.0, "n"), (2.0, "%S"), (3.0, ""), (4.0, "n"), (5.0, "%S")]
    good = [[(0, "RC 01"), (1, "352"), (2, "27"), (3, ""), (4, "316"), (5, "11")]]
    drift = [[(0, "RC 04"), (1, "214"), (2, ""), (3, "57"), (4, "0"), (5, "")]]
    assert not _drifts(bottom, good)
    assert _drifts(bottom, drift)


def test_wrapped_range_joins_its_first_half() -> None:
    # 2018 p75: "87.7-" on the count line, "99.8" under it on the "(%)" line
    from amrsn_pictures import _close_ranges, _is_val

    above = [("3564/3646", (100.0, 0, 140.0, 8)), ("87.7-", (160.0, 0, 185.0, 8))]
    rest = _close_ranges(
        above, [("(97.8)", (105.0, 10, 135.0, 18)), ("99.8", (162.0, 10, 182.0, 18))]
    )
    assert [t for t, _ in above] == ["3564/3646", "87.7-99.8"]
    assert [t for t, _ in rest] == ["(97.8)"]
    assert _is_val("96.9-100") and _is_val("98.3")


def test_staggered_heading_lines_name_every_column():
    import amrsn_tables

    cells = {(0, 1): ["Amphotericin"], (1, 2): ["Fluconazole"], (2, 1): ["B"],
             (3, 0): ["CSVC-7.2"], (3, 1): ["0.5"], (3, 2): ["0.12"]}  # fmt: skip
    recs = {r["col"]: r["column"] for r in amrsn_tables._emit(62, "t", "x", cells) if r["label"]}
    assert recs == {0: "", 1: "Amphotericin B", 2: "Fluconazole"}


def test_a_heading_row_of_years_names_its_columns():
    import amrsn_tables

    cells = {(0, 0): ["Indicator"], (0, 1): ["2021"], (0, 2): ["2022"],
             (1, 0): ["Patient days"], (1, 1): ["4,72,959"], (1, 2): ["3,12,310"]}  # fmt: skip
    recs = {r["col"]: r["column"] for r in amrsn_tables._emit(1, "t", "x", cells)}
    assert recs == {0: "Indicator", 1: "2021", 2: "2022"}


def test_picture_groups_of_repeated_rows(monkeypatch) -> None:
    """Pin 2020 Table 2.10 (a picture captioned "Table 4." under the report's "Table 2.10"):
    a group printed once beside its rows keys them, so a row one engine misses shifts no other
    group, and "97.1 (68/70)" is one cell, not part of the label."""
    import amrsn_pictures

    monkeypatch.setattr(
        amrsn_pictures, "_picture_captions", lambda page, pdf=None: [("2.10", "Table 2.10: x")]
    )
    lines = [
        [(0, ""), (1, ""), (2, "Total (n = 70)"), (3, "C. krusei (n = 13)")],
        [(0, "Essential agreement (%)"), (1, "Fluconazole"), (2, "97.1 (68/70)"), (3, "100")],
        [(0, ""), (1, "Voriconazole"), (2, "92.8 (65/70)"), (3, "84.6")],
        [(0, "Major errors (n)"), (1, "Fluconazole"), (2, "0"), (3, "0")],
        [(0, ""), (1, "Voriconazole"), (2, "0"), (3, "1")],
    ]
    got = {(c["row"], c["col"]): c["value"] for c in parse_pictures([(65, lines)])}
    assert got == {
        ("essentialagreement:fluconazole#1", 0): "97.1(68/70)",
        ("essentialagreement:fluconazole#1", 1): "100",
        ("essentialagreement:voriconazole#1", 0): "92.8(65/70)",
        ("essentialagreement:voriconazole#1", 1): "84.6",
        ("majorerrorsn:fluconazole#1", 0): "0", ("majorerrorsn:fluconazole#1", 1): "0",
        ("majorerrorsn:voriconazole#1", 0): "0", ("majorerrorsn:voriconazole#1", 1): "1",
    }  # fmt: skip
    box = list(parse_pictures([(65, [
        [_box(50, "Table 2.10: Result of direct-antifungal susceptibility in yeast species")],
        [_box(50, "Table4. Resultofdirect-antifungalsusceptibility in yeast species")],
        [_box(50, "Fluconazole"), _box(200, "97.1"), _box(230, "(68/70)"), _box(300, "92.8")],
        [_box(50, "Voriconazole"), _box(200, "92.8"), _box(230, "(65/70)"), _box(300, "85.7")],
    ])]))  # fmt: skip
    assert {c["table"] for c in box} == {"2.10"}
    assert {c["value"] for c in box if c["col"] == 0} == {"97.1(68/70)", "92.8(65/70)"}


def test_picture_model_percent_sign(monkeypatch) -> None:
    """Pin 2018 Table 6.1: "(61.4%)" is the (%) under a count, and a model's "4467/7274/(61.4%)"
    is the count and its (%)."""
    import amrsn_pictures

    monkeypatch.setattr(
        amrsn_pictures, "_picture_captions", lambda page, pdf=None: [("6.1", "Table 6.1 x")]
    )
    lines = [
        [(0, "Among S. aureus isolated in 2018, susceptibility was 61% to cefoxitin")],
        [(0, "AMA"), (1, "Sau n=7939")],
        [(0, "Cefoxitin"), (1, "4467/7274/(61.4%)")],
        [(0, "Linezolid"), (1, "7484/7577/(98.8%)")],
    ]
    got = {(c["row"], c["field"]): c["value"] for c in parse_pictures([(72, lines)])}
    assert got == {
        ("cefoxitin#1", "value"): "4467/7274", ("cefoxitin#1", "pct"): "(61.4%)",
        ("linezolid#1", "value"): "7484/7577", ("linezolid#1", "pct"): "(98.8%)",
    }  # fmt: skip
