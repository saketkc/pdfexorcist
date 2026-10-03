"""Page selection and text/scan detection."""

import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

_RANGE = re.compile(r"^(\d+)?\s*(-)?\s*(\d+)?$")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
INPUT_SUFFIXES = IMAGE_SUFFIXES | {".pdf"}


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


def page_texts(pdf: Path) -> list[str]:
    """Read each page's text layer."""
    import pymupdf

    with pymupdf.open(pdf) as doc:
        return [page.get_text() for page in doc]


def pages_matching(
    pdf: Path,
    start: str | None = None,
    stop: str | None = None,
    match: str | None = None,
    within: Sequence[int] | None = None,
) -> list[int]:
    """Return pages selected by case-insensitive text patterns.

    Args:
        pdf: PDF whose text is searched.
        start: Pattern opening the page run.
        stop: Pattern closing that run.
        match: Pattern filtering selected pages.
        within: Candidate 1-based page numbers.
    """
    flags = re.IGNORECASE | re.DOTALL
    texts = page_texts(pdf)
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
            area = abs(page.rect) or 1.0
            cover = max((abs(box & page.rect) for box, _ in image_boxes(page)), default=0.0)
            out.append(
                {
                    "page": i,
                    "chars": len("".join(page.get_text().split())),
                    "scan": cover / area >= 0.8,
                    "width": round(page.rect.width, 1),
                    "height": round(page.rect.height, 1),
                }
            )
    return out


def ocr_layer(pdf: Path) -> bool:
    """Detect OCRmyPDF text layers."""
    import pymupdf

    with pymupdf.open(pdf) as doc:
        meta = doc.metadata or {}
    return "ocrmypdf" in f"{meta.get('producer', '')} {meta.get('creator', '')}".lower()
