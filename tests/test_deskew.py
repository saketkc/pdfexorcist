"""Scanned pages a degree or two askew are levelled before the OCR engines read them."""

import io
from pathlib import Path

import pymupdf
import pytest
from PIL import Image, ImageDraw

from pdfexorcist import _deskew
from pdfexorcist._deskew import _ink, page_tilt, straighten_scans, tilt

DIR = Path(__file__).parent / "fixtures" / "karnataka_dengue"
# page 1 of hfwcom.karnataka.gov.in's DR-29-07-2025.pdf, an Adobe Scan photographed with
# its right end raised: read as it is, rows take the next district's cumulative counts
TILTED = DIR / "ka_dengue_scan_tilted_2025-07-29.pdf"
LEVEL = DIR / "ka_dengue_scan_2025-12-10.pdf"


@pytest.fixture(autouse=True)
def _cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PDFEXORCIST_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv(_deskew.OFF, raising=False)


def _table(angle: float) -> Image.Image:
    """A ruled table of 30 rows of dashes, turned angle degrees counter-clockwise."""
    img = Image.new("L", (900, 650), 255)
    draw = ImageDraw.Draw(img)
    for i in range(31):
        y = 20 + i * 20
        draw.line([(30, y), (870, y)], fill=0, width=1)
        if i < 30:
            for x in range(40, 860, 30):
                draw.rectangle([x, y + 6, x + 18, y + 13], fill=0)
    return img.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=255)


def _pdf(tmp: Path, img: Image.Image) -> Path:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=648, height=468)
    page.insert_image(page.rect, stream=buf.getvalue())
    out = tmp / "scan.pdf"
    doc.save(out)
    return out


@pytest.mark.parametrize("angle", [1.5, -1.0, 1.9])
def test_tilt_found(angle: float) -> None:
    ink = _table(angle).point(lambda v: 255 if v < 128 else 0)
    assert tilt(ink) == pytest.approx(-angle, abs=0.15)


def test_level_and_slight_tilts_are_left() -> None:
    for angle in (0.0, 0.1):
        assert tilt(_table(angle).point(lambda v: 255 if v < 128 else 0)) == 0.0


def test_tilted_scan_is_levelled(tmp_path: Path) -> None:
    pdf = _pdf(tmp_path, _table(1.5))
    out = straighten_scans(pdf, tmp_path / "out")
    assert out != pdf
    with pymupdf.open(out) as doc:
        page = doc[0]
        assert page.rect == pymupdf.Rect(0, 0, 648, 468)
        assert tilt(_ink(page)) == 0.0


def test_level_scan_and_text_pages_kept(tmp_path: Path) -> None:
    assert straighten_scans(LEVEL, tmp_path / "out") == LEVEL
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Daily Report of Dengue")
    text = tmp_path / "text.pdf"
    doc.save(text)
    assert straighten_scans(text, tmp_path / "out") == text


def test_off_switch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_deskew.OFF, "0")
    assert straighten_scans(TILTED, tmp_path / "out") == TILTED


def test_karnataka_photo_tilt(tmp_path: Path) -> None:
    """The fixture's right end is about half a row up over the table: 1.2 degrees."""
    with pymupdf.open(TILTED) as doc:
        assert page_tilt(doc[0], tmp_path / "c") == pytest.approx(-1.2, abs=0.3)
        # cached by the rendered page
        assert page_tilt(doc[0], tmp_path / "c") == page_tilt(doc[0], None)
    out = straighten_scans(TILTED, tmp_path / "out")
    with pymupdf.open(out) as doc:
        assert tilt(_ink(doc[0])) == 0.0


def test_hidden_ocr_layer_does_not_grow_the_page(tmp_path: Path) -> None:
    """A scanning app's hidden text strays outside the page; the box is kept, so the scan
    still covers the page for turn_scans and straighten_scans."""
    from pdfexorcist._prepare import fit_page_boxes

    pdf = _pdf(tmp_path, _table(1.5))
    doc = pymupdf.open(pdf)
    doc[0].insert_text((600, 700), "Davanagere, Kopal", render_mode=3)
    hidden = tmp_path / "hidden.pdf"
    doc.save(hidden)
    assert fit_page_boxes(hidden, tmp_path / "fit") == hidden
    with pymupdf.open(straighten_scans(hidden, tmp_path / "out")) as out:
        assert tilt(_ink(out[0])) == 0.0
