"""Build the IIPS fixtures."""

import csv
import sys
from pathlib import Path

import pandas as pd
import pymupdf

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[2] / "examples" / "census_iips_district"))
from iips_district_projection import KEY, TOTAL, parse  # noqa: E402

from pdfexorcist import extract  # noqa: E402


def _true_years(block_years: str) -> list[list[str]]:
    """'2022-2026;2027-2031' -> [['2022', ..., '2026'], ['2027', ..., '2031']]."""
    out = []
    for span in block_years.split(";"):
        a, b = map(int, span.split("-"))
        out.append([str(y) for y in range(a, b + 1)])
    return out


def _censusindia(project: Path) -> dict[tuple[str, str, str, str, str], str]:
    """(state, district, age, year, sex) -> censusindia value ('' when NA)."""
    d = pd.read_csv(
        project / "data-raw" / "source" / "district_2011_age_projections.csv.gz",
        dtype={"age_group": str},
    )
    out = {}
    for r in d.itertuples():
        for sex, v in (("Males", r.males), ("Females", r.females)):
            out[(r.state_name_harmonized, r.district, r.age_group, str(r.year), sex)] = (
                "" if pd.isna(v) else f"{v:.0f}"
            )
    return out


def main(report: Path, project: Path) -> None:
    ci = _censusindia(project)
    src = pymupdf.open(report)
    rows = []
    for m in csv.DictReader((HERE / "manifest.csv").open()):
        page = int(m["source_page"])
        doc = pymupdf.open()
        doc.insert_pdf(src, from_page=page - 1, to_page=page - 1)
        doc.subset_fonts()
        doc.save(HERE / m["fixture"], garbage=4, deflate=True)
        years = _true_years(m["block_years"])
        res = extract(HERE / m["fixture"], parse=parse, key=KEY)
        res = res[(res.status == "verified") & (res.age != TOTAL)]
        for r in res.itertuples():
            printed = sorted(set(res[res.block == r.block].year))
            year = years[r.block][printed.index(r.year)]
            have = ci.get((m["state"], m["censusindia_district"], r.age, year, r.sex), "")
            fix = "" if have == r.value else "absent" if have == "" else "corrected"
            rows.append(
                {
                    "fixture": m["fixture"],
                    "page": r.page,
                    "block": r.block,
                    "district": m["district"],
                    "printed_year": r.year,
                    "year": year,
                    "sex": r.sex,
                    "age": r.age,
                    "value": r.value,
                    "censusindia": have,
                    "fix": fix,
                }
            )
    pd.DataFrame(rows).to_csv(HERE / "expected.csv", index=False)


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser())
