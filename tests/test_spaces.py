"""Space glyphs drawn over letters must not split words ("Bombay d u c k", IFCT 2017 p195)."""

import pymupdf
import pytest

from pdfexorcist.extractors import EXTRACTORS


def _spaced_pdf(path):
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=100)
    page.insert_text((20, 50), "Bombay", fontname="helv", fontsize=10)  # registers /helv
    xref = page.get_contents()[0]
    # 278 pulls back one space width, so each space sits under the next letter
    tj = b"BT /helv 10 Tf 70 50 Td [(d ) 278 (u ) 278 (c ) 278 (k)] TJ ET"
    doc.update_stream(
        xref, doc.xref_stream(xref) + b"\n" + tj + b"\nBT /helv 10 Tf 150 50 Td (42) Tj ET"
    )
    doc.save(path)


@pytest.mark.parametrize("engine", ["pdfplumber", "pymupdf", "pdfium"])
def test_overprinted_spaces_do_not_split_words(tmp_path, engine):
    pdf = tmp_path / "spaced.pdf"
    _spaced_pdf(pdf)
    ((_, lines),) = list(EXTRACTORS[engine](pdf))
    assert [t for line in lines for _, t in line] == ["Bombay", "duck", "42"]


def test_plain_spaces_still_split_words(tmp_path):
    pdf = tmp_path / "plain.pdf"
    doc = pymupdf.open()
    doc.new_page(width=300, height=100).insert_text((20, 50), "Bombay duck", fontsize=10)
    doc.save(pdf)
    for engine in ("pymupdf", "pdfium"):
        ((_, lines),) = list(EXTRACTORS[engine](pdf))
        assert " ".join(t for line in lines for _, t in line) == "Bombay duck", engine


def test_an_overhanging_letter_does_not_hide_a_space():
    """Pin a space kept when an italic "f" overhangs it (AMRSN 2022 p213: "Enterococcus
    faecalis"), and one dropped when it sits under the letter."""
    from pdfexorcist._spaces import overprinted_spaces

    s = {"text": " ", "x0": 268.5, "x1": 270.7, "top": 100}
    f = {"text": "f", "x0": 269.5, "x1": 275.4, "top": 100}
    assert overprinted_spaces([s, f]) == set()
    under = {"text": " ", "x0": 270.0, "x1": 272.8, "top": 100}  # one space width back
    assert overprinted_spaces([under, f]) == {id(under)}


def test_a_generated_space_ends_a_word(tmp_path):
    """Pin two words drawn 2.4 points apart with no space glyph (AMRSN 2024 p24): PDFium
    generates a zero-width space there, which must still split them."""
    pdf = tmp_path / "tight.pdf"
    doc = pymupdf.open()
    page = doc.new_page(width=300, height=100)
    page.insert_text((20, 50), "Total", fontname="helv", fontsize=10)  # registers /helv
    width = pymupdf.get_text_length("841/19027", fontname="helv", fontsize=10)
    xref = page.get_contents()[0]
    x = 60 + width + 2.4
    tj = f"BT /helv 10 Tf 60 50 Td (841/19027) Tj ET BT /helv 10 Tf {x:.2f} 50 Td ((4.42)) Tj ET"
    doc.update_stream(xref, doc.xref_stream(xref) + b"\n" + tj.encode())
    doc.save(pdf)
    ((_, lines),) = list(EXTRACTORS["pdfium"](pdf))
    assert [t for line in lines for _, t in line] == ["Total", "841/19027", "(4.42)"]
