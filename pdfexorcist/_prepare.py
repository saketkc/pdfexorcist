"""Copies of a PDF prepared for the engines: page slices, images, grown page boxes."""

import logging
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def save_copy(doc: Any, out_dir: Path, name: str) -> Path:
    """Save doc as out_dir/name; stable bytes, as older OCR caches are keyed on them."""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    path = Path(out_dir) / name
    doc.save(path, no_new_id=True)
    return path


def replace_pages(pdf: Path, doc: Any, copies: dict[int, Any], out_dir: Path) -> Path:
    """Save doc with each page i replaced by the one-page doc copies[i], which are closed."""
    import pymupdf

    with pymupdf.open() as out:
        done = 0  # pages before this are in out
        for i, one in sorted(copies.items()):
            if i > done:
                out.insert_pdf(doc, from_page=done, to_page=i - 1)
            out.insert_pdf(one)
            one.close()
            done = i + 1
        if done < doc.page_count:
            out.insert_pdf(doc, from_page=done, to_page=doc.page_count - 1)
        return save_copy(out, out_dir, pdf.name)


def replace_each(pdf: Path, out_dir: Path, one_page: Any, what: str) -> Path:
    """Copy of pdf with each page one_page(doc, page) returns a one-page doc for replaced by it,
    or pdf itself when it returns None for every page."""
    import pymupdf

    with pymupdf.open(pdf) as doc:
        copies = {page.number: one for page in doc if (one := one_page(doc, page))}
        if not copies:
            return pdf
        logger.info("%d pages: %s", len(copies), what)
        return replace_pages(pdf, doc, copies, out_dir)


def redact(page: Any, rects: Iterable[Any]) -> None:
    """Remove the text in each rect, keeping images and rules."""
    for rect in rects:
        page.add_redact_annot(rect)
    page.apply_redactions(images=0, graphics=0)


def redact_dots(page: Any, centres: Iterable[tuple[float, float]]) -> None:
    """Remove the text at each centre (a 0.3 pt dot), keeping images and rules."""
    import pymupdf

    redact(page, (pymupdf.Rect(x - 0.3, y - 0.3, x + 0.3, y + 0.3) for x, y in centres))


def fit_page_boxes(pdf: Path, out_dir: Path) -> Path:
    """Copy of pdf whose page boxes cover all their text, or pdf itself.

    Poppler and MuPDF clip text drawn outside a page box; pdfminer and PDFium read
    it, so without this the engines would read different tables.
    """
    import pymupdf

    with pymupdf.open(pdf) as doc:  # closed on exit: Windows cannot delete an open file
        return _fit_boxes(doc, pdf, out_dir)


def _ocr_layer_only(page: Any) -> bool:
    """Whether all of page's text is unseen (render mode 3 or no opacity): a scanning app's
    OCR layer. Adobe Scan's strays far outside the page (DR-30-07-2025: a box grown from 444
    to 741 pt), which would shrink the scan in the page and hide it from turn_scans."""
    return all(s["type"] == 3 or s["opacity"] == 0 for s in page.get_texttrace())


def _fit_boxes(doc: Any, pdf: Path, out_dir: Path) -> Path:
    import pymupdf

    grown = 0
    for page in doc:
        big = pymupdf.Rect(-1e4, -1e4, 1e4, 1e4)
        words = page.get_textpage(clip=big).extractWORDS()
        if not words:
            continue
        # words are in page space (y down, origin top-left); boxes are set in PDF space (y up)
        box = pymupdf.Rect(page.cropbox)
        for w in words:
            box |= pymupdf.Rect(w[:4]) * page.derotation_matrix
        if box != page.cropbox and not _ocr_layer_only(page):
            # set_mediabox also resets the CropBox (which MuPDF clips to) to the new MediaBox
            page.set_mediabox(box * ~page.transformation_matrix)
            grown += 1
    if not grown:
        return Path(pdf)
    logger.info("%d pages had text outside their box; boxes grown", grown)
    return save_copy(doc, out_dir, Path(pdf).name)


def _pages(pdf: Path, pages: Sequence[int], out_dir: Path) -> Path:
    """Copy selected pages into a new PDF."""
    import pymupdf

    path = Path(out_dir) / f"pages_{Path(pdf).name}"
    with pymupdf.open(pdf) as src, pymupdf.open() as out:
        for p in pages:
            out.insert_pdf(src, from_page=p - 1, to_page=p - 1)
        out.save(path, no_new_id=True)  # stable bytes: older OCR caches are keyed on them
    return path


def crop_pages(pdf: Path, out_dir: Path, area: tuple[float, float, float, float]) -> Path:
    """Copy pdf with every page cropped to (x0, y0, x1, y1) in points."""
    import pymupdf

    rect = pymupdf.Rect(area)
    if rect.is_empty or rect.is_infinite:
        raise ValueError("page area needs x1 > x0 and y1 > y0")
    with pymupdf.open(pdf) as doc:
        for page in doc:
            if not page.rect.contains(rect):
                raise ValueError(f"page area {area} is outside page {tuple(page.rect)}")
            # redact outside too; some extractors ignore the CropBox
            whole = page.rect
            bands = (
                pymupdf.Rect(whole.x0, whole.y0, rect.x0, whole.y1),
                pymupdf.Rect(rect.x1, whole.y0, whole.x1, whole.y1),
                pymupdf.Rect(rect.x0, whole.y0, rect.x1, rect.y0),
                pymupdf.Rect(rect.x0, rect.y1, rect.x1, whole.y1),
            )
            redact(page, (b for b in bands if not b.is_empty))
            page.set_cropbox(rect)
        return save_copy(doc, out_dir, f"area_{Path(pdf).name}")


def as_pdf(path: Path, out_dir: Path) -> Path:
    """path, or an image wrapped in a one-page PDF in out_dir."""
    from .pages import IMAGE_SUFFIXES

    return _photo_pdf(path, out_dir) if path.suffix.lower() in IMAGE_SUFFIXES else path


def _photo_pdf(img: Path, out_dir: Path) -> Path:
    """Wrap an image in a one-page PDF."""
    import pymupdf

    path = Path(out_dir) / f"{Path(img).stem}.pdf"
    with pymupdf.open(img) as doc:
        path.write_bytes(doc.convert_to_pdf())
    return path
