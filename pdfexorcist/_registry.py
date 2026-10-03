"""Engine registry."""

from collections.abc import Callable, Iterator
from pathlib import Path

from .rows import Page

Extractor = Callable[[Path], Iterator[Page]]
EXTRACTORS: dict[str, Extractor] = {}
DEFAULTS: list[str] = []
IN_PROCESS: set[str] = set()  # engines --jobs keeps in the calling process
OCR_DPI = 300


def register(
    name: str, default: bool = True, in_process: bool = False
) -> Callable[[Extractor], Extractor]:
    """Add an extractor under name.

    Args:
        name: The engine's name in methods and --engines.
        default: Run it when no engines are named.
        in_process: Never read in a worker process (a model held on the GPU).
    """

    def deco(fn: Extractor) -> Extractor:
        EXTRACTORS[name] = fn
        if default:
            DEFAULTS.append(name)
        if in_process:
            IN_PROCESS.add(name)
        return fn

    return deco
