"""Build the NEET toppers fixture."""

import csv
import sys
from pathlib import Path

import pymupdf

from pdfexorcist.fetch import download
from pdfexorcist.pages import parse_pages

HERE = Path(__file__).parent


def main(pdf: Path | None) -> None:
    for m in csv.DictReader((HERE / "manifest.csv").open(encoding="utf-8")):
        src = pymupdf.open(pdf or download(m["url"]))
        pages = parse_pages(m["source_pages"])
        doc = pymupdf.open()
        doc.insert_pdf(src, from_page=pages[0] - 1, to_page=pages[-1] - 1)
        doc.save(HERE / m["fixture"], garbage=4, deflate=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None)
