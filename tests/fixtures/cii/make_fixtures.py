"""Build the CII fixtures."""

import csv
import sys
from pathlib import Path

import pandas as pd
import pymupdf

HERE = Path(__file__).parent

# Printed order (serial 1..36) in the 2021-2024 volumes, as parquet labels.
STATES: list[str] = [
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chhattisgarh",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
    "A & N Islands",
    "Chandigarh",
    "DNH&DD",
    "Delhi",
    "Jammu & Kashmir",
    "Ladakh",
    "Lakshadweep",
    "Puducherry",
]
TOTALS = {
    "Total (States)": "totalstates",
    "Total (UTs)": "totaluts",
    "All India": "totalallindia",
}
ALIASES = {
    "Jammu & Kashmir*": "Jammu & Kashmir",
    "Ladakh @": "Ladakh",
    "Dadra & Nagar Haveli": "DNH&DD",
    "Dadra and Nagar Haveli and Daman and Diu": "DNH&DD",
}

# fixture -> parquet metric -> printed column
METRICS: dict[str, dict[str, int]] = {
    "cii_2021_1A.1_p43": {
        "2019": 3,
        "2020": 4,
        "2021": 5,
        "Mid-Year Projected Population (in Lakhs) (2021)": 6,
        "Rate of Cognizable Crimes (IPC) (2021) (2021)": 7,
        "Chargesheeting Rate (2021) (2021) (2021)": 8,
    },
    "cii_2023_1A.4_p47": {
        "Murder I": 12,
        "(Sec.302 V": 13,
        "IPC) R": 14,
        "Offences Culpable Amounting I": 15,
        "affecting the Homicide to Murder IPC) V": 16,
        "Human Body not (Sec. 304 R": 17,
        "Causing Causing (Sec.304-A I": 18,
        "Death by Death by IPC) V": 19,
        "Negligence Negligence (Total) R": 20,
    },
    "cii_2024_1C.2_p264": {
        "Rape": 3,
        "col4": 4,
        "col5": 5,
        "col6": 6,
        "col7": 7,
        "Murder": 8,
        "Culpable": 9,
        "Attempt to": 10,
    },
}


def row_key(label: str) -> str:
    """Parquet label -> the parser's row key (printed serial, or a total's key)."""
    if label in TOTALS:
        return TOTALS[label]
    return str(STATES.index(ALIASES.get(label, label)) + 1)


def main(project: Path) -> None:
    pq = pd.read_parquet(project / "data" / "parquet" / "cii_long.parquet")
    manifest = list(csv.DictReader((HERE / "manifest.csv").open()))
    out = []
    for m in manifest:
        year, page = int(m["year"]), int(m["source_page"])
        src = pymupdf.open(project / "data" / m["source_pdf"])
        doc = pymupdf.open()
        doc.insert_pdf(src, from_page=page - 1, to_page=page - 1)
        doc.subset_fonts()  # every engine reads the subset page as it reads the full one
        doc.save(HERE / m["fixture"], garbage=4, deflate=True)
        vol = int(m["source_pdf"].split("_vol")[1][0])
        d = pq[
            (pq.year == year) & (pq.volume == vol) & (pq.table_id == m["table"]) & (pq.page == page)
        ]
        d = d[~d.label.str.startswith("'")]  # footnote text the old extractor kept as a row
        cols = METRICS[m["fixture"].removesuffix(".pdf")]
        assert set(d.metric) == set(cols), (m["fixture"], set(d.metric) ^ set(cols))
        out.extend(
            {
                "fixture": m["fixture"],
                "row": row_key(r.label),
                "state": ALIASES.get(r.label, r.label),
                "col": cols[r.metric],
                "value": f"{r.value:.12g}",
                "confirmed": r.confirmed,
            }
            for r in d.itertuples()
        )
    pd.DataFrame(out).sort_values(["fixture", "col"], kind="stable").to_csv(
        HERE / "expected.csv", index=False
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser())
