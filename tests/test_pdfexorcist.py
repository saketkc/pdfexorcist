"""Voting and extraction."""

from pathlib import Path

import pandas as pd
import pymupdf

from pdfexorcist import extract, parse_rows, vote

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


def test_pdfium_brackets_are_rejoined():
    from pdfexorcist.extractors import _join_parens

    words = [
        (10, 13, 20, "(", 10),
        (13, 18, 20, "5", 10),
        (18, 21, 20, ")", 10),
        (40, 60, 20, "State", 10),
    ]
    assert [w[3] for w in _join_parens(words)] == ["(5)", "State"]


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
