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

from ._registry import OCR_DPI, register, tesseract_words
from ._text_engines import _words
from .rows import Page, group_words

logger = logging.getLogger(__name__)

UPRIGHT = "pdfexorcist, upright images"  # the producer of a PDF of pages that need no levelling


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
            words = []
            for *box, text in tesseract_words(png):
                x, y, w, h = (v * scale for v in box)
                words.append((x, x + w, y + h, text, y))
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
    level = photo and page.parent.metadata.get("producer") != UPRIGHT  # our own pages are level
    angle = _skew(img) if level else 0.0
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


class Worker:
    """A subprocess answering each length-prefixed PNG with one JSON line; started on first use."""

    def __init__(self, cmd: list[str]) -> None:
        self.cmd = cmd
        self.proc: Any = None
        self.log: Any = None

    def __enter__(self) -> "Worker":
        return self

    def __exit__(self, exc_type: object, *_: object) -> None:
        if self.proc is not None and exc_type is None:
            self.proc.stdin.close()
            if self.proc.wait():
                raise self._failed()
        self.close()

    def ask(self, img: Any) -> Any:
        """The worker's answer for one image; raise with its log if it died."""
        import io
        import json
        import tempfile

        if self.proc is None:
            self.log = tempfile.TemporaryFile()  # noqa: SIM115  # open while the worker runs
            self.proc = subprocess.Popen(
                self.cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log
            )
        png = io.BytesIO()
        img.save(png, format="PNG")
        try:
            self.proc.stdin.write(len(png.getbuffer()).to_bytes(4, "big"))
            self.proc.stdin.write(png.getbuffer())
            self.proc.stdin.flush()
            answer = self.proc.stdout.readline()
        except BrokenPipeError:  # it died while loading
            answer = b""
        if not answer:
            self.proc.wait()
            err = self._failed()
            self.close()
            raise err
        return json.loads(answer)

    def _failed(self) -> subprocess.CalledProcessError:
        self.log.seek(0)
        return subprocess.CalledProcessError(self.proc.returncode, self.cmd, stderr=self.log.read())

    def close(self) -> None:
        if self.proc is not None and self.proc.poll() is None:  # an error, or the caller stopped
            self.proc.kill()
            self.proc.wait()
        if self.log is not None:
            self.log.close()
        self.proc = self.log = None


@register("ocrmac", default=False)
def ocrmac_(pdf: Path, tries: int = 3) -> Iterator[Page]:
    """Run Apple Vision OCR through ocrmac; tries: readings of a page that comes back empty."""
    import sys

    import ocrmac  # noqa: F401  # ImportError here, so extract() skips the engine

    with Worker([sys.executable, "-m", "pdfexorcist._vision_worker", str(tries)]) as worker:
        for i, img, scale in _images(pdf):
            w, h = img.width * scale, img.height * scale
            words = []
            for text, _, (x, y, bw, bh) in worker.ask(img):
                words += _words(x * w, (x + bw) * w, (1 - y - bh) * h, (1 - y) * h, text)
            yield i, group_words(words)


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


@register("doctr", default=False)
def doctr_(pdf: Path) -> Iterator[Page]:
    """Run docTR's OCR models on onnxruntime (OnnxTR)."""
    import numpy as np

    ocr = _doctr()
    for i, img, scale in _images(pdf):
        w, h = img.width * scale, img.height * scale
        page = ocr([np.array(img)]).pages[0]
        words = []
        for word in (wd for b in page.blocks for ln in b.lines for wd in ln.words):
            (x0, y0), (x1, y1) = word.geometry  # relative to the page
            words += _words(x0 * w, x1 * w, y0 * h, y1 * h, word.value)
        yield i, group_words(words)


@register("indra", default=False)
def indra_(pdf: Path) -> Iterator[Page]:
    """Run Datalab's Indra OCR on onnxruntime."""
    import numpy as np

    ocr = _indra()
    for i, img, scale in _images(pdf):
        words = []
        for line in ocr(np.array(img.convert("L")), turn=False).lines:  # the page is upright
            x0, y0, x1, y1 = (v * scale for v in line.box)
            words += _words(x0, x1, y0, y1, line.text)
        yield i, group_words(words)


@functools.lru_cache(maxsize=1)
def _indra() -> Any:
    """Load Indra OCR models once per process."""
    import multiprocessing

    import indra_ocr
    import onnxruntime

    threads = 1 if multiprocessing.parent_process() else 4  # a --jobs worker gets one core
    cuda = "CUDAExecutionProvider"  # only onnxruntime-gpu has it; CoreML was slower than the CPU
    gpu = [cuda, "CPUExecutionProvider"] if cuda in onnxruntime.get_available_providers() else None
    return indra_ocr.load(threads=threads, providers=gpu).ocr


@functools.lru_cache(maxsize=1)
def _doctr() -> Any:
    """Load docTR models once per process."""
    from onnxtr.models import ocr_predictor

    return ocr_predictor()


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
