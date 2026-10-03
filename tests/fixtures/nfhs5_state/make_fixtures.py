"""Build the NFHS-5 State fixtures."""

import csv
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd
import pymupdf

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[2] / "examples" / "nfhs5"))
from nfhs5_factsheet import KEY, STATE_COLUMNS, checks, parse  # noqa: E402

from pdfexorcist import extract  # noqa: E402

# class e: the CSV has the December 2020 edition's literacy; this sheet prints the revised value
LITERACY = "e"
BIHAR_LIT = "evidence/bihar_literacy_2021.png, evidence/bihar_literacy_2020.png"
# (fixture, fixture page, indicator, column) -> (printed value, class or "" when
# the CSV agrees, evidence)
CHECKED: dict[tuple[str, int, int, str], tuple[str, str, str]] = {
    **{
        ("nfhs5_bihar_p3-6.pdf", 1, n, c): (v, LITERACY, BIHAR_LIT)
        for n, vals in ((14, ("72.9", "51.6", "55.0")), (15, ("81.8", "74.9", "76.4")))
        for c, v in zip(STATE_COLUMNS, vals, strict=False)
    },
    # camelot reads row 68 with row 40's numbers, leaving the vote unresolved
    **{
        ("nfhs5_chandigarh_p3-6.pdf", 2, 68, c): (v, "", "unresolved, read on the page")
        for c, v in zip(STATE_COLUMNS, ("(7.2)", "*", "(7.1)", "(6.9)"), strict=True)
    },
}


def download(url: str, folder: Path) -> Path:
    """The source PDF, fetched once into folder under its IIPS file name."""
    name = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["link"][0]
    out = folder / name
    if not out.exists():
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=300).read()
        if not data.startswith(b"%PDF"):
            raise ValueError(f"{url}: not a PDF")
        out.write_bytes(data)
    return out


def same(printed: str, value: str, note: str | None = None) -> bool:
    """Does the CSV value (and, for districts, its note) say what the page prints?"""
    if printed == "*":
        return value == "" and (note is None or note.startswith("Percentage not shown"))
    if printed == "na":
        return value == "" and not note
    if value == "":
        return False
    bracket = printed.startswith("(")
    number = float(printed.strip("()").replace(",", ""))
    ok_note = note is None or note.startswith("Based on 25-49") == bracket
    return float(value) == number and ok_note


def cut(src: Path, pages: str, out: Path) -> None:
    first, last = (int(p) for p in pages.split("-"))
    doc = pymupdf.open()
    doc.insert_pdf(pymupdf.open(src), from_page=first - 1, to_page=last - 1)
    doc.subset_fonts()
    doc.save(out, garbage=4, deflate=True)


def main(downloads: Path, nfhs5: Path) -> None:
    manifest = list(csv.DictReader((HERE / "manifest.csv").open(encoding="utf-8")))
    states = pd.read_csv(nfhs5 / "NFHS-5-States.csv", dtype=str, keep_default_na=False)
    states["indicator_no"] = states.indicator.str.extract(r"^(\d+)\.", expand=False).astype(int)
    out, used = [], set()
    for m in manifest:
        cut(download(m["source_url"], downloads), m["source_pages"], HERE / m["fixture"])
        res = extract(HERE / m["fixture"], parse=parse, key=KEY, checks=checks())
        assert (res.failed != "").sum() == 0, m["fixture"]
        voted = {
            (int(p), int(n), c): (v, s)
            for p, n, c, v, s in zip(
                res.page, res.indicator_no, res.column, res.value, res.status, strict=True
            )
        }
        page_of = {n: p for p, n, _ in voted}
        ref = states[states.state == m["geography"]].set_index("indicator_no")
        assert len(ref) == 131, (m["fixture"], len(ref))
        for n in range(1, 132):
            row = {
                "fixture": m["fixture"],
                "page": page_of[n],
                "geo": m["geography"],
                "indicator_no": n,
                "indicator": ref.loc[n, "indicator"],
            }
            notes = []
            for col in STATE_COLUMNS:
                key = (m["fixture"], page_of[n], n, col)
                v, status = voted.get(key[1:], ("", "missing"))
                csv_value = ref.loc[n, col]
                if key in CHECKED:
                    used.add(key)
                    printed, cls, evidence = CHECKED[key]
                    assert status != "verified" or v == printed, (key, v, printed)
                    assert same(printed, csv_value) == (not cls), (key, printed, csv_value)
                    notes.append(f"{col}: {cls or 'agrees'} ({evidence})")
                else:
                    assert status == "verified" and same(v, csv_value), (key, v, status, csv_value)
                    printed = v
                row[col], row[f"csv_{col}"] = printed, csv_value
            row["checked"] = "; ".join(notes)
            out.append(row)
    assert used == set(CHECKED), set(CHECKED) - used
    pd.DataFrame(out).to_csv(HERE / "expected.csv", index=False)


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser())
