"""CBHI National Health Profile: State/UT wise cases (and deaths) of one disease by year.

The vector-borne disease and H1N1 tables print several years side by side, each over its
measures ("Cases Deaths", "C D", or "cases" alone for clinically suspected chikungunya).
"""

import re
import statistics
from collections.abc import Iterable, Iterator

from pdfexorcist.rows import Page, is_value

DISEASES = [
    ("Malaria", r"malaria"),
    ("Chikungunya", r"chikun|chickun"),
    ("Kala-azar", r"kala[- ]?azar"),
    ("Acute Encephalitis Syndrome", r"acute\s+encephalitis|\bAES\b"),
    ("Japanese Encephalitis", r"japanese\s+encephalitis|\bJE\b"),
    ("Dengue", r"dengue"),
    ("Influenza A H1N1", r"H1N1|swine\s+flu"),
]
TITLE = re.compile(r"(cases|deaths)", re.I)
YEAR = re.compile(r"\b((?:19|20)\d\d)\b(\s*\(?\s*(?:p\b|prov|till|as\s+on|upto|up\s+to))?", re.I)
MARKS = re.compile(r"(?<=\d)[*#@$^]+$")
END = re.compile(r"^\W*(source|notes?\b)", re.I)
FOOTER = re.compile(r"health\s+profile|NHP|status\s+indicator", re.I)
NOTE = re.compile(r"\bas\s+on\b|cumulative|includes|surveillance|programme", re.I)


def _text(cells: list) -> str:
    return " ".join(t for _, t in cells)


def _disease(text: str) -> str | None:
    hits = [name for name, pat in DISEASES if re.search(pat, text, re.I)]
    return hits[0] if len(hits) == 1 else None


def _header(lines: list, start: int) -> tuple[int, list[str]] | None:
    """(index of the measures line, column years) of the header below a title.

    Years are read left to right from every line down to the measures line, as a
    provisional last year may sit above the others. The last year is provisional when the
    header marks one ("Prov.", "till", "as on", "(P)").
    """
    found: dict[str, float] = {}
    marked = False
    for i in range(start + 1, min(start + 9, len(lines))):
        text = _text(lines[i])
        if re.search(r"\bICD\b|\bcode\b|wise", text, re.I):
            continue  # the title wrapping onto a second line
        measures = re.search(r"\b(cases|deaths)\b|^\W*C\s+D\b|\bC\s+D\s+C\b", text, re.I)
        _, name, vals = _row(lines[i])
        first_row = bool(found) and bool(name) and len(vals) >= 3 and not YEAR.search(text)
        if measures or first_row:
            years = sorted(found, key=lambda y: found[y])
            if len(years) < 3:
                return None
            if marked:
                years[-1] += " (Prov.)"
            # no measures line: the years head the rows themselves (cases alone)
            return (i if measures else i - 1), years
        for x, cell in lines[i]:
            for y, p in YEAR.findall(cell):
                found.setdefault(y, x)
                marked = marked or bool(p)
        marked = marked or bool(re.search(r"prov|till|as\s+on", text, re.I))
    return None


def _measures(text: str) -> list[str]:
    """The measures under each year: cases and deaths, or cases alone."""
    words = re.findall(r"\b(cases|deaths|c|d)\b", text, re.I)
    first = [w.lower()[0] for w in words[:2]]
    return ["Cases", "Deaths"] if first == ["c", "d"] else ["Cases"]


def _row(cells: list) -> tuple[str, str, list[tuple[float, str]]]:
    """(serial, name, positioned values) of a body line; marks glued to values dropped ("17$$")."""
    toks = [(x, MARKS.sub("", t)) for x, text in cells for t in text.split()]
    i = len(toks)
    while i and is_value(toks[i - 1][1]):
        i -= 1
    label, vals = [t for _, t in toks[:i]], toks[i:]
    sno = label[0].rstrip(".") if label and label[0].rstrip(".").isdigit() else ""
    name = " ".join(label[1:] if sno else label)
    name = re.sub(r"\s*&\s*", " & ", re.sub(r"[*#@$^%]+", "", name))  # "J&K", "J & K"
    name = " ".join(name.split())
    if re.fullmatch(r"(all\s+)?(india|total)(\s+total)?", name, re.I):
        name = "India"  # the national row, so the States can be checked against it
    return sno, name, vals


def _centres(rows: list, k: int) -> list[float] | None:
    full = [v for _, _, v in rows if len(v) == k]
    if len(full) < 2:
        return None
    return [statistics.median(v[i][0] for v in full) for i in range(k)]


def _place(vals: list[tuple[float, str]], centres: list[float]) -> dict[int, str]:
    """Values by column, each at the nearest centre; two in one column unread."""
    out: dict[int, str] = {}
    for x, v in vals:
        c = min(range(len(centres)), key=lambda i: abs(centres[i] - x))
        out[c] = "" if c in out else v
    return {c: v for c, v in out.items() if v}


def _lines(lines: list) -> tuple[list[tuple[str, str, list]], bool]:
    """Rows (serial, name, values) down to the table's end, wrapped names joined, and
    whether the table ended (a source note or the next title) before the page did.

    A line with a name and no values continues the row above (its name wrapped), unless
    the next line has values and no name: then it names that line. A line with values
    and no name between two named rows (Dadra & Nagar Haveli and Daman & Diu, merged in
    2020, printed between the two) is named after both.
    """
    raw = []
    ended = False
    for cells in lines:
        text = _text(cells)
        if END.search(text) or (TITLE.search(text) and _disease(text) and "wise" in text):
            ended = True
            break
        sno, name, vals = _row(cells)
        if FOOTER.search(name) or NOTE.search(name):
            continue
        if vals or (name and not re.search(r"cases|deaths|state", name, re.I)):
            raw.append([sno, name, vals])
    rows: list[list] = []
    for i, (sno, name, vals) in enumerate(raw):
        nxt = raw[i + 1] if i + 1 < len(raw) else None
        if not vals:
            if nxt is not None and nxt[2] and not nxt[1]:
                nxt[1] = name
            elif rows:
                rows[-1][1] = f"{rows[-1][1]} {name}".strip()
            continue
        if not name and rows and nxt is not None and nxt[1]:
            name = f"{rows[-1][1]} and {nxt[1]}"
        if name:
            rows.append([sno, name, vals])
    return [tuple(r) for r in rows], ended


def _body(
    lines: list, cols: list, centres: list[float] | None, disease: str, page_no: int
) -> tuple[list[dict], bool, list[float] | None]:
    """The values of the rows in lines, whether the table ended on this page, and the
    column centres (carried to a continuation page)."""
    rows, ended = _lines(lines)
    centres = _centres(rows, len(cols)) or centres
    out: list[dict] = []
    for sno, name, vals in rows:
        if len(vals) > len(cols):
            continue
        placed = _place(vals, centres) if centres else {i: v for i, (_, v) in enumerate(vals)}
        for c, v in placed.items():
            year, measure = cols[c]
            out.append({
                "page": page_no,
                "disease": disease,
                "state": name,
                "col": f"{year} {measure}",
                "sno": sno,
                "year": year[:4],
                "measure": measure,
                "value": v,
            })  # fmt: skip
    return out, ended, centres


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield one value per disease, State/UT, year and measure; India is a row.

    A table that runs to the foot of a page continues on the next page's rows above any
    new title (the header is not repeated).
    """
    carry: tuple[str, list, list[float] | None] | None = None
    for page_no, lines in pages:
        titles = []
        for i, cells in enumerate(lines):
            text = _text(cells)
            if not (TITLE.search(text) and re.search(r"wise", text, re.I)):
                continue
            disease = _disease(text + " " + " ".join(_text(c) for c in lines[i + 1 : i + 2]))
            if disease and (head := _header(lines, i)):
                titles.append((i, disease, head))
        if carry is not None:
            stop = titles[0][0] if titles else len(lines)
            cells, _, _ = _body(lines[:stop], carry[1], carry[2], carry[0], page_no)
            yield from cells
        carry = None
        for _, disease, (at, years) in titles:
            cols = [(y, m) for y in years for m in _measures(_text(lines[at]))]
            cells, ended, centres = _body(lines[at + 1 :], cols, None, disease, page_no)
            yield from cells
            carry = None if ended else (disease, cols, centres)
