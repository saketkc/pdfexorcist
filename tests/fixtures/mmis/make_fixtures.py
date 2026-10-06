"""Build the MMIS fixture and its expected values, from pdftotext -layout."""

import csv
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pymupdf

from pdfexorcist.pages import parse_pages

HERE = Path(__file__).parent
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
TITLE = re.compile(r"GRAPH \d: MONTH WISE TREND OF (\w+) IN (.+?)\s*$")
ROW = re.compile(r"^\s*(BSE|TPC|TPR|PF) (Current Year|3 Year Average)\s+([\d.\s]+)$")
SERIES = {"Current Year": "current", "3 Year Average": "avg3"}


def main(pdf: Path) -> None:
    src = pymupdf.open(pdf)
    out = []
    for m in csv.DictReader((HERE / "manifest.csv").open(encoding="utf-8")):
        pages = parse_pages(m["source_pages"])
        doc = pymupdf.open()
        for p in pages:
            doc.insert_pdf(src, from_page=p - 1, to_page=p - 1)
        doc.save(HERE / m["fixture"], garbage=4, deflate=True)
        cut = pymupdf.open(HERE / m["fixture"])
        assert all(
            cut[k].get_text("words") == src[p - 1].get_text("words") for k, p in enumerate(pages)
        )
        text = subprocess.run(
            ["pdftotext", "-layout", HERE / m["fixture"], "-"],
            capture_output=True, text=True, check=True,
        ).stdout  # fmt: skip
        title = None
        for line in text.splitlines():
            if t := TITLE.search(line):
                title = t
            elif r := ROW.match(line):
                assert title is not None
                for month, v in zip(MONTHS, r.group(3).split(), strict=False):
                    out.append({
                        "fixture": m["fixture"], "area": title.group(2),
                        "indicator": title.group(1), "printed": r.group(1),
                        "series": SERIES[r.group(2)], "month": month, "value": v,
                    })  # fmt: skip
    df = pd.DataFrame(out)
    assert not df.duplicated(["fixture", "area", "indicator", "series", "month"]).any()
    df.to_csv(HERE / "expected.csv", index=False)
    print(df.groupby(["area", "indicator", "series"]).size())


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser())
