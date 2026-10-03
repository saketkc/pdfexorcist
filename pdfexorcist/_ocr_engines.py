"""OCR engines and page rendering."""

import functools
import logging
import os
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._registry import OCR_DPI, register
from ._text_engines import _spans
from .rows import Page, group_words

logger = logging.getLogger(__name__)


@register("tesseract", default=False)
def tesseract_(pdf: Path) -> Iterator[Page]:
    """Run Tesseract on rendered pages."""
    import pymupdf

    if not shutil.which("tesseract"):
        raise ImportError("tesseract is not on PATH")
    scale = 72 / OCR_DPI  # pixels to points; tolerances assume points
    with pymupdf.open(pdf) as doc:
        for i, page in enumerate(doc, start=1):
            png = page.get_pixmap(dpi=OCR_DPI).tobytes("png")
            tsv = subprocess.run(
                ["tesseract", "stdin", "stdout", "--psm", "6", "tsv"],
                input=png,
                capture_output=True,
                check=True,
            ).stdout.decode()
            words = []
            for row in tsv.splitlines()[1:]:
                f = row.split("\t")
                if len(f) == 12 and f[0] == "5" and f[11].strip():
                    x, y, w, h = (int(v) * scale for v in f[6:10])
                    words.append((x, x + w, y + h, f[11], y))
            yield i, group_words(words)


@dataclass(frozen=True)
class Rendered:
    """A rendered page for OCR and display."""

    image: Any  # PIL image, levelled when the page is a photo
    scale: float  # points per pixel
    angle: float  # degrees a photo was rotated by to level it (0.0: not rotated)
    size0: tuple[int, int]  # pixel size before levelling
    dpi: int


def render_page(page: Any, dpi: int | None = None, text_dpi: int = OCR_DPI) -> Rendered:
    """Render a page at text or native image resolution."""
    from PIL import Image

    photo = False
    if dpi is None:
        native = _image_dpi(page)
        dpi, photo = (native, True) if native else (text_dpi, False)
    pix = page.get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    angle = _skew(img) if photo else 0.0
    return Rendered(_level(img, angle), 72 / dpi, angle, img.size, dpi)


def _render(page: Any, dpi: int | None = None) -> tuple[Any, float]:
    """Return a rendered image and its scale."""
    r = render_page(page, dpi)
    return r.image, r.scale


def _image_dpi(page: Any) -> int | None:
    """Return native DPI for a single-image page."""
    from .pages import image_boxes

    imgs = image_boxes(page)
    if len(imgs) == 1 and imgs[0][0].contains(page.rect * 0.99):
        box, info = imgs[0]  # info's width is in the image's own, unrotated pixels
        return round(72 * info["width"] / (box.height if page.rotation % 180 else box.width))
    return None


def _deskew(img: Any) -> Any:
    """Level a photographed page by its horizontal lines."""
    return _level(img, _skew(img))


def _level(img: Any, angle: float) -> Any:
    """Rotate an image counterclockwise when needed."""
    from PIL import Image

    if not angle:
        return img
    logger.info("deskewing a photographed page by %.2f degrees", angle)
    return img.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="white")


def _skew(img: Any) -> float:
    """Estimate a page's counterclockwise levelling angle."""
    import cv2
    import numpy as np

    edges = cv2.Canny(cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY), 50, 150)
    lines = cv2.HoughLinesP(
        edges,
        1,
        np.pi / 1800,
        threshold=200,
        minLineLength=img.width // 3,
        maxLineGap=10,
    )
    angles = [
        a
        for x1, y1, x2, y2 in ([] if lines is None else lines.reshape(-1, 4))
        if abs(a := np.degrees(np.arctan2(y2 - y1, x2 - x1))) < 10
    ]
    angle = float(np.median(angles)) if angles else 0.0
    return 0.0 if abs(angle) < 0.2 else angle


def _images(pdf: Path) -> Iterator[tuple]:
    """Yield rendered pages and scales."""
    import pymupdf

    with pymupdf.open(pdf) as doc:
        for i, page in enumerate(doc, start=1):
            yield (i, *_render(page))


def _words(x0: float, x1: float, y_top: float, y_bottom: float, text: str) -> list:
    """Split an OCR box into positioned tokens."""
    return [(a, b, y_bottom, t, y_top) for a, b, t in _spans(x0, x1, text)]


@register("ocrmac", default=False)
def ocrmac_(pdf: Path) -> Iterator[Page]:
    """Run Apple Vision OCR through ocrmac."""
    import io
    import json
    import sys
    import tempfile

    import ocrmac  # noqa: F401  # ImportError here, so extract() skips the engine

    cmd = [sys.executable, "-m", "pdfexorcist._vision_worker"]
    with tempfile.TemporaryFile() as log:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log)
        assert proc.stdin is not None and proc.stdout is not None
        try:
            for i, img, scale in _images(pdf):
                w, h = img.width * scale, img.height * scale
                png = io.BytesIO()
                img.save(png, format="PNG")
                proc.stdin.write(len(png.getvalue()).to_bytes(4, "big") + png.getvalue())
                proc.stdin.flush()
                answer = proc.stdout.readline()
                if not answer:  # the worker died: raise with its error output
                    proc.stdin.close()
                    proc.wait()
                    log.seek(0)
                    raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=log.read())
                words = []
                for text, _, (x, y, bw, bh) in json.loads(answer):
                    words += _words(x * w, (x + bw) * w, (1 - y - bh) * h, (1 - y) * h, text)
                yield i, group_words(words)
            proc.stdin.close()
            if proc.wait():
                log.seek(0)
                raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=log.read())
        finally:
            if proc.poll() is None:  # stopped early (an error, or the caller stopped reading)
                proc.kill()
                proc.wait()


@register("paddleocr", default=False)
def paddleocr_(pdf: Path) -> Iterator[Page]:
    """Run PaddleOCR 3."""
    import numpy as np

    ocr = _paddle()
    for i, img, scale in _images(pdf):
        res = ocr.predict(np.array(img)[:, :, ::-1])[0]  # paddle expects BGR
        words = []
        for text, box in zip(res["rec_texts"], res["rec_boxes"], strict=True):
            x0, y0, x1, y1 = (float(v) * scale for v in box)
            words += _words(x0, x1, y0, y1, text)
        yield i, group_words(words)


@functools.lru_cache(maxsize=1)
def _paddle() -> Any:
    """Load PaddleOCR models once per process."""
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    from paddleocr import PaddleOCR

    return PaddleOCR(
        lang="en",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )
