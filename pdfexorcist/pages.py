"""Page selection and text/scan detection."""

import logging
import re
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RANGE = re.compile(r"^(\d+)?\s*(-)?\s*(\d+)?$")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
INPUT_SUFFIXES = IMAGE_SUFFIXES | {".pdf"}
STRIP = 0.15  # share of the page height read by OCR for titles
COVER = 0.8  # share of the page a scan's picture covers (DR17-10-23 p2: 0.89, its box grown)


def parse_pages(spec: str, n_pages: int | None = None) -> list[int]:
    """Return unique, ordered pages from comma-separated ranges."""
    out: list[int] = []
    for part in (p.strip() for p in str(spec).split(",")):
        if not part:
            continue
        m = _RANGE.match(part)
        if not m or not (m.group(1) or m.group(3)):
            raise ValueError(f"{part!r} is not a page number or range like 3, 1-5 or 10-")
        a = int(m.group(1)) if m.group(1) else 1
        if m.group(2):
            if m.group(3):
                b = int(m.group(3))
            elif n_pages is not None:
                b = n_pages
            else:
                raise ValueError(f"{part!r} has no end page")
        else:
            b = a
        if a < 1 or b < a:
            raise ValueError(f"{part!r} is not a valid range (pages start at 1, low to high)")
        if n_pages is not None and b > n_pages:
            raise ValueError(f"{part!r} goes past the last page ({n_pages})")
        out += [p for p in range(a, b + 1) if p not in out]
    if not out:
        raise ValueError("no pages given")
    return out


def format_pages(pages: list[int]) -> str:
    """Pages as parse_pages reads them: [18, 19, 20, 43] -> "18-20,43"."""
    runs: list[list[int]] = []
    for p in pages:
        if runs and p == runs[-1][1] + 1:
            runs[-1][1] = p
        else:
            runs.append([p, p])
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def page_texts(
    pdf: Path,
    ocr_fallback: bool = False,
    strip: float = STRIP,
    within: Sequence[int] | None = None,
) -> list[str]:
    """Read each page's text layer.

    With ocr_fallback, a page whose text layer is unusable (none, or control codes
    from a font without a Unicode map) also gets tesseract's OCR of its top strip
    (that share of the page height), where titles are; only pages in within, if given.
    """
    import pymupdf

    with pymupdf.open(pdf) as doc:
        texts = [page.get_text() for page in doc]
        ocr = set(within or range(1, len(texts) + 1)) if ocr_fallback else set()
        bad = [i for i, t in enumerate(texts) if i + 1 in ocr and not usable(t)]
        if bad and not shutil.which("tesseract"):
            logger.warning(
                "%d pages have no usable text; matching their titles needs tesseract", len(bad)
            )
            return texts
        for i in bad:
            texts[i] += "\n" + _ocr_top(doc[i], strip)
    return texts


def usable(text: str) -> bool:
    """Whether a text layer reads as text: 20 letters or digits, and almost no control codes."""
    shown = [c for c in text if not c.isspace()]
    junk = sum(1 for c in shown if ord(c) < 32 or 0xE000 <= ord(c) <= 0xF8FF or c == "\ufffd")
    return sum(c.isalnum() for c in shown) >= 20 and junk <= 0.02 * len(shown)


def _ocr_top(page: Any, strip: float) -> str:
    """Tesseract's reading of the top strip of a page."""
    import pymupdf

    clip = pymupdf.Rect(
        page.rect.x0, page.rect.y0, page.rect.x1, page.rect.y0 + strip * page.rect.height
    )
    png = page.get_pixmap(dpi=200, clip=clip, colorspace=pymupdf.csGRAY).tobytes("png")
    return subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "6"], input=png, capture_output=True, check=False
    ).stdout.decode()


def find(pdf: Path, pattern: str, ocr_fallback: bool = True, strip: float = STRIP) -> list[int]:
    """1-based pages whose text matches pattern (case-insensitive).

    A page without usable text is matched on OCR of its top strip (strip x its
    height) when ocr_fallback is set and tesseract is installed.
    """
    return pages_matching(pdf, match=pattern, ocr_fallback=ocr_fallback, strip=strip)


def pages_matching(
    pdf: Path,
    start: str | None = None,
    stop: str | None = None,
    match: str | None = None,
    within: Sequence[int] | None = None,
    ocr_fallback: bool = True,
    strip: float = STRIP,
    texts: Sequence[str] | None = None,
) -> list[int]:
    """Return pages selected by case-insensitive text patterns.

    Args:
        pdf: PDF whose text is searched.
        start: Pattern opening the page run.
        stop: Pattern closing that run.
        match: Pattern filtering selected pages.
        within: Candidate 1-based page numbers.
        ocr_fallback: Read pages without usable text by OCR of their top strip.
        strip: Share of the page height that OCR reads.
        texts: Every page's text, already read.
    """
    flags = re.IGNORECASE | re.DOTALL
    texts = texts if texts is not None else page_texts(pdf, ocr_fallback, strip, within)
    pages = list(within) if within else list(range(1, len(texts) + 1))
    if start:
        rx = re.compile(start, flags)
        first = next((i for i, p in enumerate(pages) if rx.search(texts[p - 1])), None)
        if first is None:
            return []
        pages = pages[first:]
        if stop:
            rx = re.compile(stop, flags)
            end = next((i for i, p in enumerate(pages) if i and rx.search(texts[p - 1])), None)
            pages = pages[:end]
    elif stop:
        raise ValueError("stop needs start")
    if match:
        rx = re.compile(match, flags)
        pages = [p for p in pages if rx.search(texts[p - 1])]
    return pages


def image_boxes(page: Any) -> list[tuple[Any, dict]]:
    """Return rotation-adjusted image boxes with metadata."""
    import pymupdf

    return [(pymupdf.Rect(im["bbox"]) * page.rotation_matrix, im) for im in page.get_image_info()]


def page_kinds(pdf: Path, pages: Sequence[int] | None = None) -> list[dict]:
    """Return text coverage and dimensions for selected pages."""
    import pymupdf

    out = []
    with pymupdf.open(pdf) as doc:
        for i in pages or range(1, doc.page_count + 1):
            page = doc[i - 1]
            out.append(
                {
                    "page": i,
                    "chars": len("".join(page.get_text().split())),
                    "scan": is_scan_page(page),
                    "width": round(page.rect.width, 1),
                    "height": round(page.rect.height, 1),
                }
            )
    return out


def is_scan_page(page: Any) -> bool:
    """Whether one picture covers page."""
    # scanners leave a sliver of the page bare (DR22-1-24: 0.3 pt at the top)
    cover = max((abs(box & page.rect) for box, _ in image_boxes(page)), default=0.0)
    return cover >= COVER * (abs(page.rect) or 1.0)


def is_scan(kinds: Sequence[dict]) -> bool:
    """Whether pages read by page_kinds are a scan: no text, and an image across a page."""
    return all(k["chars"] < 20 for k in kinds) and any(k["scan"] for k in kinds)


def ocr_layer(pdf: Path) -> bool:
    """Detect OCRmyPDF text layers."""
    import pymupdf

    with pymupdf.open(pdf) as doc:
        meta = doc.metadata or {}
    return "ocrmypdf" in f"{meta.get('producer', '')} {meta.get('creator', '')}".lower()
