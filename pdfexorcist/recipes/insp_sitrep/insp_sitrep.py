"""INSP (DRC) Ebola situation reports: confirmed cases and deaths by province and health zone.

A province's own row has zone "Total"; the national row has province "Total". Needs
engines that give word boxes.
"""

import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import pairwise

from pdfexorcist import grid
from pdfexorcist.cells import _inside
from pdfexorcist.grid import Word

# heading (accents dropped, lower case) -> column; the first match wins
NAMES = [
    ("zone", r"zones? de sante$|^province ?/ ?zone"),
    ("province", r"^provinces?$"),
    ("zones_affected", r"zones? de sante touchees"),
    ("suspected_deaths", r"deces suspects"),
    ("suspected_cases", r"cas suspects"),
    ("contacts", r"contacts"),
    ("new_case_deaths", r"dont deces"),
    ("community_deaths", r"communautaire"),
    ("cte_deaths", r"intra"),
    ("new_deaths", r"total deces|deces du jour"),
    ("new_cases", r"nouv"),
    ("cfr", r"letalite"),
    ("deaths", r"deces"),
    ("cases", r"\bcas\b"),
]
LABELS = {"province", "zone"}
KNOWN = {name for name, _ in NAMES}
NUMBER = re.compile(r"^[\d\s.,%/()]*\d[\d\s.,%/()]*$")
PROVINCES = {
    "kinshasa", "kongocentral", "kwango", "kwilu", "maindombe", "kasai", "kasaicentral",
    "kasaioriental", "lomami", "sankuru", "maniema", "sudkivu", "nordkivu", "ituri",
    "hautuele", "basuele", "tshopo", "mongala", "nordubangi", "sudubangi", "equateur",
    "tshuapa", "tanganyika", "hautlomami", "lualaba", "hautkatanga",
}  # fmt: skip


@dataclass(frozen=True)
class Columns:
    """A table's columns: (name, x0, x1) left to right, and the table's kind."""

    cols: tuple[tuple[str, float, float], ...]
    kind: str  # "zones", "zones_daily" or "provinces"

    @property
    def span(self) -> tuple[float, float]:
        return self.cols[0][1], self.cols[-1][2]


def _ascii(text: str) -> str:
    """Lower case without accents: "Haut-Uélé" -> "haut-uele"."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def fold(text: str) -> str:
    """Lower case without accents or punctuation: "Haut-Uélé" -> "hautuele"."""
    return re.sub(r"[^a-z0-9]", "", _ascii(text))


def _name(heading: str) -> str:
    plain = " ".join(_ascii(heading).split())
    for name, pattern in NAMES:
        if re.search(pattern, plain):
            return name
    return re.sub(r"[^a-z0-9]+", "_", plain).strip("_")


def _label(words: list[Word]) -> str:
    """Printed text, rejoining a name Word broke after its hyphen ("Makiso-" "Kisangani")."""
    text = unicodedata.normalize("NFC", " ".join(w[0] for w in words))
    return re.sub(r"\s+", " ", re.sub(r"-\s+", "-", text)).strip(" *")


def _value(words: list[Word]) -> str:
    """A cell's value without spaces: "1 984" -> "1984", "28/36 (77,8 %)" -> "28/36(77,8%)"."""
    return "".join(w[0] for w in words)


def _data_top(table: grid.Table, words: list[Word], bands: list[float]) -> float | None:
    """The top of the first band with a label and a number; None for a table without data."""
    x0, _, x1, _ = table.bbox
    for a, b in pairwise(bands):
        band = sorted((w for w in words if _inside((x0, a, x1, b), *w[1])), key=lambda w: w[1][0])
        first = next((i for i, w in enumerate(band) if NUMBER.match(w[0])), None)
        if first is not None and any(re.search(r"[^\W\d_]", w[0]) for w in band[:first]):
            return a
    return None


def _header(table: grid.Table, words: list[Word], data_top: float) -> tuple[Columns, float] | None:
    """The columns the header's lowest cells name, and the header's bottom; None for other tables.

    Rows right of the case-fatality column may draw no rules.
    """
    x0, _, x1, _ = table.bbox
    # a cell across the whole table is a province printed as a section row ("ITURI")
    above = [
        c for c in table.cells if c[3] <= data_top + grid.SNAP and c[2] - c[0] < x1 - x0 - grid.SNAP
    ]
    if not above:
        return None
    data_top = max(c[3] for c in above)
    leaves = sorted(c for c in above if abs(c[3] - data_top) <= grid.SNAP)
    cols = []
    for c in leaves:
        mid = (c[0] + c[2]) / 2
        stack = sorted(
            (h for h in table.cells if h[0] <= mid <= h[2] and h[3] <= data_top + grid.SNAP),
            key=lambda h: h[1],
        )
        heading = " ".join(_label(grid.words_in(words, h)) for h in stack)
        cols.append((_name(heading), c[0], c[2]))
    names = {n for n, _, _ in cols}
    if not names & LABELS or not names & {"cases", "new_cases"} or not names <= KNOWN:
        return None
    kind = "zones" if "cases" in names else "zones_daily"
    if "zone" not in names:
        kind = "provinces"
    return Columns(tuple(cols), kind), data_top


def parse(pages: Iterable) -> Iterator[dict]:
    """Yield each value of the case tables keyed by table, province, zone and column."""
    tables = grid.tables(grid.current_pdf())
    columns: Columns | None = None
    province = ""
    for page_no, lines in pages:
        words = grid.words(lines)
        for table in tables.get(page_no, []):
            x0, top, x1, bottom = table.bbox
            inside = [w for w in words if _inside(table.bbox, *w[1])]
            bands = grid.bands(table)
            data_top = _data_top(table, inside, bands)
            if data_top is None:
                continue
            if data_top - top > grid.SNAP:  # a header: a new table
                head = _header(table, inside, data_top)
                columns, data_top = head if head else (None, data_top)
                province = ""
            elif columns is not None and all(
                abs(a - b) <= 6 for a, b in zip(columns.span, (x0, x1), strict=True)
            ):
                # the same table, continued; its first row may sit above the first drawn rule
                data_top = top - (bands[1] - bands[0])
                bands = [data_top, *bands]
                inside = [w for w in words if _inside((x0, data_top, x1, bottom), *w[1])]
            else:
                columns = None
            if columns is None:
                continue
            for a, b in _rows(columns, inside, bands, data_top):
                province, row = _row(table, columns, inside, a, b, province)
                for col, value in row.items():
                    yield {**value, "col": col, "table": columns.kind, "page": page_no}


def _rows(
    columns: Columns, words: list[Word], bands: list[float], data_top: float
) -> Iterator[tuple[float, float]]:
    """The data rows as (top, bottom).

    A band whose values sit on several lines splits between them; a wrapped zone name keeps
    its values on one line.
    """
    value_x = [(c0, c1) for name, c0, c1 in columns.cols if name not in LABELS]
    for a, b in pairwise(bands):
        if a < data_top - grid.SNAP:
            continue
        mids = sorted(
            (w[1][1] + w[1][3]) / 2
            for w in words
            if a <= (w[1][1] + w[1][3]) / 2 <= b
            and any(c0 <= (w[1][0] + w[1][2]) / 2 <= c1 for c0, c1 in value_x)
        )
        cuts = [(p + q) / 2 for p, q in pairwise(grid.snap(mids)) if q - p > 6]
        yield from pairwise([a, *cuts, b])


def _row(
    table: grid.Table, columns: Columns, words: list[Word], a: float, b: float, province: str
) -> tuple[str, dict[str, dict]]:
    """The province now in force, and the row's values between a and b by column."""
    cells: dict[str, str] = {}
    row = grid.in_band(words, a, b)
    for name, c0, c1 in columns.cols:
        box = (c0, a, c1, b)
        if name == "province" and columns.kind != "provinces":
            # merged over its zones: read the whole drawn cell
            box = table.at((c0 + c1) / 2, (a + b) / 2) or box
            cells[name] = _label(grid.words_in(words, box))
        else:
            ws = grid.words_in(row, box)
            cells[name] = _label(ws) if name in LABELS else _value(ws)
    label = cells.get("zone") or cells.get("province") or ""
    values = {n: v for n, v in cells.items() if n not in LABELS and v}
    if label and not values and fold(label) in PROVINCES:
        return label, {}  # a province printed as a section row, without counts
    if not label or not values:
        return province, {}
    if fold(label).startswith("total"):  # "Total — létalité 30,5 %"
        province, zone = "Total", "Total"
    elif columns.kind == "provinces":
        province, zone = label, ""
    elif fold(label).startswith("soustotal"):  # "Sous-total Nord-Kivu" (sitrep 026)
        zone = "Total"
    elif cells.get("province"):
        province, zone = cells["province"], label
    elif fold(label) in PROVINCES and fold(label) != fold(province):
        # a zone may share its province's name (Tshopo); the province's row came first
        province, zone = label, "Total"
    else:
        zone = label
    if columns.kind == "provinces":
        zone = ""
    key = {"province": province, "zone": zone}
    return province, {n: {**key, "value": v} for n, v in values.items()}
