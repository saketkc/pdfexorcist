"""Build the Pravah fixture."""

import csv
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pymupdf

from pdfexorcist.pages import parse_pages

HERE = Path(__file__).parent
COLS = ["date", "time", "dead", "live_cap", "gross_cap", "live", "gross", "pct_live",
        "pct_live_last_year"]  # fmt: skip
NUM = r"(\d+(?:\.\d+)?)"
ROW = re.compile(
    r"^(\d+)\s+(.+?)\s+(\d\d/\d\d/\d{4})\s+(\d{1,2}:\d\d\s*[AP]M)"
    + rf"\s+{NUM}" * 5
    + rf"\s+{NUM}\s*%\s+{NUM}\s*%$"
)
# first line of a wrapped name -> the whole name, as printed
WRAPPED = {
    "Kinwat ( Mangrul ) H": "Kinwat ( Mangrul ) H L B",
    "Wanjarkheda High": "Wanjarkheda High level Barrage",
}


def _shrink_images(doc: pymupdf.Document) -> None:
    """Scale every image (the logo and its mask) to a quarter of its width and height."""
    xrefs = {x for p in doc for img in p.get_images(full=True) for x in img[:2] if x}
    for x in xrefs:
        pix = pymupdf.Pixmap(doc, x)
        small = pymupdf.Pixmap(pix, pix.width // 4, pix.height // 4, None)
        doc.update_stream(x, small.samples)
        doc.xref_set_key(x, "Width", str(small.width))
        doc.xref_set_key(x, "Height", str(small.height))
        doc.xref_set_key(x, "DecodeParms", "null")


def main(pdf: Path) -> None:
    src = pymupdf.open(pdf)
    out = []
    for m in csv.DictReader((HERE / "manifest.csv").open(encoding="utf-8")):
        pages = parse_pages(m["source_pages"])
        doc = pymupdf.open()
        doc.insert_pdf(src, from_page=pages[0] - 1, to_page=pages[-1] - 1)
        doc = pymupdf.open("pdf", doc.tobytes(garbage=4))  # one copy of the logo, not one a page
        _shrink_images(doc)
        doc.save(HERE / m["fixture"], garbage=4, deflate=True)
        cut = pymupdf.open(HERE / m["fixture"])
        assert all(
            cut[k].get_text("words") == src[p - 1].get_text("words") for k, p in enumerate(pages)
        )
        for k in range(1, len(pages) + 1):
            text = subprocess.run(
                ["pdftotext", "-layout", "-f", str(k), "-l", str(k), HERE / m["fixture"], "-"],
                capture_output=True, text=True, check=True,
            ).stdout  # fmt: skip
            for line in text.splitlines():
                r = ROW.match(line.strip())
                if not r:
                    continue
                name = re.sub(r"\s+", " ", r.group(2))
                row = {"fixture": m["fixture"], "page": k, "sr": r.group(1),
                       "dam": WRAPPED.get(name, name)}  # fmt: skip
                vals = (re.sub(r"\s+", " ", g) for g in r.groups()[2:])
                row |= dict(zip(COLS, vals, strict=True))
                parts = float(row["dead"]) + float(row["live"])
                row["note"] = (
                    f"gross {row['gross']} is not dead + live ({parts:.2f})"
                    if abs(parts - float(row["gross"])) > 0.015
                    else ""
                )
                out.append(row)
    df = pd.DataFrame(out)
    assert not df.duplicated(["fixture", "dam"]).any()
    df.to_csv(HERE / "expected.csv", index=False)
    print(df.groupby("fixture").size(), df[df.note != ""][["dam", "note"]], sep="\n")


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser())
