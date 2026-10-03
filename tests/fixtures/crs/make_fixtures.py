"""Build the CRS fixture."""

import csv
import re
import sys
from pathlib import Path

import pandas as pd
import pymupdf

HERE = Path(__file__).parent
COLS = [f"{a}_{s}" for a in ("Rural", "Urban", "Total") for s in ("Male", "Female", "Person")]
# parquet name -> the name the page prints, where they differ
PRINTED = {
    "Andaman & Nicobar Islands": "A & N Islands",
    "Dadra & Nagar Haveli & Daman & Diu": "Dadra and Nagar Haveli and Daman and Diu",
}


def state_key(name: str) -> str:
    """The parser's state key for a parquet name."""
    return re.sub(r"[^a-z]", "", PRINTED.get(name, name).lower())


def main(project: Path) -> None:
    pq = pd.read_parquet(project / "inst" / "extdata" / "crs_state.parquet")
    manifest = list(csv.DictReader((HERE / "manifest.csv").open(encoding="utf-8")))
    out = []
    for fixture in dict.fromkeys(m["fixture"] for m in manifest):
        rows = [m for m in manifest if m["fixture"] == fixture]
        src = pymupdf.open(project / "data-raw" / "pdfs" / rows[0]["source_pdf"])
        doc = pymupdf.open()
        for m in rows:
            page = int(m["source_page"])
            doc.insert_pdf(src, from_page=page - 1, to_page=page - 1)
        doc.subset_fonts()
        doc.save(HERE / fixture, garbage=4, deflate=True)
        for fixture_page, m in enumerate(rows, start=1):
            d = pq[(pq.year == int(m["year"])) & (pq["table"] == int(m["table"]))]
            for r in d.itertuples():
                for c in COLS:
                    v = getattr(r, c)
                    out.append(
                        {
                            "fixture": fixture,
                            "page": fixture_page,
                            "table": m["table"],
                            "state": r.State,
                            "state_key": state_key(r.State),
                            "col": c,
                            "value": "-" if pd.isna(v) else f"{v:.0f}",
                            "crsindia": "" if pd.isna(v) else f"{v:.0f}",
                        }
                    )
    pd.DataFrame(out).to_csv(HERE / "expected.csv", index=False)


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser())
