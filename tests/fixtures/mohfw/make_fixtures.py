"""Build the MoHFW fixtures."""

import csv
import sys
from pathlib import Path

import pandas as pd
import pymupdf

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[2] / "examples" / "census_mohfw_state"))

from mohfw_state_projection import parse  # noqa: E402

from pdfexorcist.extractors import EXTRACTORS  # noqa: E402


def _pages(spec: str) -> range:
    """ "165-166" -> range(165, 167)."""
    a, _, b = spec.partition("-")
    return range(int(a), int(b or a) + 1)


def main(pdf: Path, censusindia: Path) -> None:
    src = pymupdf.open(pdf)
    ci = pd.read_csv(censusindia / "data-raw" / "source" / "state_age_projections.csv.gz")
    ci = ci.melt(
        id_vars=["state_name_harmonized", "age_group", "year"],
        value_vars=["males", "females"],
        var_name="sex",
        value_name="censusindia",
    )
    ci["sex"] = ci.sex.map({"males": "Male", "females": "Female"})
    out = []
    for m in csv.DictReader((HERE / "manifest.csv").open()):
        pages = _pages(m["source_pages"])
        doc = pymupdf.open()
        doc.insert_pdf(src, from_page=pages[0] - 1, to_page=pages[-1] - 1)
        doc.subset_fonts()
        doc.save(HERE / m["fixture"], garbage=4, deflate=True)
        printed = {
            (r["year"], r["age"], r["sex"]): r["value"]
            for r in parse(EXTRACTORS["pymupdf"](HERE / m["fixture"]))
        }
        want = ci[ci.state_name_harmonized == m["state"]]
        assert len(want) == 204, (m["state"], len(want))
        for r in want.itertuples():
            ours = "" if pd.isna(r.censusindia) else str(int(r.censusindia))
            out.append(
                {
                    "fixture": m["fixture"],
                    "state": m["state"],
                    "year": r.year,
                    "age": r.age_group,
                    "sex": r.sex,
                    "value": printed[(r.year, r.age_group, r.sex)],
                    "censusindia": ours,
                }
            )
    df = pd.DataFrame(out)
    print(df.assign(diff=df.value != df.censusindia).groupby("fixture")["diff"].sum())
    df.to_csv(HERE / "expected.csv", index=False)


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser())
