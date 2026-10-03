"""show and compare views."""

import json
import os
import pickle
import re
from importlib.util import find_spec
from pathlib import Path

import pandas as pd
import pymupdf
import pytest
from typer.testing import CliRunner

from pdfexorcist import extract, group_words, parse_rows, recipe
from pdfexorcist.cells import BoxCell, cell_box
from pdfexorcist.cli import app
from pdfexorcist.readings import locate
from pdfexorcist.show import SHOW_DPI, inspect_page
from pdfexorcist.show_html import render_html
from pdfexorcist.show_png import write_png

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures"
CII = FIXTURES / "cii" / "cii_2021_1A.1_p43.pdf"
MCCD = FIXTURES / "mccd" / "mccd_2011.pdf"
BMC = FIXTURES / "bmc" / "2026-07-28.jpg"
runner = CliRunner()


def _view(src: Path, recipe_file: Path, page: int = 1, **kw):
    r = recipe.load(recipe_file)
    parse, key = r.parse_and_key()
    return inspect_page(
        src,
        page,
        parse=parse,
        key=key,
        normalize=r.normalizer(),
        checks=r.check_functions(),
        postprocess=r.postprocess_function(),
        columns=r.columns or "col",
        rows=r.rows,
        **kw,
    )


def _data(html: str) -> dict:
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.DOTALL)
    assert m
    return json.loads(m.group(1))


@pytest.fixture(scope="module")
def cii():
    return _view(CII, ROOT / "examples" / "crime_in_india.toml")


@pytest.fixture(scope="module")
def mccd():
    return _view(MCCD, ROOT / "examples" / "mccd" / "table4.toml")


def test_box_cell_is_an_x_text_pair():
    c = BoxCell(10.0, "17", (5, 1, 15, 9))
    x, t = c
    assert (x, t) == (10.0, "17") and c == (10.0, "17") and len(c) == 2
    assert cell_box(c) == (5, 1, 15, 9) and cell_box((1, "a")) is None
    back = pickle.loads(pickle.dumps(c))
    assert back == c and back.box == c.box


def test_group_boxes():
    words = [(0, 20, 100, "Goa", 90), (50, 60, 100, "17", 92)]
    line = group_words(words)[0]
    assert [t for _, t in line] == ["Goa", "17"]  # cells unpack as (x, text)
    assert [cell_box(c) for c in line] == [(0, 90, 20, 100), (50, 92, 60, 100)]
    got = list(parse_rows([(1, [line])]))
    assert got[0]["value"] == "17" and got[0]["box"] == (50, 92, 60, 100)
    assert "box" not in next(parse_rows([(1, [[(0, "Goa"), (50, "17")]])]))


def test_default_output():
    """Pin votes without boxes and additive return_readings."""

    def unboxed(pages):
        return parse_rows((p, [[(x, t) for x, t in ln] for ln in ls]) for p, ls in pages)

    res = extract(CII)
    plain = extract(CII, parse=unboxed)
    pd.testing.assert_frame_equal(res, plain)
    assert "box" not in res.columns
    res2, readings = extract(CII, return_readings=True)
    pd.testing.assert_frame_equal(res, res2)
    cells = readings.cells
    assert set(cells.method) == set(res2.sources.str.split("|").explode()) - {""}
    assert cells.loc[cells.method == "pymupdf", "box"].notna().all()
    assert cells.loc[cells.method == "pdftotext", "box"].isna().all()


def test_custom_boxes():
    def mine(pages):
        for page_no, lines in pages:
            for line in lines:
                label = " ".join(t for x, t in line if not t.replace(".", "").isdigit())
                nums = [t for x, t in line if t.isdigit()]  # users' parsers unpack cells like this
                for n, t in enumerate(nums):
                    yield {"page": page_no, "label": label, "n": n, "value": t}

    res = extract(CII, ["pdfplumber", "pymupdf", "pdfium"], parse=mine, key=["page", "label", "n"])
    assert (res.status == "verified").sum() > 50
    view = inspect_page(
        CII,
        1,
        ["pdfplumber", "pymupdf", "pdfium"],
        parse=mine,
        key=["page", "label", "n"],
    )
    placed = [c for c in view.cells if c["status"] == "agreed"]
    assert placed and all(c["box"] for c in placed)  # located among the engines' words


def test_locate_follows_reading_order():
    lines = [
        [BoxCell(0, "5", (0, 0, 1, 1)), BoxCell(5, "5", (5, 0, 6, 1))],
        [BoxCell(0, "1,020", (0, 5, 3, 6))],
    ]
    assert locate(["5", "5", "1020"], lines) == [
        (0, 0, 1, 1),
        (5, 0, 6, 1),
        (0, 5, 3, 6),
    ]
    assert locate(["9"], lines) == [None]


def test_html_cells(cii):
    html = render_html(cii)
    assert not re.search(r"(src|href)\s*=\s*[\"']?https?:", html)
    assert "https://" not in html and "http://" not in html
    data = _data(html)
    r = recipe.load(ROOT / "examples" / "crime_in_india.toml")
    parse, key = r.parse_and_key()
    res = extract(CII, parse=parse, key=key, normalize=r.normalizer(), checks=r.check_functions())
    want = {
        (int(x.page), x.row, int(x.col)): "failed"
        if x.failed
        else ("agreed" if x.status == "verified" else "unresolved")
        for x in res.itertuples()
    }
    got = {(c["key"]["page"], c["key"]["row"], c["key"]["col"]): c["status"] for c in data["cells"]}
    assert got == want
    assert data["counts"]["agreed"] == sum(s == "agreed" for s in want.values())
    assert all(c["box"] for c in data["cells"])


def test_pymupdf_box(cii):
    """Pin Kerala's display-pixel box around the PyMuPDF word."""
    with pymupdf.open(CII) as doc:
        w = next(w for w in doc[0].get_text("words") if w[4] == "175810")
    k = SHOW_DPI / 72
    cx, cy = (w[0] + w[2]) / 2 * k, (w[1] + w[3]) / 2 * k
    cell = next(c for c in cii.cells if c["value"] == "175810")
    x0, y0, x1, y1 = cell["box"]
    assert x0 <= cx <= x1 and y0 <= cy <= y1
    assert abs((x0 + x1) / 2 - cx) < 3 * k and abs((y0 + y1) / 2 - cy) < 3 * k
    # every engine with geometry places it there too (camelot: its table cell)
    for m, r in cell["readings"].items():
        b = r["box"]
        assert b[0] <= cx <= b[2] and b[1] <= cy <= b[3], m
    assert cell["readings"]["pdftotext"]["src"] == "borrowed"


def test_compare_engines(cii):
    data = _data(render_html(cii, start="compare"))
    read = {m for c in cii.cells for m in c["readings"]}
    assert read == {e["name"] for e in data["engines"] if e["readings"]}
    assert data["start"] == "compare"
    assert {"pdftotext", "pdfplumber", "pymupdf", "pdfium", "camelot"} <= read


def test_mccd_2011_names_all_33_columns(mccd):
    """Pin all 33 named State columns in the 2011 spread."""
    assert len(mccd.cols) == 33 and all(c["named"] for c in mccd.cols)
    assert mccd.cols[0]["label"] == "0: All States (Total)"
    assert [c["label"].split(": ")[1] for c in mccd.cols][-1] == "West Bengal"
    xs = [c["x"] for c in mccd.cols]
    assert xs == sorted(xs)
    assert mccd.counts()["no_box"] == 0


def test_png_is_written(cii, tmp_path):
    out = write_png(cii, tmp_path / "x.png")
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    from PIL import Image

    with Image.open(out) as im:
        assert im.width > cii.image.width and im.height > cii.image.height


def test_show_output(tmp_path):
    pdf = tmp_path / "cii.pdf"
    pdf.write_bytes(CII.read_bytes())
    r = runner.invoke(app, ["show", str(pdf), "--png"])
    assert r.exit_code == 0, r.output
    html, png = tmp_path / "cii.p1.show.html", tmp_path / "cii.p1.show.png"
    assert html.exists() and png.exists()
    assert _data(html.read_text())["start"] == "page"
    again = runner.invoke(app, ["show", str(pdf)])
    assert again.exit_code == 2 and "already exists" in again.output
    r = runner.invoke(app, ["compare", str(pdf), "-o", str(tmp_path / "only.png")])
    assert r.exit_code == 0 and (tmp_path / "only.png").exists()
    r = runner.invoke(app, ["compare", str(pdf)])
    assert (
        r.exit_code == 0
        and _data((tmp_path / "cii.p1.compare.html").read_text())["start"] == "compare"
    )


def test_bad_page(tmp_path):
    r = runner.invoke(app, ["show", str(CII), "--page", "4", "-o", str(tmp_path)])
    assert r.exit_code == 2 and "has 1 page" in r.output


OCR = ["chandra", "glmocr", "paddleocr", "ocrmac"]
MODULES = {
    "chandra": "chandra",
    "glmocr": "mlx_vlm",
    "paddleocr": "paddleocr",
    "ocrmac": "ocrmac",
}


@pytest.mark.skipif(
    not os.environ.get("PDFEXORCIST_OCR_TESTS"),
    reason="slow OCR test; set PDFEXORCIST_OCR_TESTS=1",
)
def test_tilted_boxes(tmp_path):
    engines = [e for e in OCR if find_spec(MODULES[e])]
    if len(engines) < 2:
        pytest.skip("needs two OCR engines")
    view = _view(
        BMC,
        ROOT / "examples" / "lake_photo" / "recipe.toml",
        methods=engines,
        min_agree=max(2, len(engines) // 2 + 1),
    )
    agreed = [c for c in view.cells if c["status"] == "agreed"]
    assert len(agreed) > 100
    placed = [c for c in agreed if c["box"]]
    assert len(placed) >= len(agreed) - 1
    w, h = view.image.size
    assert all(
        0 <= c["box"][0] < c["box"][2] <= w and 0 <= c["box"][1] < c["box"][3] <= h for c in placed
    )
    # rows are level after deskewing: one lake-year row's cells share a line
    row = [c for c in placed if c["key"]["lake"] == "Tansa" and c["key"]["year"] == "2026"]
    ys = [(c["box"][1] + c["box"][3]) / 2 for c in row]
    assert len(row) >= 5 and max(ys) - min(ys) < 12
    assert {c["label"].split(": ")[-1] for c in view.cols} >= {
        "level",
        "useful_content_ml",
    }
    write_png(view, tmp_path / "bmc.png")
