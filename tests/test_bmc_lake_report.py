"""BMC lake-level photos."""

import csv
import json
import os
from importlib.util import find_spec
from pathlib import Path

import pytest
from bmc_lake_report import BLOCKS, CURRENT, KEY, LAKES, TOTALS, parse

from pdfexorcist import extract

FIXTURES = Path(__file__).parent / "fixtures" / "bmc"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
DATES = [m["date"] for m in MANIFEST]
ENGINES = {
    "chandra": "chandra",
    "glmocr": "mlx_vlm",
    "paddleocr": "paddleocr",
    "ocrmac": "ocrmac",
}  # engine: module

# Rows whose printed % is not useful content / capacity; parse() drops them.
# 2026-07-03 Tansa 2024: 28517 ML and 19.56 %, but 28517 / 145080 = 19.66 %.
SELF_CONTRADICTING = {("2026-07-03", "Tansa", "2024")}

# Current-year cells no majority agrees on; any other unagreed one fails the test.
KNOWN_UNAGREED = {
    # Chandra and PaddleOCR read 128925, GLM-OCR 128928, Apple Vision misses the row
    ("2024-07-28", "Modak Sagar", "2024", "useful_content_ml"),
}


def expected(report: dict) -> dict:
    """A hand-checked bombay7 report JSON -> {(lake, year, field): value} in parse()'s terms."""
    out = {("", "", "report_date"): report["report_date"]}
    for lake in report["lakes"]:
        for yr, y in lake["years"].items():
            out.update(
                {(lake["lake"], yr, f): repr(float(v) + 0.0) for f, v in y.items() if f in CURRENT}
            )
    for yr, y in report["totals"].get("years", {}).items():
        out.update({("total", yr, f): repr(float(v) + 0.0) for f, v in y.items() if f in TOTALS})
    return out


def _report(date: str) -> dict:
    return json.loads((FIXTURES / f"{date}.json").read_text())


def _page(report: dict) -> list:
    """Lay out one report page as a line-based OCR engine returns it."""
    cur = report["report_date"][:4]
    years = [str(int(cur) - k) for k in range(3)]
    lakes = {lake["lake"]: lake for lake in report["lakes"]}
    f2 = "{:.2f}".format
    rows = [
        [
            "Report of Lake Levels at",
            "6.00",
            f"AM on {'-'.join(reversed(report['report_date'].split('-')))}",
        ]
    ]
    for name, cap in BLOCKS:
        if name in ("subtotal", "total"):
            members = LAKES[:4] if name == "subtotal" else LAKES
            for k, yr in enumerate(years):
                if not all(yr in lakes[n]["years"] for n, _ in members):
                    continue  # reports stored for this year only
                uc = sum(lakes[n]["years"][yr]["useful_content_ml"] for n, _ in members)
                printed = report["totals"]["years"].get(yr) if name == "total" else None
                uc = printed["useful_content_ml"] if printed else uc
                rows.append([yr, str(uc)] + ([str(cap)] if k == 1 else []) + [f2(100 * uc / cap)])
            continue
        lake = lakes[name]
        for k, yr in enumerate(years):
            if yr not in lake["years"]:
                continue  # reports stored for this year only
            y = lake["years"][yr]
            row = [f2(lake["fsl"]), f2(lake["ldl"])] if k == 0 else [name.upper()] if k == 1 else []
            row += [yr, f2(y["level"])] + ([f2(y.get("rise_fall_24h", 0))] if k == 0 else [])
            row += [str(y["useful_content_ml"])] + ([str(cap)] if k == 1 else [])
            row += [
                f2(y["pct_useful_content"]),
                f2(y.get("today_rain_mm", 0)),
                f2(y.get("total_rain_mm", 0)),
            ]
            rows.append(row)
    rows.append(["Remarks 1. Vehar Lake started overflowing on 07/07/2026 at", "21.00", "Hrs."])
    return [(1, [[(x, t) for x, t in enumerate(r)] for r in rows])]


@pytest.mark.parametrize("date", DATES)
def test_parser_values(date):
    """Pin parser values and rejection of inconsistent percentage rows."""
    report = _report(date)
    got = {tuple(r[k] for k in KEY): r["value"] for r in parse(_page(report))}
    want = {k: v for k, v in expected(report).items() if (date, *k[:2]) not in SELF_CONTRADICTING}
    assert {k: (got.get(k), v) for k, v in want.items() if got.get(k) != v} == {}


def _installed() -> list:
    return [e for e, mod in ENGINES.items() if find_spec(mod)]


@pytest.mark.skipif(
    not os.environ.get("PDFEXORCIST_OCR_TESTS"),
    reason="slow OCR test; set PDFEXORCIST_OCR_TESTS=1",
)
@pytest.mark.parametrize("date", DATES)
def test_ocr_values(date):
    """Pin OCR values, current-year coverage, and title-date exclusion."""
    engines = _installed()
    need = max(2, len(engines) // 2 + 1)  # strict majority: 3 of 4, 2 of 3, 2 of 2
    res = extract(
        FIXTURES / f"{date}.jpg",
        methods=engines,
        parse=parse,
        key=KEY,
        min_agree=need,
        min_unopposed=2,  # as examples/lake_photo/recipe.toml
    )
    got = {
        tuple(getattr(r, k) for k in KEY): r.value
        for r in res[res.status == "verified"].itertuples()
    }
    want = expected(_report(date))

    wrong = {k: (v, want[k]) for k, v in got.items() if k in want and v != want[k]}
    cur = date[:4]
    required = [k for k in want if k[1] == cur]
    missing = [k for k in required if k not in got and (date, *k) not in KNOWN_UNAGREED]
    dates = (
        res.votes[res.field == "report_date"].str.split(" | ").explode().str.rsplit("×", n=1).str[0]
    )
    # an installed engine that read nothing (e.g. Apple Vision's recognizer stuck
    # until macOS restarts it) may leave cells unagreed; then only wrong values fail
    read = {m for s in res.sources for m in s.split("|") if m} | {
        d.split("=")[0] for x in res.dissent for d in x.split("|") if d and "<missing>" not in d
    }
    silent = sorted(set(engines) - read)
    print(
        f"\n{date}: {len(got)} agreed, {sum(k in want for k in got)} tallied, "
        f"{len(wrong)} wrong, {len(missing)} of {len(required)} current-year cells unagreed"
        + (f"; read nothing: {', '.join(silent)}" if silent else "")
    )
    assert wrong == {}
    if not silent:
        assert missing == []
    assert set(dates) <= {date}


def test_ocr_specks():
    """Pin tolerance of OCR specks and Levels misspelling."""
    words = [
        "Report of Lake Levols at 6.00 AM on 03-10-2026",
        "UPPER VAITARNA 2026 603.27 0.00 219332 96.60 0.00 3896.00",
        "2025 603.51 227047 227047 100.00 0.00 2560.00",
        "2024 • 603.50 226565 99.79 0.00 2810.00",
        "MODAK SAGAR 2026 159.48 -0.25 99153 76.91 0.00 3260.00",
        "TANSA 2026 128.20 -0.03 136822 94.31 0.00 2970.00",
        "2024 ·128.57 143887 99.18 4.00 2954.00",
    ]
    lines = [[(float(i), t) for i, t in enumerate(w.split())] for w in words]
    got = {(r["lake"], r["year"], r["field"]): r["value"] for r in parse([(1, lines)])}
    assert got[("", "", "report_date")] == "2026-10-03"
    assert got[("Upper Vaitarna", "2024", "level")] == "603.5"
    assert got[("Tansa", "2024", "level")] == "128.57"
