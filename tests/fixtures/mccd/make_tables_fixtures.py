"""Build the MCCD Table 2, 5 and 9 fixtures."""

import csv
import sys
from pathlib import Path

import pandas as pd
import pymupdf

HERE = Path(__file__).parent
PARQUET = {"2": "mccd_table_deaths", "5": "mccd_table_age", "9": "mccd_table_trend"}
COLUMN = {"2": "State", "5": "Age_Group", "9": "Trend_Year"}
AGES = {"NS": "N.S.", "Total": "TOTAL"}
# printed as two columns, published merged under one name: not comparable
MERGED = {"Dadra & Nagar Haveli & Daman & Diu"}

T2_RIGHT = [  # page 69 of the 2019 report, left to right
    "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram",
    "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu",
    "Telangana", "Tripura", "Uttarakhand", "Uttar Pradesh", "West Bengal",
]  # fmt: skip
T2_ALL = {  # ALL CAUSES on page 69, read off the page
    "M": "168 28643 171883 1358 3646 2116 192 26909 5751 21584 41139 904 167547 39933 6262 "
    "3529 34731 46820",
    "F": "154 16272 93249 655 2377 1312 81 16282 3704 16023 21643 606 111340 23303 3996 "
    "2347 26604 30783",
    "T": "322 44915 265132 2013 6023 3428 273 43191 9455 37607 62782 1510 278887 63236 10258 "
    "5876 61335 77603",
}
T5_AGES = ["<1", "1-4", "5-14", "15-24", "25-34", "35-44", "45-54", "55-64", "65-69", "70+",
           "N.S.", "TOTAL"]  # fmt: skip
T5_ROWS = {  # 2018 Table 5, read off the page
    ("XV", "F"): "0 0 19 1921 3092 1267 399 0 0 0 193 6891",
    ("XV", "T"): "0 0 19 1921 3092 1267 399 0 0 0 193 6891",
    ("ALL", "T"): "114955 16332 22993 57366 86911 127381 201342 264399 151802 390183 22359 1456023",
}
PRINTED: dict[str, dict[tuple[str, str, str], str]] = {
    "mccd_2019_t2_p68-69.pdf": {
        ("ALL", s, st): v
        for s, row in T2_ALL.items()
        for st, v in zip(T2_RIGHT, row.split(), strict=True)
    },
    "mccd_2018_t5_p104.pdf": {
        (g, s, a): v
        for (g, s), row in T5_ROWS.items()
        for a, v in zip(T5_AGES, row.split(), strict=True)
    },
    "mccd_2019_t9_p194.pdf": {},
}


def _group(t: pd.DataFrame, table: str) -> pd.Series:
    if table == "2":
        return t.ICD10_Code.replace("", "ALL")
    return t.Major_Group.str.rstrip(".").where(t.Cause_Of_Death.str.upper() != "ALL CAUSES", "ALL")


def main(project: Path) -> None:
    manifest = list(csv.DictReader((HERE / "mccd_tables_manifest.csv").open(encoding="utf-8")))
    out = []
    for m in manifest:
        first, _, last = m["source_pages"].partition("-")
        src = pymupdf.open(project / "data-raw" / "reports" / m["source"])
        doc = pymupdf.open()
        doc.insert_pdf(src, from_page=int(first) - 1, to_page=int(last or first) - 1)
        doc.subset_fonts()
        doc.save(HERE / m["fixture"], garbage=4, deflate=True)

        table, year = m["table"], int(m["year"])
        pq = pd.read_parquet(project / "inst" / "extdata" / f"{PARQUET[table]}.parquet")
        t = pq[(pq.Year == year) & ~pq.State.isin(MERGED)] if table == "2" else pq[pq.Year == year]
        cols = t[COLUMN[table]].astype(str).replace(AGES if table == "5" else {})
        have = {
            (g, s, c): d
            for g, s, c, d in zip(_group(t, table), t.Sex, cols, t.Deaths, strict=True)
            if pd.notna(d)
        }
        printed = PRINTED[m["fixture"]]
        for k in sorted({*have, *printed}):
            ours = f"{have[k]:.0f}" if k in have else ""
            value = printed.get(k, ours)
            fix = "" if value == ours else "corrected" if ours else "absent"
            group, sex, column = k
            out.append([m["fixture"], table, group, sex, column, value, ours, fix])
    cols = ["fixture", "table", "group", "sex", "column", "value", "mccdindia", "fix"]
    pd.DataFrame(out, columns=cols).to_csv(HERE / "mccd_tables_expected.csv", index=False)


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser())
