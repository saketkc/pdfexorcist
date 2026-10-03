"""Installed engines and install hints."""

import platform
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from importlib.util import find_spec

from .extractors import DEFAULTS, EXTRACTORS

PIP = 'pip install "pdfexorcist[{}]"'


@dataclass(frozen=True)
class EngineInfo:
    """What one engine needs and reads."""

    name: str
    reads: str  # "text layer" or "pixels (OCR)"
    about: str
    modules: tuple[str, ...] = ()  # Python modules it imports
    programs: tuple[str, ...] = ()  # executables it runs
    extra: str | None = None  # pip extra that installs it
    platforms: Callable[[], bool] | None = None  # None: everywhere
    platform_note: str = ""


def _mac() -> bool:
    return sys.platform == "darwin"


def _apple_silicon() -> bool:
    return _mac() and platform.machine() == "arm64"


KNOWN: dict[str, EngineInfo] = {
    e.name: e
    for e in [
        EngineInfo("pdftotext", "text layer", "poppler's pdftotext", programs=("pdftotext",)),
        EngineInfo("pdfplumber", "text layer", "pdfminer word boxes", modules=("pdfplumber",)),
        EngineInfo("pymupdf", "text layer", "MuPDF word boxes", modules=("pymupdf",)),
        EngineInfo(
            "pdfium",
            "text layer",
            "PDFium, Chrome's PDF engine",
            modules=("pypdfium2",),
        ),
        EngineInfo("camelot", "text layer", "camelot table finder", modules=("camelot",)),
        EngineInfo(
            "tabula",
            "text layer",
            "tabula-java (needs Java)",
            modules=("tabula", "jpype"),
            programs=("java",),
            extra="tabula",
        ),
        EngineInfo("tesseract", "pixels (OCR)", "Tesseract OCR, CPU", programs=("tesseract",)),
        EngineInfo(
            "chandra",
            "pixels (OCR)",
            "Chandra OCR 2 model, GPU (CUDA or Apple)",
            modules=("chandra", "torch", "transformers"),
            extra="chandra",
        ),
        EngineInfo(
            "paddleocr",
            "pixels (OCR)",
            "PaddleOCR, CPU",
            modules=("paddleocr",),
            extra="paddleocr",
        ),
        EngineInfo(
            "ocrmac",
            "pixels (OCR)",
            "Apple Vision OCR",
            modules=("ocrmac",),
            extra="ocrmac",
            platforms=_mac,
            platform_note="macOS only",
        ),
        EngineInfo(
            "glmocr",
            "pixels (OCR)",
            "GLM-OCR model via MLX",
            modules=("mlx_vlm",),
            extra="glmocr",
            platforms=_apple_silicon,
            platform_note="Apple Silicon Macs only",
        ),
    ]
}
OCR_ENGINES = [n for n, e in KNOWN.items() if e.reads.startswith("pixels")]


def _system_install(program: str) -> str:
    """Install command for a system program on this platform."""
    pkg = {
        "pdftotext": (
            "poppler",
            "poppler-utils",
            "conda install -c conda-forge poppler",
        ),
        "tesseract": (
            "tesseract",
            "tesseract-ocr",
            "winget install UB-Mannheim.TesseractOCR",
        ),
        "java": ("openjdk", "default-jre", "winget install Microsoft.OpenJDK.21"),
    }
    brew, apt, win = pkg.get(program, (program, program, f"install {program}"))
    if sys.platform == "darwin":
        return f"brew install {brew}"
    if sys.platform.startswith("win"):
        return win
    return f"sudo apt install {apt}  (or your system's package manager)"


@dataclass(frozen=True)
class EngineStatus:
    """One engine's state on this machine."""

    name: str
    installed: bool
    default: bool
    reads: str
    about: str
    fix: str  # how to install it ("" when installed)


def status(name: str) -> EngineStatus:
    """Installed? and how to fix it, without importing heavy modules."""
    default = name in DEFAULTS
    info = KNOWN.get(name)
    if info is None:  # registered by the user's own code
        return EngineStatus(name, True, default, "custom", "registered with @register", "")
    if info.platforms and not info.platforms():
        return EngineStatus(
            name,
            False,
            default,
            info.reads,
            info.about,
            f"not available: {info.platform_note}",
        )
    missing_mods = [m for m in info.modules if find_spec(m) is None]
    missing_progs = [p for p in info.programs if shutil.which(p) is None]
    fixes = []
    if missing_mods:
        fixes.append(PIP.format(info.extra) if info.extra else "pip install --upgrade pdfexorcist")
    fixes += [_system_install(p) for p in missing_progs]
    return EngineStatus(
        name,
        not fixes,
        default,
        info.reads,
        info.about,
        " and ".join(dict.fromkeys(fixes)),
    )


def all_status() -> list[EngineStatus]:
    """Every registered engine: defaults first, then opt-in, in registry order."""
    names = list(EXTRACTORS)
    names.sort(key=lambda n: n not in DEFAULTS)
    return [status(n) for n in names]


def installed_ocr() -> list[str]:
    """OCR engines that can run here."""
    return [n for n in OCR_ENGINES if n in EXTRACTORS and status(n).installed]
