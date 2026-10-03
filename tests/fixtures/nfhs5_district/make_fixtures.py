"""Build the NFHS-5 district fixtures."""

import csv
import importlib.util
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[2] / "examples" / "nfhs5"))
from nfhs5_factsheet import DISTRICT_COLUMNS, KEY, checks, parse  # noqa: E402

from pdfexorcist import extract  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "state_fixtures", HERE.parent / "nfhs5_state" / "make_fixtures.py"
)
_state = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_state)
cut, download, same = _state.cut, _state.download, _state.same

EVIDENCE = "../nfhs5_state/evidence/"
# (fixture, fixture page, printed indicator, column) -> (printed, class, evidence)
CHECKED: dict[tuple[str, int, int, str], tuple[str, str, str]] = {
    ("nfhs5_kangra_p31-33.pdf", 1, 16, "nfhs4_total"): ("2.4", "a", EVIDENCE + "kangra_16.png"),
    ("nfhs5_raigarh_p169-171.pdf", 3, 97, "nfhs5_total"): (
        "26.4",
        "a",
        EVIDENCE + "raigarh_97.png",
    ),
    ("nfhs5_raigarh_p169-171.pdf", 3, 97, "nfhs4_total"): ("na", "a", EVIDENCE + "raigarh_97.png"),
}
# Mahisagar's first page skips "10." and prints 11-32 for indicators 10-31.
RENUMBERED = {("nfhs5_mahisagar_p121-123.pdf", 1, n): n - 1 for n in range(11, 33)}


def main(downloads: Path, nfhs5: Path) -> None:
    manifest = list(csv.DictReader((HERE / "manifest.csv").open(encoding="utf-8")))
    ref_all = pd.read_csv(nfhs5 / "NFHS-5-Districts.csv", dtype=str, keep_default_na=False)
    ref_all["no"] = ref_all.Indicator.str.extract(r"^(\d+)\.", expand=False).astype(int)
    out, used = [], set()
    for m in manifest:
        cut(download(m["source_url"], downloads), m["source_pages"], HERE / m["fixture"])
        res = extract(HERE / m["fixture"], parse=parse, key=KEY, checks=checks())
        assert (res.failed != "").sum() == 0 and (res.status == "verified").all(), m["fixture"]
        assert set(res.geo) == {m["geography"]}, (m["fixture"], set(res.geo))
        got = {
            (int(p), int(n), c): v
            for p, n, c, v in zip(res.page, res.indicator_no, res.column, res.value, strict=True)
        }
        ref = ref_all[
            (ref_all["State-Code"] == m["state_code"]) & (ref_all.District == m["district"])
        ]
        ref = ref.set_index("no")
        assert len(ref) == 104, (m["fixture"], len(ref))
        cols = sorted({c for _, _, c in got}, key=DISTRICT_COLUMNS.index)
        seen = set()
        for page, n in sorted({(p, n) for p, n, _ in got}):
            no = RENUMBERED.get((m["fixture"], page, n), n)
            seen.add(no)
            row = {
                "fixture": m["fixture"],
                "page": page,
                "geo": m["geography"],
                "indicator_no": n,
                "csv_no": no,
                "indicator": ref.loc[no, "Indicator"],
            }
            notes = (
                ["printed number differs: c (" + EVIDENCE + "mahisagar_9-12.png)"]
                if no != n
                else []
            )
            for col in DISTRICT_COLUMNS:
                src = {"nfhs5_total": "NFHS-5", "nfhs4_total": "NFHS-4"}[col]
                value, note = ref.loc[no, src], ref.loc[no, f"{src}-note"]
                row[col], row[f"csv_{col}"], row[f"csv_{col}_note"] = "", value, note
                if col not in cols:
                    assert value == "" and note == "", (m["fixture"], n, col)  # no such column
                    continue
                key = (m["fixture"], page, n, col)
                if key in CHECKED:
                    used.add(key)
                    printed, cls, evidence = CHECKED[key]
                    assert got[key[1:]] == printed and not same(printed, value, note), key
                    notes.append(f"{col}: {cls} ({evidence})")
                else:
                    printed = got[key[1:]]
                    assert same(printed, value, note), (key, printed, value, note)
                row[col] = printed
            row["checked"] = "; ".join(notes)
            out.append(row)
        assert seen == set(range(1, 105)), (m["fixture"], sorted(set(range(1, 105)) - seen))
    assert used == set(CHECKED), set(CHECKED) - used
    pd.DataFrame(out).to_csv(HERE / "expected.csv", index=False)


if __name__ == "__main__":
    main(Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser())
