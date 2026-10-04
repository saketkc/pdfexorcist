"""The part of pypdfium2 that pdfexorcist and camelot use, over PDFium wasm.

Handles close as in pypdfium2: idempotent, children first, unclosed ones when collected.
"""

import math
import weakref
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from js import pdfium as _js  # type: ignore[import-not-found]  # set by the worker
from pyodide.ffi import to_js  # type: ignore[import-not-found]

PYPDFIUM_INFO = "wasm shim"


class _Handle:
    _h: int | None = None  # for __del__ after a failed __init__
    _parent: "_Handle | None" = None  # keeps the document alive

    def __init__(self, h: int, closer: Callable[[int], Any]) -> None:
        self._h = h
        self._closer = closer
        self._kids: weakref.WeakSet[_Handle] = weakref.WeakSet()

    def _own(self, kid: "_Handle") -> Any:
        self._kids.add(kid)
        kid._parent = self
        return kid

    @property
    def raw(self) -> int:
        if self._h is None:
            raise ValueError(f"{type(self).__name__} is closed")
        return self._h

    def close(self) -> None:
        if self._h is None:
            return
        for kid in list(self._kids):
            kid.close()
        h, self._h = self._h, None
        self._closer(h)

    def __enter__(self) -> Any:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        self.close()


class PdfDocument(_Handle):
    def __init__(self, path: str) -> None:
        super().__init__(_js.open(to_js(Path(path).read_bytes())), _js.closeDoc)

    def __len__(self) -> int:
        return int(_js.pageCount(self.raw))

    def __getitem__(self, i: int) -> "PdfPage":
        return self._own(PdfPage(_js.loadPage(self.raw, i)))

    def __iter__(self) -> Iterator["PdfPage"]:
        return (self[i] for i in range(len(self)))

    def init_forms(self) -> None:
        if _js.formType(self.raw):  # form fields are not drawn here
            raise NotImplementedError("PDFs with forms are not supported in the browser")


class PdfPage(_Handle):
    def __init__(self, h: int) -> None:
        super().__init__(h, _js.closePage)

    def get_width(self) -> float:
        return float(_js.pageWidth(self.raw))

    def get_height(self) -> float:
        return float(_js.pageHeight(self.raw))

    def get_bbox(self) -> tuple:
        return tuple(_js.bbox(self.raw).to_py())

    def get_textpage(self) -> "PdfTextPage":
        return self._own(PdfTextPage(_js.textPage(self.raw)))

    def render(self, scale: float = 1) -> "PdfBitmap":
        w, h = math.ceil(self.get_width() * scale), math.ceil(self.get_height() * scale)
        stride, buf = _js.render(self.raw, w, h)
        return PdfBitmap(w, h, int(stride), buf.to_bytes())


class PdfBitmap:
    def __init__(self, width: int, height: int, stride: int, buffer: bytes) -> None:
        self.width, self.height, self.stride, self.buffer = width, height, stride, buffer

    def to_pil(self) -> Any:
        from PIL import Image

        size = (self.width, self.height)
        return Image.frombuffer("RGB", size, self.buffer, "raw", "BGR", self.stride, 1)


class PdfTextPage(_Handle):
    def __init__(self, h: int) -> None:
        super().__init__(h, _js.closeTextPage)

    def count_rects(self) -> int:
        return int(_js.countRects(self.raw))

    def get_rect(self, i: int) -> tuple:
        return tuple(_js.rect(self.raw, i).to_py())

    def get_text_bounded(self, left: float, bottom: float, right: float, top: float) -> str:
        return str(_js.boundedText(self.raw, left, top, right, bottom))
