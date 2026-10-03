"""NEET toppers scan."""

import csv
import os
from importlib.util import find_spec
from pathlib import Path

import pandas as pd
import pytest
from nta_toppers import FIELDS, KEY, parse, percentile_falls, rank_rises

from pdfexorcist import extract, validate
from pdfexorcist.cells import BoxCell

FIXTURES = Path(__file__).parent / "fixtures" / "nta"
EXPECTED = list(csv.DictReader((FIXTURES / "expected.csv").open(encoding="utf-8")))
ENGINES = {"paddleocr": "paddleocr", "ocrmac": "ocrmac", "glmocr": "mlx_vlm"}  # engine: module
# column centres in points, as on the scan
X = {
    "sr_no": 76,
    "application_no": 127,
    "name": 205,
    "gender": 290,
    "category": 340,
    "percentile": 406,
    "rank": 461,
    "state": 500,
}
COVERAGE = 0.95  # share of the expected cells a majority must agree on


def _want() -> dict:
    return {(r["sr_no"], f): r[f] for r in EXPECTED for f in FIELDS}


def _wrap(field: str, text: str) -> list[str]:
    """A cell's lines as printed: long names, the OBC category and two-word States wrap."""
    if field == "category" and text.startswith("OBC"):
        return ["OBC-", "NCL", "(Central", "List)"]
    if field == "state" and " " in text:
        return text.split(" ", 1)
    if field == "name" and len(text) > 15:
        first, _, rest = text.rpartition(" ")
        return [first, rest]
    return [text]


def _cell(field: str, text: str, y: float) -> BoxCell:
    x = X[field]
    return BoxCell(x, text, (x - 3 * len(text), y - 5, x + 3 * len(text), y + 5))


def _text(text: str, y: float) -> list:
    """A line of running text (a heading, the letterhead) across the page."""
    return [BoxCell(300, text, (100, y - 5, 500, y + 5))]


HEADER = ["Sr.", "Application", "Candidate name", "Gender", "Category", "Percentile", "NEET"]
LETTERHEAD = [
    _text("National Testing Agency", 60),
    _text("(An Autonomous Organization under the Department of Higher Education)", 100),
]
TITLE = _text("List of Top 138 candidates scoring equal to or more than 690 marks", 130)


def _lines_page(rows: list[dict], head: bool = True) -> list:
    """Lay out rows as line-based OCR, including wrapped cells and page text."""
    lines = list(LETTERHEAD)
    if head:
        lines.append(TITLE)
        lines.append([_cell(f, t, 160) for f, t in zip(X, HEADER, strict=False)])
        lines.append([_cell("sr_no", "No.", 170), _cell("rank", "rank", 170)])
    y = 180.0
    for r in rows:
        cells = {f: _wrap(f, r[f]) for f in X}
        height = max(len(c) for c in cells.values())
        for k in range(height):
            line = []
            for f, c in cells.items():
                j = k - (height - len(c))  # bottom-aligned
                if j >= 0:
                    line.append(_cell(f, c[j], y))
            lines.append(line)
            y += 12
    lines.append(_text("Page 1 of 15", 800))
    return lines


def _table_page(rows: list[dict]) -> list:
    """Lay out rows as GLM-OCR, omitting page 2 Application No."""
    return [
        [(0, "Sr. No."), (1, "Candidate name"), (2, "Gender")],
        *([(j, r[f]) for j, f in enumerate(f for f in X if f != "application_no")] for r in rows),
    ]


def test_wrapped_rows():
    """Pin wrapped-row parsing and exclusion of later numbered lists."""
    other = [dict(r, sr_no=str(k + 1)) for k, r in enumerate(EXPECTED[:3])]
    female = _lines_page(other)
    female[2] = _text("List of 20 female toppers in the NEET (UG)-2026 re-examination", 130)
    pages = [(1, _lines_page(EXPECTED[:24])), (2, _lines_page(EXPECTED[24:], head=False))]
    got = {(r["sr_no"], r["field"]): r["value"] for r in parse([*pages, (3, female)])}
    assert got == _want()


def test_parser_reads_one_line_rows():
    got = {(r["sr_no"], r["field"]): r["value"] for r in parse([(1, _table_page(EXPECTED))])}
    assert got == {k: v for k, v in _want().items() if k[1] != "application_no"}


def test_out_of_order():
    want = _want()
    df = pd.DataFrame([{"sr_no": s, "field": f, "value": v} for (s, f), v in want.items()])
    assert not validate(df, [rank_rises, percentile_falls]).failed.any()
    df.loc[(df.sr_no == "30") & (df.field == "rank"), "value"] = "80"  # a misread 30
    df.loc[(df.sr_no == "30") & (df.field == "percentile"), "value"] = "99.9998999"
    failed = validate(df, [rank_rises, percentile_falls]).set_index(["sr_no", "field"]).failed
    assert set(failed[failed != ""].index) == {
        ("30", "rank"),
        ("31", "rank"),
        ("29", "percentile"),
        ("30", "percentile"),
    }


def _installed() -> list:
    return [e for e, mod in ENGINES.items() if find_spec(mod)]


@pytest.mark.skipif(
    not os.environ.get("PDFEXORCIST_OCR_TESTS"),
    reason="slow OCR test; set PDFEXORCIST_OCR_TESTS=1",
)
def test_ocr_tally():
    """Pin OCR values and majority-agreement coverage."""
    engines = _installed()
    if len(engines) < 2:
        pytest.skip("needs two OCR engines")
    need = max(2, len(engines) // 2 + 1)  # strict majority: 2 of 3, 2 of 2
    res = extract(
        FIXTURES / "neet_2026_top138_p1-2.pdf",
        methods=engines,
        parse=parse,
        key=KEY,
        min_agree=need,
    )
    got = {(r.sr_no, r.field): r.value for r in res[res.status == "verified"].itertuples()}
    want = _want()
    wrong = {k: (v, want.get(k)) for k, v in got.items() if v != want.get(k)}
    print(f"\n{len(got)} of {len(want)} cells agreed, {len(wrong)} wrong ({', '.join(engines)})")
    assert wrong == {}
    assert len(got) >= COVERAGE * len(want)
