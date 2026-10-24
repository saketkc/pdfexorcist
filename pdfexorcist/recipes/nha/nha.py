"""National Health Accounts Estimates for India: the text tables of the report.

Each table is found by its title and read until the next title, across pages.
"""

import re
from collections.abc import Iterable, Iterator

from pdfexorcist.rows import Page, is_value

TITLE = re.compile(r"^Table\s*(?:[A-Z]\s*\.?\s*)?\d+\s*:", re.I)
CODE = re.compile(r"^(HF|FS|HP|HC)\s?\.\s?([0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)$")
YEAR = re.compile(r"^(?:19|20)\d\d-(?:\d\d)?$")
SERIAL = re.compile(r"^\d{1,2}\.?$")
# the words a year header line may hold besides the years
HEADER_WORDS = {"sl", "no", "n", "slno", "indicator", "nha"}
# lines that end a table's rows: page footers and footnotes
FOOTER = re.compile(r"National Health Accounts|Source|All values|rounded off|^\*", re.I)
# section headings inside the key indicators table
SECTION = re.compile(r"^(Government Health Expenditure \(GHE\)|Household Health and Out|Others$)")

# Table A 6, by the order of its header
STATES_2021 = [
    "the_cr", "the_pct_gsdp", "the_pc",
    "ghe_cr", "ghe_pct_the", "ghe_pct_gsdp", "ghe_pct_gge", "ghe_pc",
    "oope_cr", "oope_pct_the", "oope_pct_gsdp", "oope_pct_gge", "oope_pc",
    "population_cr", "gsdp_cr", "gge_cr",
]  # fmt: skip
STATES_2015 = [
    "the_cr", "the_pc", "the_pct_gsdp",
    "ghe_cr", "ghe_pc", "ghe_pct_the", "ghe_pct_gsdp", "ghe_pct_gge",
    "oope_cr", "oope_pc", "oope_pct_gsdp", "oope_pct_the",
    "population_cr", "gsdp_cr", "gge_cr",
]  # fmt: skip
STATES_GHE = [
    "ghe_pct_gsdp",
    "ghe_pct_gge",
    "ghe_pc",
    "ghe_cr",
    "population_cr",
    "gsdp_cr",
    "gge_cr",
]
UTS_GHE = ["ghe_pc", "ghe_000", "population_000"]


def table_kind(title: str) -> str | None:
    """Name the table a title starts, or None for a table this recipe does not read.

    rounds, che, key: key indicators (row: Sl. No.; column: year). HF, FS, HP, HC: spending
    by financing scheme, revenue, provider, function (row: SHA 2011 code or Total; column:
    amount or pct). capital: capital formation. states, states_ghe, uts_ghe: annexures.
    """
    t = " ".join(title.split()).lower()
    if "select states" in t:
        return "states"
    if "all the states" in t:
        return "states_ghe"
    if "uts without" in t:
        return "uts_ghe"
    if "key health financing indicators" in t:
        if "across nha rounds" in t:
            return "rounds"
        return "che" if "current health expenditure" in t else "key"
    if "capital formation" in t:
        return "capital"
    if re.search(r"\band\b|matrix", t):
        return None  # the two-way matrices of Annexure A.1
    if re.search(
        r"\bby (healthcare financing|revenues|healthcare providers|healthcare functions)", t
    ):
        return "codes"
    return None


def _tokens(line: list) -> list[str]:
    return [t for _, text in line for t in text.split()]


def _split(toks: list[str]) -> tuple[list[str], list[str]]:
    """Split tokens into the label and the trailing values."""
    i = len(toks)
    while i and is_value(toks[i - 1]):
        i -= 1
    return toks[:i], toks[i:]


def _years(toks: list[str], nxt: list[str]) -> list[str] | None:
    """The year columns of a header line: 2013-14, or 2013- over 14 on the next line."""
    ys = [t for t in toks if YEAR.match(t)]
    words = {re.sub(r"[^a-z]", "", t.lower()) for t in toks if not YEAR.match(t)}
    if not ys or not words <= HEADER_WORDS:
        return None
    if all(not y.endswith("-") for y in ys):
        return ys
    tails = [t for t in nxt if re.fullmatch(r"\d\d", t)]
    if len(tails) != len(ys):
        return None
    return [y + t for y, t in zip(ys, tails, strict=True)]


class _Reader:
    """Reads one engine's lines; rows are kept until the next row starts."""

    def __init__(self) -> None:
        self.kind: str | None = None
        self.years: list[str] = []
        self.header = ""
        self.row: dict | None = None
        self.out: list[dict] = []

    def flush(self) -> None:
        if self.row:
            self.out.extend(self._cells(self.row))
        self.row = None

    def _cells(self, r: dict) -> Iterator[dict]:
        table, cols, vals = r["table"], r["cols"], r["vals"][-len(r["cols"]) :]
        if len(vals) < len(cols):
            return
        label = " ".join(" ".join(r["label"]).split())
        for col, v in zip(cols, vals, strict=True):
            yield {
                "table": table,
                "item": r["key"],
                "col": col,
                "value": v,
                "label": label,
                "page": r["page"],
            }

    def line(self, page: int, toks: list[str], nxt: list[str]) -> None:
        text = " ".join(toks)
        if TITLE.match(text):
            self.flush()
            self.kind, self.years, self.header = table_kind(text), [], ""
            return
        if self.kind is None:
            return
        read = {"codes": self._codes, "capital": self._capital}.get(self.kind)
        if read is None:
            read = self._states if self.kind.startswith(("states", "uts")) else self._rounds
        read(page, toks, nxt)

    def _start(self, page: int, table: str, key: str, label: list, vals: list, cols: list) -> None:
        self.flush()
        self.row = {"table": table, "key": key, "label": list(label), "vals": list(vals),
                    "cols": cols, "page": page}  # fmt: skip

    def _rounds(self, page: int, toks: list[str], nxt: list[str]) -> None:
        label, vals = _split(toks)
        text = " ".join(label)
        if FOOTER.search(text) or SECTION.match(text):
            self.flush()
            return
        ys = _years(toks, nxt)
        if ys:
            self.flush()
            self.years = ys
            return
        if label and SERIAL.match(label[0]) and self.years and len(vals) >= len(self.years):
            self._start(page, self.kind or "", label[0].rstrip("."), label[1:], vals, self.years)
        elif self.row and label:
            self.row["label"] += label

    def _codes(self, page: int, toks: list[str], nxt: list[str]) -> None:
        label, vals = _split(toks)
        m = CODE.match(label[0]) if label else None
        if not m and len(label) > 1:
            m = CODE.match(label[0] + label[1])  # "HP. 10"
            label = [label[0] + label[1], *label[2:]] if m else label
        if m:
            code = f"{m[1]}.{m[2]}"
            self._start(page, m[1], code, label[1:], vals, ["amount", "pct"])
        elif label == ["Total"] and self.row:
            self._start(page, self.row["table"], "Total", [], vals, ["amount", "pct"])
        elif self.row and not label:
            self.row["vals"] += vals  # an amount printed below its wrapped name
        elif (self.row and vals) or FOOTER.search(" ".join(label)):
            self.flush()
        elif self.row:
            self.row["label"] += label

    def _capital(self, page: int, toks: list[str], nxt: list[str]) -> None:
        label, vals = _split(toks)
        if len(vals) == 2 and label and not FOOTER.search(" ".join(label)):
            self._start(page, "capital", " ".join(label), label, vals, ["amount", "pct"])
            if label == ["Total"]:
                self.flush()
                self.kind = None
        else:
            self.flush()

    def _states(self, page: int, toks: list[str], nxt: list[str]) -> None:
        label, vals = _split(toks)
        if self.kind == "states":
            cols = (
                STATES_2015
                if re.search(r"per\s*capita\s*%\s*gsdp", self.header, re.I)
                else STATES_2021
            )
        else:
            cols = STATES_GHE if self.kind == "states_ghe" else UTS_GHE
        if label and SERIAL.match(label[0]) and len(label) > 1 and len(vals) >= len(cols):
            name = " ".join(label[1:])
            self._start(page, self.kind or "", name, label[1:], vals, cols)
        elif label and label[0][:1].isalpha() and len(vals) == len(cols):
            self._start(page, self.kind or "", " ".join(label), label, vals, cols)  # 2020-21 A 6
        elif (
            self.row
            and label
            and not vals
            and len(label) <= 3
            and not FOOTER.search(" ".join(label))
        ):
            self.row["key"] += " " + " ".join(label)  # a name wrapped onto a second line
            self.row["label"] += label
        else:
            self.flush()
            if not self.out or self.out[-1]["table"] != self.kind:
                self.header += " " + " ".join(toks)


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield the cells of every table this recipe reads, in reading order."""
    r = _Reader()
    for page_no, lines in pages:
        toks = [_tokens(line) for line in lines]
        toks = [t for t in toks if t]
        for i, t in enumerate(toks):
            r.line(page_no, t, toks[i + 1] if i + 1 < len(toks) else [])
        r.flush()  # a row does not run on to the next page
    yield from r.out
