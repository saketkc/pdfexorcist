"""Build the NFHS-6 district fixtures."""

import csv
import sys
from pathlib import Path

import pandas as pd
import pymupdf

HERE = Path(__file__).parent
# (fixture, fixture page, indicator, column) -> (printed value, evidence)
CORRECTIONS: dict[tuple[str, int, int, str], tuple[str, str]] = {}


def main(repo: Path) -> None:
    manifest = list(csv.DictReader((HERE / "manifest.csv").open(encoding="utf-8")))
    pq = pd.read_parquet(repo / "parquet" / "nfhs6_districts.parquet")
    long = pd.read_csv(
        repo / "districts" / "csv" / "factsheets_long.csv", dtype=str, keep_default_na=False
    )
    direction = pd.read_csv(repo / "csv" / "indicator_direction.csv", dtype=str)
    direction = direction[direction.district_no.notna()]
    state_no = dict(zip(direction.district_no.astype(int), direction.state_no, strict=True))
    out = []
    for m in manifest:
        first, last = (int(p) for p in m["source_pages"].split("-"))
        src = pymupdf.open(repo / m["source_pdf"])
        doc = pymupdf.open()
        doc.insert_pdf(src, from_page=first - 1, to_page=last - 1)
        doc.subset_fonts()
        doc.save(HERE / m["fixture"], garbage=4, deflate=True)
        g = pq[(pq.state == m["state"]) & (pq.district == m["district"])]
        lg = long[(long.state == m["state"]) & (long.district == m["district"])]
        assert len(lg) == len(g) and len(g) in (93, 186), (m["fixture"], len(g), len(lg))
        cells = {
            (int(r.indicator_no), r.column): (int(r.page), r.value, r.sources)
            for r in lg.itertuples()
        }
        for r in g.itertuples():
            col = "nfhs6_total" if r.round == "NFHS-6" else "nfhs5_total"
            page, value, _ = cells[(r.indicator_no, col)]
            assert value == r.printed, (m["fixture"], r.indicator_no, col, value, r.printed)
        for no in sorted({n for n, _ in cells}):
            page, v6, src6 = cells[(no, "nfhs6_total")]
            k = page - first + 1
            row = {
                "fixture": m["fixture"],
                "page": k,
                "geo": f"{m['district']}, {m['state']}",
                "indicator_no": no,
                "state_no": state_no.get(no, ""),
                "indicator": g[g.indicator_no == no].indicator.iat[0],
                "area": "Total",
                "nfhs6": v6,
                "nfhs5": "",
                "repo_sources": f"nfhs6_total: {src6}",
                "correction": "",
            }
            if (no, "nfhs5_total") in cells:
                p5, v5, src5 = cells[(no, "nfhs5_total")]
                assert p5 == page
                row["nfhs5"] = v5
                row["repo_sources"] += f"; nfhs5_total: {src5}"
            corrected = []
            for rnd, col in (("nfhs6", "nfhs6_total"), ("nfhs5", "nfhs5_total")):
                fixed, why = CORRECTIONS.get((m["fixture"], k, no, col), (None, ""))
                if fixed is not None:
                    corrected.append(f"{col}: repo {row[rnd] or 'blank'}, printed {fixed} ({why})")
                    row[rnd] = fixed
            row["correction"] = "; ".join(corrected)
            out.append(row)
    pd.DataFrame(out).to_csv(HERE / "expected.csv", index=False)


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser())
