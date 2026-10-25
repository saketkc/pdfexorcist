"""Scanned pages printed sideways are turned upright before the OCR engines read them."""

import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pymupdf
import pytest
from cli_helpers import run

from pdfexorcist import _orient
from pdfexorcist._clean import clean_pdf
from pdfexorcist._orient import page_turn, turn_scans
from pdfexorcist._vlm_engines import _page_pictures

DIR = Path(__file__).parent / "fixtures" / "karnataka_dengue"
# page 1 of the scan below turned a quarter clockwise onto a portrait page (150 dpi grey JPEG,
# /Rotate 0), as the late-2023 Karnataka scans are: the text reads top to bottom
SIDEWAYS = DIR / "ka_dengue_scan_sideways_2025-12-10.pdf"
UPRIGHT = DIR / "ka_dengue_scan_2025-12-10.pdf"
RECIPE = Path(__file__).parent.parent / "pdfexorcist" / "recipes" / "karnataka_dengue" / "scan.toml"


def _has_osd() -> bool:
    if not shutil.which("tesseract"):
        return False
    langs = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True)
    return "osd" in langs.stdout.split()


needs_osd = pytest.mark.skipif(not _has_osd(), reason="needs tesseract with osd data")


@pytest.fixture(autouse=True)
def _cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDFEXORCIST_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv(_orient.OFF, raising=False)


def _fake_osd(monkeypatch: pytest.MonkeyPatch, rotate: int, conf: float) -> None:
    out = f"Page number: 0\nRotate: {rotate}\nOrientation confidence: {conf}\n".encode()
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/tesseract")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=out))


@pytest.mark.parametrize(
    ("rotate", "conf", "want"), [(270, 8.6, 270), (90, 12.0, 90), (90, 1.5, 0)]
)
def test_osd_turn_sets_rotate(monkeypatch, tmp_path, rotate, conf, want) -> None:
    """OSD's Rotate is /Rotate; an unsure reading leaves the page as it is."""
    _fake_osd(monkeypatch, rotate, conf)
    got = turn_scans(SIDEWAYS, tmp_path / "turned")
    with pymupdf.open(got) as doc:
        assert doc[0].rotation == want
    assert (got == SIDEWAYS) == (want == 0)


def test_text_pages_and_opt_out_are_left_alone(monkeypatch, tmp_path, states_pdf) -> None:
    _fake_osd(monkeypatch, 90, 15.0)
    assert turn_scans(states_pdf, tmp_path / "turned") == states_pdf  # a text layer
    monkeypatch.setenv(_orient.OFF, "0")
    assert turn_scans(SIDEWAYS, tmp_path / "turned") == SIDEWAYS


@pytest.mark.parametrize(("render_mode", "want"), [(3, True), (0, False)])
def test_scan_with_hidden_ocr_layer_is_a_picture(tmp_path, render_mode, want) -> None:
    """A scanner's hidden text layer and a bare sliver at the top still make a scan."""
    with pymupdf.open(SIDEWAYS) as src:
        jpeg = src.extract_image(src[0].get_images()[0][0])["image"]
    doc = pymupdf.open()
    page = doc.new_page(width=592, height=843)
    page.insert_image(pymupdf.Rect(0, 0.3, 592, 843), stream=jpeg, keep_proportion=False)
    page.insert_text((50, 100), "JOINT DIRECTOR", render_mode=render_mode)
    assert _orient._picture_only(page) is want


@needs_osd
def test_sideways_scan_is_turned(tmp_path: Path) -> None:
    turned = clean_pdf(SIDEWAYS, tmp_path)
    with pymupdf.open(turned) as doc:
        page = doc[0]
        assert page.rotation == 270 and page.rect.width > page.rect.height
        assert page_turn(page) == 0  # upright now
    assert clean_pdf(UPRIGHT, tmp_path / "upright") == UPRIGHT


def test_turned_page_pictures_cover_the_page(tmp_path: Path) -> None:
    """OXR's crop of a page turned by /Rotate is the whole turned page, at the scan's dpi."""
    pdf = tmp_path / "turned.pdf"
    with pymupdf.open(SIDEWAYS) as doc:
        doc[0].set_rotation(270)
        doc.save(pdf)
    (_, [img]), *_ = list(_page_pictures(pdf))
    assert img.width > img.height
    assert abs(img.width - 843 * 150 / 72) < 4  # 150 dpi across the turned page


@pytest.mark.skipif(
    not os.environ.get("PDFEXORCIST_OCR_TESTS"), reason="slow OCR test; set PDFEXORCIST_OCR_TESTS=1"
)
@needs_osd
@pytest.mark.usefixtures("wide_console")
def test_sideways_scan_end_to_end(tmp_path: Path) -> None:
    """Every engine reads the turned page; the Dengue total is the printed one."""
    pdf = tmp_path / SIDEWAYS.name
    shutil.copy(SIDEWAYS, pdf)
    r = run(["extract", str(pdf), "--recipe", str(RECIPE), "--json", "-q"])
    s = json.loads(r.stdout)
    assert all(n > 50 for n in s["engines"]["used"].values()), s["engines"]
    t = pd.read_csv(pdf.with_suffix(".csv"), dtype=str, keep_default_na=False)
    total = t.set_index(["disease", "district"]).loc[("Dengue", "Total")]
    assert total[["day_suspected", "day_positive", "cum_suspected", "cum_positive"]].tolist() == [
        "415", "7", "191962", "3551"
    ]  # fmt: skip
