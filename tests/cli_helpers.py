"""CLI runner and a synthetic PDF."""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pymupdf
from typer.testing import CliRunner, Result

from pdfexorcist.cli import app

runner = CliRunner()

STATES = [
    ("Kerala", "1,020", "7", "8.0"),
    ("Goa", "12", "3", "4.5"),
    ("Total", "1,032", "10", "12.5"),
]


def make_pdf(path: Path, pages: Sequence[Sequence[tuple]], titles: Sequence[str] = ()) -> Path:
    """A text-layer PDF: each page a title line and rows of (label, values...)."""
    doc = pymupdf.open()
    for i, rows in enumerate(pages):
        page = doc.new_page()
        if i < len(titles):
            page.insert_text((50, 60), titles[i])
        for j, row in enumerate(rows):
            for x, text in zip((50, 250, 330, 410), row, strict=False):
                page.insert_text((x, 100 + 20 * j), text)
    doc.save(path)
    return path


def run(args: list[str], **kw: Any) -> Result:
    return runner.invoke(app, args, **kw)
