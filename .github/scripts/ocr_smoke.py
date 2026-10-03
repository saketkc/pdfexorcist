"""OCR smoke test."""

import sys
from collections import Counter
from pathlib import Path

from pdfexorcist.extractors import EXTRACTORS
from pdfexorcist.rows import is_value

MIN_VALUES = 150  # fewest value tokens Tesseract must read from the page
MIN_SHARED = 0.8  # share of Tesseract's values that pdftotext also reads


def values(engine: str, pdf: Path) -> Counter:
    """Multiset of value tokens one engine reads from the PDF."""
    return Counter(
        text.strip()
        for _, lines in EXTRACTORS[engine](pdf)
        for line in lines
        for _, cell in line
        for text in cell.split()
        if is_value(text.strip())
    )


def main() -> int:
    pdf = Path(sys.argv[1])
    ocr, text = values("tesseract", pdf), values("pdftotext", pdf)
    n = sum(ocr.values())
    shared = sum((ocr & text).values()) / max(n, 1)
    print(f"tesseract: {n} values, {shared:.1%} also read by pdftotext")
    if n < MIN_VALUES or shared < MIN_SHARED:
        print(f"FAIL: need >= {MIN_VALUES} values and >= {MIN_SHARED:.0%} shared")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
