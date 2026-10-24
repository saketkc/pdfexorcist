"""Voting and extraction."""

import sys
import types
from pathlib import Path

import pandas as pd
import pymupdf
import pytest
from cli_helpers import make_pdf

from pdfexorcist import EXTRACTORS, extract, parse_rows, vote
from pdfexorcist._ocr_engines import _indra
from pdfexorcist._registry import lab_families, one_per_lab

ROWS = [("Tamil Nadu", "12.3", "(45.6)", "*"), ("Kerala", "1,020", "7", "8.0")]


def test_vote_needs_quorum_and_no_tie():
    r = pd.DataFrame(
        [
            ("a", 1, "1.0"),
            ("b", 1, "1.0"),
            ("c", 1, "7.0"),  # 2 of 3 agree
            ("a", 2, "5"),
            ("b", 2, "6"),
            ("c", 2, "7"),  # no majority
        ],
        columns=["method", "row", "value"],
    ).assign(page=1, col=0)
    out = vote(r, min_agree=2).set_index("row")
    assert out.loc[1, "value"] == "1.0" and out.loc[1, "dissent"] == "c=7.0"
    assert out.loc[2, "status"] == "unresolved"


def test_rows_key():
    page = (1, [[(0, "Tam il Nadu"), (50, "12.3 (45.6)")], [(0, "notes only")]])
    got = list(parse_rows([page]))
    assert [(g["row"], g["col"], g["value"]) for g in got] == [
        ("tamilnadu#1", 0, "12.3"),
        ("tamilnadu#1", 1, "(45.6)"),
    ]


def test_end_to_end(tmp_path):
    pdf = tmp_path / "t.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    for i, row in enumerate(ROWS):
        for x, text in zip((50, 250, 330, 410), row, strict=True):
            page.insert_text((x, 100 + 20 * i), text)
    doc.save(pdf)
    res = extract(pdf, ["pdftotext", "pdfplumber", "pymupdf"], min_agree=3)
    ok = res[res.status == "verified"]
    got = ok.groupby("label")["value"].apply(tuple).to_dict()
    assert got == {r[0]: r[1:] for r in ROWS}


def test_checks_flag_failing_groups():
    from pdfexorcist import check, total_check, validate

    df = pd.DataFrame(
        {
            "cause": ["a"] * 3 + ["b"] * 3,
            "sex": ["M", "F", "T"] * 2,
            "value": ["1", "2", "3", "1", "2", "9"],  # b: T != M + F
        }
    )

    @check("no nines")
    def no_nines(d):
        return d.value == "9"

    out = validate(df, [total_check("sex", "T", ["M", "F"], by=["cause"]), no_nines])
    assert (out.failed[:3] == "").all()
    assert out.failed[5] == "T == sum of sex; no nines"
    assert out.failed[3] == "T == sum of sex"
    loose = validate(df, [total_check("sex", "T", ["M", "F"], by=["cause"], op=">=")])
    assert (loose.failed == "").all()


def test_unopposed():
    from pdfexorcist import total_check, validate

    r = pd.DataFrame(
        [("a", 1, "5"), ("b", 1, "5"), ("a", 2, "5"), ("b", 2, "6")],
        columns=["method", "row", "value"],
    ).assign(page=1, col=0)
    out = vote(r, min_agree=3, min_unopposed=2).set_index("row")
    assert out.loc[1, "status"] == "verified" and out.loc[2, "status"] == "unresolved"

    df = pd.DataFrame({"sex": ["M", "T"], "value": ["1", "9"]})  # F missing: not judged
    assert (validate(df, [total_check("sex", "T", ["M", "F"])]).failed == "").all()


def test_family_vote():
    from pdfexorcist import parse_by_columns
    from pdfexorcist.rows import group_words

    # three Tesseract runs agreeing are one family: not enough against nothing else
    r = pd.DataFrame(
        [
            ("t1", "5"),
            ("t2", "5"),
            ("t3", "5"),
            ("chandra", "5"),
            ("t1", "7"),
            ("t2", "7"),
        ],
        columns=["method", "value"],
    ).assign(page=1, col=0, row=[1, 1, 1, 1, 2, 2])
    out = vote(r, families={"tess": ["t1", "t2", "t3"]}).set_index("row")
    assert out.loc[1, "status"] == "verified" and out.loc[2, "status"] == "unresolved"

    # a missing value (OCR dropped a "0") does not shift the next one
    lines = [
        [(0, "Goa"), (50, "1"), (100, "2"), (150, "3")],
        [(0, "Bihar"), (50, "4"), (150, "6")],
        [(0, "Delhi"), (50, "7"), (100, "8"), (150, "9")],
    ]
    got = {(c["row"], c["col"]): c["value"] for c in parse_by_columns([(1, lines)])}
    assert got[("bihar#1", 2)] == "6" and ("bihar#1", 1) not in got

    # a value 2.7 pt off the baseline stays on its row
    words = [
        (0, 20, 100, "Goa", 90),
        (50, 60, 102.7, "532.2", 92.7),
        (80, 90, 100, "16.3", 90),
    ]
    assert [t for _, t in group_words(words)[0]] == ["Goa", "532.2", "16.3"]


def test_lab_votes_once(states_pdf, monkeypatch):
    """Pin LABS: when chandra and indra read the same wrong value, they count as one vote."""

    def misread(pdf):
        for page, lines in EXTRACTORS["pdfplumber"](pdf):
            yield page, [[(x, "1,021" if t == "1,020" else t) for x, t in ln] for ln in lines]

    monkeypatch.setitem(EXTRACTORS, "chandra", misread)
    monkeypatch.setitem(EXTRACTORS, "indra", misread)
    res = extract(states_pdf, methods=["pdfplumber", "pymupdf", "chandra", "indra"])
    cell = res[res.votes.str.contains("1,021")].iloc[0]
    assert (cell.value, cell.status) == ("1,020", "verified")


def test_ocr_runs_one_engine_per_lab():
    assert one_per_lab(["tesseract", "chandra", "indra"]) == ["tesseract", "indra"]
    given = {"pdfminer": ["pdfplumber", "camelot"]}
    assert lab_families(["chandra", "indra", "pdfplumber"], given) == {
        "datalab": ["indra", "chandra"],
        **given,
    }


@pytest.mark.parametrize("cuda", [True, False])
def test_indra_uses_cuda_when_onnxruntime_has_it(monkeypatch, cuda):
    providers = (
        ["CUDAExecutionProvider", "CPUExecutionProvider"] if cuda else ["CPUExecutionProvider"]
    )
    loaded = {}
    monkeypatch.setitem(
        sys.modules, "onnxruntime", types.SimpleNamespace(get_available_providers=lambda: providers)
    )
    monkeypatch.setitem(
        sys.modules,
        "indra_ocr",
        types.SimpleNamespace(load=lambda **kw: types.SimpleNamespace(ocr=loaded.update(kw))),
    )
    _indra.__wrapped__()
    assert loaded["providers"] == (providers if cuda else None)


def test_fake_bold():
    from pdfexorcist.rows import group_words, is_value

    words = [
        (0, 20, 100, "Goa", 90),
        (0.3, 20.3, 100.2, "Goa", 90.2),
        (50, 60, 100, "17", 90),
        (50.2, 60.2, 100, "17", 90),
    ]
    assert [t for _, t in group_words(words)[0]] == ["Goa", "17"]
    assert is_value("N.A.")
    assert is_value("2E+05")  # Excel's display of a number too wide for its cell (MCCD 2013)


def test_value_with_uncertainty():
    from pdfexorcist._text_engines import _layout_lines
    from pdfexorcist.rows import group_words, is_value

    for t in ["9.20±0.40", "1489±10", "-1.2±0.3", "12+/-3", "1,234.5±6.7%"]:
        assert is_value(t), t
    for t in ["±", "1±", "±2", "a±b"]:
        assert not is_value(t), t
    # narrow columns 3 pt apart (IFCT 2017) hold two values
    words = [
        (0, 20, 100, "O006", 90),
        (30, 60, 100, "0.041±0.031", 90),
        (63, 93, 100, "0.001±0.000", 90),
    ]
    assert [t for _, t in group_words(words)[0]] == ["O006", "0.041±0.031", "0.001±0.000"]
    line = _layout_lines("M004  Egg   1.31±0.11 0.04±0.01")[0]
    assert [t for _, t in line] == ["M004", "Egg", "1.31±0.11", "0.04±0.01"]


def test_missing_parts_can_fail():
    from pdfexorcist import total_check, validate

    df = pd.DataFrame({"state": ["All", "A"], "value": ["10", "4"]})  # state B lost upstream
    skip = total_check("state", "All", ["A", "B"])
    fail = total_check("state", "All", ["A", "B"], missing="fail")
    assert (validate(df, [skip]).failed == "").all()
    assert (validate(df, [fail]).failed != "").all()


def test_markdown_pipes():
    from pdfexorcist.extractors import _parse_markdown

    rows = _parse_markdown(
        "Report on 26-08-2026\n| A | 2026 | 1.5 |\n| :--- | :--- | :--- |\nB | 2025 | 2.5 |\n"
    )
    assert rows == [
        [(0, "Report on 26-08-2026")],
        [(0, "A"), (1, "2026"), (2, "1.5")],
        [(0, "B"), (1, "2025"), (2, "2.5")],
    ]


def test_deskew_levels_a_tilted_photo():
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw

    from pdfexorcist.extractors import _deskew

    img = Image.new("RGB", (900, 700), "white")
    draw = ImageDraw.Draw(img)
    for y in range(100, 650, 40):  # table rules
        draw.line((50, y, 850, y), fill="black", width=2)
    tilted = img.rotate(3, expand=True, fillcolor="white")

    def tilt(im):
        edges = cv2.Canny(cv2.cvtColor(np.array(im), cv2.COLOR_RGB2GRAY), 50, 150)
        lines = cv2.HoughLinesP(
            edges, 1, np.pi / 1800, 200, minLineLength=im.width // 3, maxLineGap=10
        )
        return np.median(
            [np.degrees(np.arctan2(y2 - y1, x2 - x1)) for x1, y1, x2, y2 in lines.reshape(-1, 4)]
        )

    assert abs(tilt(tilted) + 3) < 0.3
    assert abs(tilt(_deskew(tilted))) < 0.3
    assert _deskew(img) is img  # a level page is left alone


def test_markdown_text():
    from pdfexorcist.extractors import _parse_markdown

    assert _parse_markdown("(M.S.L.) (M.S.L.) 2023 602.84 205775 90.63") == [
        [
            (0, "(M.S.L.) (M.S.L.)"),
            (1, "2023"),
            (2, "602.84"),
            (3, "205775"),
            (4, "90.63"),
        ]
    ]


def test_page_cuts(tmp_path):
    import hashlib
    from pathlib import Path

    from pdfexorcist.vote import _pages

    src = Path(__file__).parent / "fixtures" / "mccd" / "mccd_2011.pdf"
    (tmp_path / "a").mkdir(), (tmp_path / "b").mkdir()
    a, b = _pages(src, [1], tmp_path / "a"), _pages(src, [1], tmp_path / "b")
    assert hashlib.md5(a.read_bytes()).digest() == hashlib.md5(b.read_bytes()).digest()


def test_vision_process():
    import io
    import json
    import os
    import subprocess
    import sys

    import pytest

    if not os.environ.get("PDFEXORCIST_OCR_TESTS"):
        pytest.skip("slow OCR test; set PDFEXORCIST_OCR_TESTS=1")
    pytest.importorskip("ocrmac")
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (400, 120), "white")
    ImageDraw.Draw(img).text((20, 40), "TOTAL 1447363", fill="black", font_size=36)
    png = io.BytesIO()
    img.save(png, format="PNG")
    page = len(png.getvalue()).to_bytes(4, "big") + png.getvalue()
    out = subprocess.run(  # two pages through one worker: one JSON line each
        [sys.executable, "-m", "pdfexorcist._vision_worker"],
        input=page * 2,
        capture_output=True,
        check=True,
    ).stdout
    lines = out.splitlines()
    assert len(lines) == 2
    assert all(any("1447363" in t for t, _, _ in json.loads(line)) for line in lines)


def test_fit_boxes(tmp_path):
    import pymupdf

    from pdfexorcist.vote import fit_page_boxes

    src = tmp_path / "off.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=200, height=300)
        page.insert_text((50, -2), "TOPTEXT", fontsize=10)  # above the page
        page.insert_text((50, 310), "BOTTOMTEXT", fontsize=10)  # below it
        page.insert_text((205, 150), "RIGHTTEXT", fontsize=10)  # right of it
        doc.save(src)
    out = fit_page_boxes(src, tmp_path / "fit")
    with pymupdf.open(out) as doc:
        words = {w[4] for w in doc[0].get_text("words")}  # MuPDF clips to the box
    assert {"TOPTEXT", "BOTTOMTEXT", "RIGHTTEXT"} <= words


def test_empty_column():
    r = pd.DataFrame(
        [("a", 1, "1.0", None), ("b", 1, "1.0", None), ("c", 1, "1.0", None)],
        columns=["method", "row", "value", "geo"],
    ).assign(page=1, col=0)
    out = vote(r, min_agree=2)
    assert out.loc[0, "value"] == "1.0" and out.loc[0, "geo"] is None


def test_unfitted_boxes(tmp_path):
    import pymupdf

    from pdfexorcist import extract

    src = tmp_path / "facing.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=300, height=200)
        page.insert_text((20, 50), "Kerala 12.5 7.0 3.1", fontsize=10)
        page.insert_text((-250, 120), "Bihar 99.9 88.8 77.7", fontsize=10)  # the facing page
        doc.save(src)
    grown = extract(src, methods=["pdfplumber", "pymupdf", "pdfium"], min_agree=2)
    kept = extract(src, methods=["pdfplumber", "pymupdf", "pdfium"], min_agree=2, fit_boxes=False)
    assert "99.9" in set(grown.value) and "99.9" not in set(kept.value)
    assert "12.5" in set(kept.value)


def test_decimal_total():
    from pdfexorcist import total_check

    df = pd.DataFrame({"row": ["n"] * 3, "col": [0, 1, 2], "value": ["65.3", "-4.0", "61.3"]})
    assert not total_check("col", 2, [0, 1], by=["row"])(df).any()  # 65.3 - 4.0 is 61.29999...
    df.loc[2, "value"] = "61.4"
    assert total_check("col", 2, [0, 1], by=["row"])(df).all()  # a real 0.1 gap still fails


def test_a_rotated_scan_is_a_scan(tmp_path):
    import pymupdf
    from PIL import Image

    from pdfexorcist._ocr_engines import _image_dpi
    from pdfexorcist.pages import page_kinds

    png = tmp_path / "scan.png"
    Image.new("RGB", (1100, 780), "white").save(png)  # landscape pixels, 100 dpi on A4
    doc = pymupdf.open()
    page = doc.new_page(width=792, height=561.6)
    page.insert_image(page.rect, filename=png)
    page.set_rotation(270)  # shown portrait, as scanners save it
    doc.save(tmp_path / "scan.pdf")
    assert page_kinds(tmp_path / "scan.pdf")[0]["scan"]
    with pymupdf.open(tmp_path / "scan.pdf") as d:
        assert _image_dpi(d[0]) == 100


def test_parallel_vote():
    """Pin identical votes from worker-process reads."""
    pdf = Path(__file__).parent / "fixtures" / "synthetic" / "cleaning.pdf"
    one, two = extract(pdf), extract(pdf, jobs=3)
    pd.testing.assert_frame_equal(one, two)
    assert (one.status == "verified").sum() > 0


def test_parallel_error(tmp_path):
    pdf = Path(__file__).parent / "fixtures" / "synthetic" / "cleaning.pdf"
    events = []
    res = extract(
        pdf,
        methods=["pdfplumber", "pymupdf", "pdfium", "no_such_engine"],
        jobs=2,
        on_engine=lambda n, e, d: events.append((n, e)),
    )
    assert ("no_such_engine", "skipped") in events and (res.status == "verified").any()


def test_camelot_distinct():
    from types import SimpleNamespace

    from pdfexorcist._text_engines import _distinct

    small, big, beside = (
        SimpleNamespace(_bbox=b) for b in [(10, 10, 50, 50), (0, 0, 60, 60), (70, 0, 90, 20)]
    )
    assert _distinct([small, big, beside]) == [big, beside]  # reading order kept


@pytest.mark.parametrize("engine", ["pypdf", "pdfjs"])
def test_independent_text_engine(engine):
    from pdfexorcist.doctor import status
    from pdfexorcist.extractors import EXTRACTORS

    if not status(engine).installed:
        pytest.skip(f"{engine} not installed")
    pdf = Path(__file__).parent / "fixtures" / "nfhs5_state" / "nfhs5_chandigarh_p3-6.pdf"

    def values(name):
        return {
            (r["page"], r["row"], r["col"]): r["value"] for r in parse_rows(EXTRACTORS[name](pdf))
        }

    ref, got = values("pymupdf"), values(engine)
    assert sum(got.get(k) == v for k, v in ref.items()) >= 0.99 * len(ref)


@pytest.mark.parametrize("rot", [90, 180, 270])
def test_sideways_table(tmp_path, rot):
    """A table printed turned on an upright page, with a running head across the margin."""
    pdf = tmp_path / "t.pdf"
    doc = pymupdf.open(make_pdf(tmp_path / "upright.pdf", [ROWS]))
    page = doc[0]
    page.insert_text((49, 104), "Survey 2018", rotate=90)  # across the table, box over a label
    page.set_rotation(rot)  # turn the content itself, no /Rotate, as InDesign does
    page.remove_rotation()
    doc.save(pdf)
    res = extract(pdf, ["pdftotext", "pdfplumber", "pymupdf", "pdfium"], min_agree=4)
    ok = res[res.status == "verified"]
    assert ok.groupby("label")["value"].apply(tuple).to_dict() == {r[0]: r[1:] for r in ROWS}


def test_two_sideways_pages(tmp_path):
    """Every sideways page is turned; clearing one page's margin text must not break the next."""
    from pdfexorcist._upright import upright_pages

    pdf = Path(__file__).parent / "fixtures" / "upright" / "tb_report_2024_p185-186.pdf"
    with pymupdf.open(upright_pages(pdf, tmp_path)) as out:
        assert len(out) == 2
        assert all(page.rect.width > page.rect.height for page in out)
        assert all("States/UTs" in page.get_text() for page in out)


def test_pymupdf_boxes_match_pdfplumber():
    """PyMuPDF's words line up with pdfplumber's on a page whose CropBox and MediaBox differ."""
    import pdfplumber

    from pdfexorcist.cells import token_boxes

    pdf = Path(__file__).parent / "fixtures" / "rhs" / "rhs_2021-22_t12-17-76.pdf"
    with pdfplumber.open(pdf) as doc:
        tops = {w["text"]: (w["x0"], w["top"]) for w in doc.pages[0].extract_words()}
    lines = next(lines for page, lines in EXTRACTORS["pymupdf"](pdf) if page == 1)
    gaps = [
        max(abs(tops[t][0] - b[0]), abs(tops[t][1] - b[1]))
        for line in lines
        for _, t, b in token_boxes(line)
        if b is not None and t in tops
    ]
    assert len(gaps) > 100 and sorted(gaps)[len(gaps) // 2] < 3  # was 8 pt across, 25 pt down


def _keys(lines: list, **kw) -> list[tuple[str, str]]:
    return [(r["row"], r["value"]) for r in parse_rows([(1, lines)], **kw) if r["col"] == 0]


def test_side_labels_do_not_key_rows() -> None:
    """A side label on its own line, in a first cell, or joined (pdftotext) keys nothing."""
    lines = [
        [(30.0, "Percentage of cases"), (90.0, "1.0")],
        [(5.0, "Rural")],
        [(30.0, "Female Sterilisation"), (90.0, "2.0")],
        [(30.0, "Percentage of cases"), (90.0, "3.0")],
        [(5.0, "Urban"), (30.0, "Female Sterilisation"), (90.0, "4.0")],
        [(17.0, "Urban Percentage of cases"), (90.0, "5.0")],
        [(5.0, "Private hospital:"), (30.0, "All"), (90.0, "6.0")],  # a heading stays
        [(5.0, "51."), (30.0, "Institutional births"), (90.0, "7.0")],  # a serial stays
    ]
    assert _keys(lines) == [
        ("percentageofcases#1", "1.0"),
        ("femalesterilisation#1", "2.0"),
        ("percentageofcases#2", "3.0"),
        ("femalesterilisation#2", "4.0"),
        ("percentageofcases#3", "5.0"),
        ("privatehospitalall#1", "6.0"),
        ("51institutionalbirths#1", "7.0"),
    ]


def test_wrapped_label_takes_its_values() -> None:
    """Pin values between a wrapped label's lines; headings and side labels lend no label."""
    lines = [
        [(50.0, "Male"), (70.0, "Female")],
        [(50.0, "1"), (70.0, "2")],
        [(30.0, "Public hospitals"), (90.0, "327")],
        [(30.0, "Charitable/NGO run")],
        [(90.0, "589")],
        [(30.0, "hospitals")],
        [(5.0, "Rural +")],
        [(90.0, "8")],
    ]
    assert [k for k, _ in _keys(lines)] == ["#1", "publichospitals#1", "charitablengorun#1", "#2"]


def test_fit_width_gives_back_a_label_number() -> None:
    """ "below 20" keeps its 20 with fit_width; a wider table's last row keeps its values."""
    lines = [
        [(10.0, "below"), (40.0, "20"), (60.0, "98"), (80.0, "85")],
        [(10.0, "20-24"), (60.0, "99"), (80.0, "86")],
    ]
    assert [r["row"] for r in parse_rows([(1, lines)])][:3] == ["below#1"] * 3
    assert _keys(lines, fit_width=True)[0] == ("below20#1", "98")
    wide = [[(10.0, t), (40.0, "1"), (60.0, "2"), (80.0, "3")] for t in ("a", "b")]
    wide.append([(10.0, "c"), (60.0, "4")])
    assert _keys(wide, fit_width=True) == [("a#1", "1"), ("b#1", "1"), ("c#1", "4")]


def test_vision_back_to_accurate(monkeypatch):
    """Pin that one empty accurate reading does not leave later pages to fast mode."""
    import pytest

    pytest.importorskip("ocrmac")
    from pdfexorcist import _vision_worker as vw

    calls: list[str] = []
    accurate = iter([[], [], [], [("A", 1.0, (0, 0, 1, 1))]])  # page 1: 3 empty tries; page 2: text

    class FakeOCR:
        def __init__(self, img, recognition_level):
            self.level = recognition_level

        def recognize(self):
            calls.append(self.level)
            return next(accurate) if self.level == "accurate" else [("a", 0.5, (0, 0, 1, 1))]

    monkeypatch.setattr(vw.ocrmac, "OCR", FakeOCR)
    monkeypatch.setattr(vw.time, "sleep", lambda s: None)
    found, fast = vw.read(None)
    assert found[0][0] == "a" and fast  # fell back to fast
    found, fast = vw.read(None, fast)
    assert found[0][0] == "A" and not fast  # one accurate try, and it read: accurate again
    assert calls == ["accurate"] * 3 + ["fast", "accurate"]


def test_html_rows_rowspan_keeps_columns() -> None:
    # OXR, 2018 AMRSN Table 6.2: "AMA" spans three heading rows; "Total" is the first value column
    from pdfexorcist._vlm_engines import _HtmlRows

    html = (
        '<table><tr><td rowspan="2">AMA</td><td colspan="2">S. aureus</td></tr>'
        "<tr><td>Total</td><td>OPD</td></tr><tr><td>Cefoxitin</td><td>1/2</td><td>3/4</td></tr></table>"
    )
    assert _HtmlRows.parse(html) == [
        [(0, "AMA"), (1.5, "S. aureus")],
        [(1, "Total"), (2, "OPD")],
        [(0, "Cefoxitin"), (1, "1/2"), (2, "3/4")],
    ]


def test_sideways_heading_is_one_word_and_kept(tmp_path):
    import pymupdf

    from pdfexorcist._slanted import drop_slanted
    from pdfexorcist._text_engines import pdfplumber_

    pdf = tmp_path / "side.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((100, 200), "TEM", rotate=90)  # a gene heading printed bottom to top
    page.insert_text((150, 300), "RC2 78%")
    doc.save(pdf)
    assert drop_slanted(pdf, tmp_path / "level") == pdf  # nothing to drop
    words = [t for _, lines in pdfplumber_(pdf) for line in lines for _, t in line]
    assert "TEM" in words
