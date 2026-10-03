"""ADSI tables."""

import csv
import os
from importlib.util import find_spec
from pathlib import Path

import pandas as pd
import pytest
from adsi_state_table import KEY, adsi_checks, make_parser, row_key

from pdfexorcist import extract

FIXTURES = Path(__file__).parent / "fixtures" / "adsi"
MANIFEST = list(csv.DictReader((FIXTURES / "manifest.csv").open(encoding="utf-8")))
EXPECTED = pd.read_csv(FIXTURES / "expected.csv", keep_default_na=False)
DIGITAL = [m for m in MANIFEST if not m["source_pdf"].endswith(".orig")]
SCANNED = [m for m in MANIFEST if m["source_pdf"].endswith(".orig")]
OCR_ENGINES = {
    "tesseract": None,
    "chandra": "chandra",
    "glmocr": "mlx_vlm",
    "paddleocr": "paddleocr",
    "ocrmac": "ocrmac",
}  # engine: module (None: a binary)

# Slack for one engine's tokenisation change; a lost row or column still fails.
MIN_COVERAGE = 0.97
# The 1995 scan: Tesseract yields no rows on this ruled page, so the other four
# engines vote. MP 25692 and the Haryana and Rajasthan rates go unagreed.
SCAN_MIN_COVERAGE = 0.95


def _tally(res: pd.DataFrame, fixture: str) -> dict:
    """Return vote tallies keyed by serial or total label."""
    v = res[res.status == "verified"]
    got = {(str(r), m): float(x) for r, m, x in zip(v.row, v.metric, v.value, strict=True)}
    exp = EXPECTED[EXPECTED.fixture == fixture]
    keys = [str(s) if s != "" else r for s, r in zip(exp.serial, exp.row, strict=True)]
    want = {(k, m): float(x) for k, m, x in zip(keys, exp.metric, exp.value, strict=True)}
    named = {(k, m): n for k, m, n in zip(keys, exp.metric, exp.note, strict=True) if n}
    state = dict(zip(keys, exp.row, strict=True))
    names = {str(r): row_key(n) for r, n in zip(v.row, v.name, strict=True)}
    out = {
        "agreed": len(got),
        "tallied": sum(k in want for k in got),
        "wrong": {k: (got[k], want[k]) for k in got if k in want and abs(got[k] - want[k]) > 1e-9},
        "missing": [k for k in want if k not in got],
        "named": len(named),
        "named_bad": {
            k: (got.get(k), want[k], named[k])
            for k in named
            if k not in got or abs(got[k] - want[k]) > 1e-9
        },
        "failed": int(((res.status == "verified") & (res.failed != "")).sum()),
        "expected": len(want),
        "misnamed": {r: (n, state[r]) for r, n in names.items() if r in state and n != state[r]},
    }
    print(
        f"\n{fixture}: {out['agreed']} agreed, {out['tallied']} tallied, {len(out['wrong'])} "
        "wrong, "
        f"{len(out['missing'])} of {out['expected']} expected unagreed, "
        f"{out['named'] - len(out['named_bad'])} of {out['named']} named cells right, "
        f"{out['failed']} failed a check"
    )
    return out


@pytest.mark.parametrize("m", DIGITAL, ids=[m["fixture"] for m in DIGITAL])
def test_text_tally(m: dict) -> None:
    """Pin the verified text-engine tally and coverage."""
    res = extract(
        FIXTURES / m["fixture"],
        parse=make_parser(m["table"]),
        key=KEY,
        checks=adsi_checks(),
    )
    t = _tally(res, m["fixture"])
    assert t["wrong"] == {}
    assert t["named_bad"] == {}
    assert t["failed"] == 0
    assert t["agreed"] == t["tallied"]  # nothing voted outside the State/UT rows
    assert t["misnamed"] == {}  # each serial carries the State the project stored under it
    assert t["tallied"] >= MIN_COVERAGE * t["expected"]
    # all five text engines vote; PDFium splits Table 1.2's "(5)" header into three tokens
    assert set("|".join(res.sources).split("|")) == {
        "pdftotext",
        "pdfplumber",
        "pymupdf",
        "pdfium",
        "camelot",
    }


def _installed() -> list:
    import shutil

    return [
        e for e, mod in OCR_ENGINES.items() if (shutil.which(e) if mod is None else find_spec(mod))
    ]


@pytest.mark.skipif(
    not os.environ.get("PDFEXORCIST_OCR_TESTS"),
    reason="slow OCR test; set PDFEXORCIST_OCR_TESTS=1",
)
@pytest.mark.parametrize("m", SCANNED, ids=[m["fixture"] for m in SCANNED])
def test_scan_tally(m: dict) -> None:
    """Pin OCR tally, named corrections, and scan coverage."""
    engines = _installed()
    need = max(2, len(engines) // 2 + 1)  # 3 of 5, 3 of 4, 2 of 3
    res = extract(
        FIXTURES / m["fixture"],
        methods=engines,
        parse=make_parser(m["table"]),
        key=KEY,
        min_agree=need,
        checks=adsi_checks(),
    )
    t = _tally(res, m["fixture"])
    assert t["wrong"] == {}
    assert t["named_bad"] == {}
    assert t["tallied"] >= SCAN_MIN_COVERAGE * t["expected"]
