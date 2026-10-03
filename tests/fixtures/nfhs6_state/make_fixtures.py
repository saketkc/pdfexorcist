"""Build the NFHS-6 State fixtures."""

import ast
import csv
import sys
from pathlib import Path

import pandas as pd
import pymupdf

HERE = Path(__file__).parent
SOURCE = "NFHS 6 factsheet.pdf"
# indicators on each of a geography's three pages
PAGE_RANGES = [range(1, 41), range(41, 74), range(74, 102)]
AREAS = {"Urban": "nfhs6_urban", "Rural": "nfhs6_rural", "Total": "nfhs6_total"}
# (fixture, fixture page, indicator, column) -> (printed value, evidence)
CORRECTIONS: dict[tuple[str, int, int, str], tuple[str, str]] = {}


def _literal(script: Path, name: str) -> list:
    """Read a top-level nfhs6 list literal without running its script."""
    for node in ast.parse(script.read_text()).body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == name:
            return ast.literal_eval(node.value)
    raise KeyError(name)


def _fixes(repo: Path) -> dict[tuple[str, int, str], list[str]]:
    """(repo csv, indicator, column) -> what nfhs6's fix scripts did to the cell."""
    out: dict[tuple[str, int, str], list[str]] = {}

    def add(f: str, no: int, col: str, text: str) -> None:
        out.setdefault((f, int(no), col), []).append(text)

    cols = [*AREAS.values(), "nfhs5_total"]
    for f, no, *vals in _literal(repo / "09_final_patches.py", "PATCHES"):
        for col, v in zip(cols, vals, strict=False):
            add(f, no, col, f"09_final_patches set {v}")
    for f, no, u, r, t, page in _literal(repo / "15_verified_corrections.py", "CORR"):
        for col, v in zip(cols, (u, r, t), strict=False):
            add(f, no, col, f"15_verified_corrections set {v} (PDF p{page})")
    for r in csv.DictReader((repo / "csv" / "ocr_reference_fixes.csv").open()):
        add(
            r["file"],
            r["indicator_no"],
            AREAS[r["area"]],
            f"20_fix_nfhs6_ocr_from_references {r['old_value']} -> {r['new_value']}",
        )
    for r in csv.DictReader((repo / "csv" / "compendium_state_fixes.csv").open()):
        old = r["old_value"] or "blank"
        add(
            r["file"],
            r["indicator_no"],
            r["column"],
            f"23_apply_compendium_state_fixes {old} -> {r['new_value']}",
        )
    return out


def _same(printed: str, repo: str) -> bool:
    """The repo CSV stores '(45.6)' as 45.6 and '*' as blank."""
    if printed == "*":
        return repo == ""
    return repo != "" and float(printed.strip("()")) == float(repo)


def main(repo: Path) -> None:
    manifest = list(csv.DictReader((HERE / "manifest.csv").open(encoding="utf-8")))
    pq = pd.read_parquet(repo / "parquet" / "nfhs6_states.parquet")
    fixes = _fixes(repo)
    src = pymupdf.open(repo / SOURCE)
    out = []
    for m in manifest:
        first, last = (int(p) for p in m["source_pages"].split("-"))
        doc = pymupdf.open()
        doc.insert_pdf(src, from_page=first - 1, to_page=last - 1)
        doc.subset_fonts()
        # the outlined page is all glyph paths: clean merges its streams
        doc.save(HERE / m["fixture"], garbage=4, deflate=True, clean=m["text_layer"] == "no")
        rows = pd.read_csv(repo / "csv" / m["repo_file"], dtype=str, keep_default_na=False)
        rows = rows.set_index(rows.indicator_no.astype(int))
        g = pq[pq.state == m["geography"]]
        printed = {
            (int(n), r, a): p
            for n, r, a, p in zip(g.indicator_no, g["round"], g.area, g.printed, strict=True)
        }
        for k, page in enumerate(range(first, last + 1), start=1):
            nos = PAGE_RANGES[(page - int(m["first_page_of_geo"])) % 3]
            for no in nos:
                for area, col in AREAS.items():
                    cells = {"nfhs6": (col, printed[(no, "NFHS-6", area)])}
                    if area == "Total":
                        cells["nfhs5"] = ("nfhs5_total", printed[(no, "NFHS-5", "Total")])
                    row = {
                        "fixture": m["fixture"],
                        "page": k,
                        "geo": m["geography"],
                        "indicator_no": no,
                        "indicator": rows.loc[no, "indicator"],
                        "area": area,
                        "nfhs6": "",
                        "nfhs5": "",
                        "fix": "",
                        "correction": "",
                    }
                    notes, corrected = [], []
                    for rnd, (c, v) in cells.items():
                        assert _same(v, rows.loc[no, c]), (m["fixture"], no, c, v, rows.loc[no, c])
                        fixed, why = CORRECTIONS.get((m["fixture"], k, no, c), (None, ""))
                        if fixed is not None:
                            corrected.append(f"{c}: repo {v or 'blank'}, printed {fixed} ({why})")
                            v = fixed
                        row[rnd] = v
                        notes += [f"{c}: {t}" for t in fixes.get((m["repo_file"], no, c), [])]
                    row["fix"], row["correction"] = "; ".join(notes), "; ".join(corrected)
                    out.append(row)
    pd.DataFrame(out).to_csv(HERE / "expected.csv", index=False)


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser())
