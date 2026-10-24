"""Vision-language OCR engines."""

import functools
import hashlib
import logging
import re
from collections.abc import Callable, Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from ._ocr_engines import render_page
from ._registry import register
from .rows import Page, is_value

logger = logging.getLogger(__name__)

GLM_OCR_MLX = "mlx-community/GLM-OCR-bf16"
OXR = "SoMarkAI/OXR-1.0"
OXR_PIXELS = 4_000_000  # its default, 960 x 960, blurs the small print of a table
PICTURE_SHARE = 0.1  # a picture covering this share of the page is read on its own


class _HtmlRows:
    """Parse Chandra HTML into text rows."""

    @staticmethod
    def parse(html: str) -> list:
        rows: list = []

        class P(HTMLParser):
            cell: list[str] | None = None

            col, span, down = 0, 1, 1

            def __init__(self) -> None:
                super().__init__()
                self.held: dict[int, int] = {}  # column -> rows still covered by a rowspan above

            def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                if tag == "tr":
                    rows.append([])
                    self.col = 0
                    self.held = {c: n - 1 for c, n in self.held.items() if n > 1}
                elif tag in ("td", "th", "h1", "h2", "h3"):
                    self.cell = []
                    a = dict(attrs)
                    self.span = int(a.get("colspan") or 1)
                    self.down = int(a.get("rowspan") or 1)
                    while self.col in self.held:  # a cell from a row above ("AMA", rowspan 3)
                        self.col += 1
                elif tag == "br" and self.cell is not None:
                    self.cell.append(" ")

            def handle_endtag(self, tag: str) -> None:
                if self.cell is None:
                    return
                if tag in ("td", "th"):
                    # spanning cell at its middle column keeps later cells in place
                    rows[-1].append((self.col + (self.span - 1) / 2, "".join(self.cell).strip()))
                    if self.down > 1:
                        self.held |= {self.col + i: self.down for i in range(self.span)}
                    self.col += self.span
                    self.cell = None
                elif tag in ("h1", "h2", "h3"):
                    rows.append([(0, "".join(self.cell).strip())])
                    self.cell = None

            def handle_data(self, data: str) -> None:
                if self.cell is not None:
                    self.cell.append(data)

        P().feed(html)
        return [r for r in rows if r]


@register("chandra", default=False, in_process=True)
def chandra_(pdf: Path) -> Iterator[Page]:
    """Run Chandra OCR 2."""

    def infer(img: Any) -> str:  # the model loads on the first uncached page
        from chandra.model.hf import generate_hf
        from chandra.model.schema import BatchInputItem

        batch = [BatchInputItem(image=img, prompt_type="ocr_layout")]
        return generate_hf(batch, _chandra_model())[0].raw

    for i, text in _cache_pages("chandra", pdf, infer, dpi=150):  # the model's native resolution
        yield i, _HtmlRows.parse(text)


def _cache_pages(
    engine: str, pdf: Path, infer: Callable[[Any], str], dpi: int | None = None
) -> Iterator[tuple[int, str]]:
    """Yield cached model output for rendered pages."""
    import shutil

    import pymupdf

    from .fetch import cache_root

    root = cache_root()
    root = root / engine
    root.mkdir(parents=True, exist_ok=True)
    legacy: Path | None = None  # the older cache, keyed by the PDF's bytes and page number
    with pymupdf.open(pdf) as doc:
        for i, page in enumerate(doc, start=1):
            r = render_page(page, dpi)
            h = hashlib.md5(r.image.tobytes())
            h.update(f"{r.image.width}x{r.image.height}@{r.dpi}".encode())
            f = root / f"{h.hexdigest()}.html"
            if not f.exists():
                if legacy is None:
                    legacy = root / hashlib.md5(Path(pdf).read_bytes()).hexdigest()
                old = legacy / f"p{i:04d}.html"
                if old.exists():
                    shutil.copyfile(old, f)
                else:
                    f.write_text(infer(r.image))
                    logger.info("%s page %d", engine, i)
            yield i, f.read_text()


@register("glmocr", default=False, in_process=True)
def glmocr_(pdf: Path) -> Iterator[Page]:
    """Run GLM-OCR through MLX."""
    from mlx_vlm import generate

    def infer(img: Any) -> str:
        m, proc, prompt = _glm_model()
        img.thumbnail((2048, 2048))  # model's working size; larger only slows it
        out = generate(m, proc, prompt, [img], max_tokens=8192, temperature=0.0, verbose=False)
        return str(getattr(out, "text", out))

    for i, text in _cache_pages("glmocr", pdf, infer):
        yield (
            i,
            _HtmlRows.parse(text) if "<table" in text.lower() else _parse_markdown(text),
        )


@register("oxr", default=False, in_process=True)
def oxr_(pdf: Path) -> Iterator[Page]:
    """Run SoMark OXR through MLX on each picture of a page, or on the page if it has none.

    OXR reads at most OXR_PIXELS; a picture read at its own resolution keeps small print legible
    (2018 AMRSN Table 6.2: 0 of 200 R/n cells wrong from the picture, 1-3 from the page).
    """
    for i, crops in _page_pictures(pdf):
        rows: list = []
        for img in crops:  # an empty row between pictures: a chart's labels are not table headings
            rows += ([[]] if rows else []) + _HtmlRows.parse(_cached("oxr", img, _oxr_infer))
        yield i, rows


def _oxr_infer(img: Any) -> str:
    from mlx_vlm import generate

    m, proc, prompt = _oxr_model()
    out = generate(m, proc, prompt, image=[img], max_tokens=8192, temperature=0.0,
                   verbose=False, max_pixels=OXR_PIXELS)  # fmt: skip
    return str(getattr(out, "text", out))


@functools.lru_cache(maxsize=1)
def _oxr_model() -> tuple:
    """Load OXR once per process."""
    from importlib.util import find_spec

    from mlx_vlm import load
    from mlx_vlm.prompt_utils import apply_chat_template

    if find_spec("mlx_vlm.models.oxr") is None:
        raise RuntimeError("oxr needs an mlx-vlm with OXR (after 0.7.10): uv sync --extra glmocr")
    m, proc = load(OXR)
    prompt = "Recognize the table of the image into html format."
    return m, proc, apply_chat_template(proc, m.config, prompt, num_images=1)


def _page_pictures(pdf: Path) -> Iterator[tuple[int, list]]:
    """Each page's pictures, top to bottom, rendered at their own resolution (at most 300 dpi);
    the whole page rendered when it has none."""
    import pymupdf

    with pymupdf.open(pdf) as doc:
        for i, page in enumerate(doc, start=1):
            area = page.rect.width * page.rect.height
            crops = []
            for info in sorted(page.get_image_info(), key=lambda d: d["bbox"][1]):
                rect = pymupdf.Rect(info["bbox"]) & page.rect
                if rect.is_empty or rect.width * rect.height < PICTURE_SHARE * area:
                    continue
                dpi = min(300, max(72, round(info["width"] / rect.width * 72)))
                crops.append(_image(page.get_pixmap(clip=rect, dpi=dpi)))
            yield i, crops or [render_page(page, None).image]


def _image(pix: Any) -> Any:
    from PIL import Image

    return Image.frombytes("RGB" if pix.n < 4 else "RGBA", (pix.width, pix.height), pix.samples)


def _cached(engine: str, img: Any, infer: Callable[[Any], str]) -> str:
    """Model output for an image, cached by its pixels."""
    from .fetch import cache_root

    root = cache_root() / engine
    root.mkdir(parents=True, exist_ok=True)
    h = hashlib.md5(img.tobytes())
    h.update(f"{img.width}x{img.height}".encode())
    f = root / f"{h.hexdigest()}.html"
    if not f.exists():
        f.write_text(infer(img))
        logger.info("%s %dx%d", engine, img.width, img.height)
    return f.read_text()


@functools.lru_cache(maxsize=1)
def _glm_model() -> tuple:
    """Load GLM-OCR once per process."""
    from mlx_vlm import load
    from mlx_vlm.prompt_utils import apply_chat_template

    m, proc = load(GLM_OCR_MLX)
    return (
        m,
        proc,
        apply_chat_template(proc, m.config, "Table Recognition:", num_images=1),
    )


def _parse_markdown(text: str) -> list:
    """Parse model Markdown into text rows."""
    rows = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.count("|") >= 2:
            piped = [c.strip() for c in line.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{3,}:?", c) for c in piped):
                rows.append([(j, c) for j, c in enumerate(piped) if c])
        elif line:
            cells: list[str] = []
            for tok in line.split():
                if is_value(tok) or not cells or is_value(cells[-1]):
                    cells.append(tok)
                else:
                    cells[-1] += " " + tok
            rows.append(list(enumerate(cells)))
    return rows


@functools.lru_cache(maxsize=1)
def _chandra_model() -> Any:
    """Load Chandra once per process."""
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    device = "cuda" if torch.cuda.is_available() else "mps"
    model = AutoModelForImageTextToText.from_pretrained(
        "datalab-to/chandra-ocr-2", dtype=torch.bfloat16, device_map=device
    ).eval()
    model.processor = AutoProcessor.from_pretrained("datalab-to/chandra-ocr-2")
    model.processor.tokenizer.padding_side = "left"
    return model
