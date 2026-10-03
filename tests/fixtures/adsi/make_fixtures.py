"""Build the ADSI fixtures."""

import csv
import re
import sys
from pathlib import Path

import pandas as pd
import pymupdf

HERE = Path(__file__).parent
REPO = Path(
    sys.argv[1] if len(sys.argv) > 1 else Path.home() / "github" / "accidents_suicides_india"
)

# printed column heading (parquet metric) -> parser metric
METRIC = {
    "Forces of Nature": "nature",
    "Other Causes": "other",
    "Total Number of Accidental Deaths": "total",
    "Number of Suicides": "total",
    "Number of Accidental Deaths": "total",
    "Percentage Share in Total Deaths": "share",
    "Percentage Share in Total Suicides": "share",
    "Projected Mid-Year Population (in Lakh)": "pop",
    "Estimated Mid-Year Population (in Lakhs)": "pop",
    "Rate of Accidental Deaths (Col.5/Col.7)": "rate",
    "Rate of Suicides (Col.3/Col.5)": "rate",
    "Rate (Accidental Deaths Per Lakh) (col.3/col.5)": "rate",
}
TOTALS = {"All India": "totalallindia"}

# fixture -> {(row key, metric or "*"): note}: the cells PDF_VERIFIED_FIXES.md names
MISSING_2023 = [
    "arunachalpradesh",
    "bihar",
    "goa",
    "haryana",
    "jharkhand",
    "kerala",
    "maharashtra",
    "meghalaya",
    "nagaland",
    "punjab",
    "sikkim",
    "telangana",
    "uttarpradesh",
    "westbengal",
]
TRUNCATED_2024 = [
    "bihar",
    "himachalpradesh",
    "jammukashmir",
    "jharkhand",
    "ladakh",
    "lakshadweep",
    "mizoram",
    "sikkim",
    "telangana",
    "tripura",
]
NAMED = {
    "2023_t1.2_p35.pdf": {
        **{(k, "*"): "State missing before the fix (one of 14)" for k in MISSING_2023}
    },
    "2024_t1.2_p35.pdf": {
        **{(k, "*"): "label truncated before the fix (BIH, HIM, JAM...)" for k in TRUNCATED_2024},
        ("andhrapradesh", "pop"): "split number: 534.0 stored as 5 + 34.0",
        ("bihar", "pop"): "split number: 1292.1 stored as 1 + 292.1",
        ("telangana", "pop"): "split number: 383.2 stored as 3 + 83.2",
    },
    "2024_t2.2_p238.pdf": {
        ("andhrapradesh", "*"): "table missing before the fix (title uses an en dash)",
        ("totalallindia", "*"): "table missing before the fix (title uses an en dash)",
    },
    "1995_t2A_p6.pdf": {
        ("himachalpradesh", "total"): "was 1264; printed 1204",
        ("sikkim", "total"): "was 4887; printed 153",
        ("tamilnadu", "total"): "was 17437; printed 17421",
    },
}


def row_key(label: str) -> str:
    """Letters only, '&' dropped: 'A & N ISLANDS' == 'A N Islands', 'Total (UTs)' == 'Total Uts'."""
    return TOTALS.get(label) or re.sub(r"[^a-z]", "", label.lower())


def state_rows(d: pd.DataFrame, fixture: str) -> pd.DataFrame:
    """1995 2(A) also lists cities (Delhi twice): keep rows up to 'Total Uts'."""
    if not fixture.startswith("1995"):
        return d
    keys = d.label.astype(str).map(row_key).tolist()
    return d.iloc[: max(i for i, k in enumerate(keys) if k == "totaluts") + 1]


def main() -> None:
    pq = pd.read_parquet(REPO / "data" / "parquet" / "adsi_long.parquet")
    manifest = list(csv.DictReader((HERE / "manifest.csv").open()))
    out = []
    for m in manifest:
        src, page = REPO / m["source_pdf"], int(m["source_page"])
        if not (
            HERE / m["fixture"]
        ).exists():  # rewriting changes the bytes, and OCR caches key on them
            doc = pymupdf.open()
            doc.insert_pdf(pymupdf.open(src), from_page=page - 1, to_page=page - 1)
            doc.save(HERE / m["fixture"], garbage=4, deflate=True)
        d = pq[(pq.year == int(m["year"])) & (pq.table_id == m["table"]) & (pq.page == page)]
        d = state_rows(d[d.metric.astype(str).isin(METRIC)], m["fixture"])
        named = NAMED[m["fixture"]]
        # printed serial: States/UTs are numbered 1..36 in the order the page lists them
        order = [
            k for k in dict.fromkeys(d.label.astype(str).map(row_key)) if not k.startswith("total")
        ]
        for r in d.itertuples():
            k, metric = row_key(str(r.label)), METRIC[str(r.metric)]
            out.append(
                {
                    "fixture": m["fixture"],
                    "serial": "" if k.startswith("total") else order.index(k) + 1,
                    "row": k,
                    "metric": metric,
                    "value": r.value,
                    "note": named.get((k, metric)) or named.get((k, "*"), ""),
                }
            )
    df = pd.DataFrame(out)
    dup = df.duplicated(["fixture", "row", "metric"], keep=False)
    assert not dup.any(), df[dup]
    df.to_csv(HERE / "expected.csv", index=False)
    print(
        df.groupby("fixture").agg(
            cells=("value", "size"), named=("note", lambda s: (s != "").sum())
        )
    )


if __name__ == "__main__":
    main()
