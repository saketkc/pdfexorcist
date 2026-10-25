"""Gujarat NVBDCP monthly highlights (one page, November 2019 onwards).

Reads the state's blood examination rate (MBER or ABER), the change in cases since January
against the year before as a signed %, and each top contributing place's share of cases.
Places are as printed; the caller maps them to districts.
"""

import re
from collections.abc import Iterable, Iterator

from pdfexorcist.rows import Cell, Page

DISEASES = ("Malaria", "Dengue", "Chikungunya")
SECTION = re.compile(r"^(Malaria|Dengue|Chikungunya|Elimination|Specific|Action)\b", re.I)
END = re.compile(r"^(Action|Elimination|Specific|Note)\b", re.I)
SHARE = re.compile(r"([A-Za-z][A-Za-z .,&/-]*?)\s*,?\s*\(\s*(\d+(?:\.\d+)?)\s*%?\s*\)")
SPLIT = re.compile(r"\s*(?:,|&|\band\b)\s*")
BER = re.compile(
    r"(Monthly|Annual)\s+Blood\s+Examination\s+Rate.{0,160}?\bwas\s+(\d+(?:\.\d+)?)\s*%", re.I
)
CHANGE = re.compile(
    r"(?:\b(Malaria|Dengue|Chikungunya)(?:\s+and\s+PF)?\s+cases|cases\s+of\s+(Malaria|Dengue|"
    r"Chikungunya))[^.%]{0,40}?\b(declined|decreased|reduced|increased|rised|rose)\s*(?:by)?\s*"
    r"(\d+(?:\.\d+)?)\s*%",
    re.I,
)


def _text(cells: list[Cell]) -> str:
    """A line's text, ASCII only (the bullets are private-use glyphs)."""
    text = " ".join(t for _, t in cells)
    return " ".join(re.sub(r"[^\x20-\x7e]", " ", text).split())


def _shares(disease: str, text: str) -> Iterator[dict]:
    # a cell naming several places ("Jamnagar & GMC (5%)") gives each the share printed
    for names, share in SHARE.findall(text):
        for name in SPLIT.split(names.strip(" ,.&-")):
            name = name.strip(" ,.&-")
            if re.search(r"[A-Za-z]{2}", name):
                yield {"disease": disease, "measure": "share", "area": name, "value": share}


def _grid(lines: list[list[Cell]], start: int) -> Iterator[dict]:
    """The contributors' table from 2020-10: a column per disease, its cells "AMC (24 %)"."""
    heads = [(x, t) for x, text in lines[start] for t in text.split() if t in DISEASES]
    xs = [x for x, _ in heads]
    if len(heads) != len(DISEASES) or len(set(xs)) != len(xs):
        return  # an engine giving the heading as one piece cannot place the columns
    cols: dict[str, list[str]] = {d: [] for _, d in heads}
    for cells in lines[start + 1 :]:
        if END.match(_text(cells)):
            break
        line: dict[str, list[str]] = {d: [] for d in cols}
        for x, text in cells:
            col = min(heads, key=lambda h: abs(h[0] - x))[1]
            line[col].append(re.sub(r"[^\x20-\x7e]", " ", text))
        for col, pieces in line.items():
            cols[col].append(" ".join(pieces))
    for disease, parts in cols.items():
        yield from _shares(disease, _join(parts))


def _join(parts: list[str]) -> str:
    """A column's lines as one text; a name wrapped to a new line is a new place
    ("Jamnagar, Kutchh" over "Surendranagr (4%)") unless it goes on in lower case."""
    text = ""
    for part in (" ".join(p.split()) for p in parts):
        if not part:
            continue
        new_place = text and not text.endswith((")", ",", "&")) and part[0].isupper()
        text = f"{text}, {part}" if new_place else f"{text} {part}".strip()
    return text


def _prose(lines: list[list[Cell]]) -> Iterator[dict]:
    """Contributors named in a sentence of each disease's section, before 2020-10.

    ("... were Ahmedabad Corporation (16%), Surat Municipal Corporation (30%)")
    """
    section, texts = "", {d: [] for d in DISEASES}
    for cells in lines:
        text = _text(cells)
        if m := SECTION.match(text):
            section = m.group(1).capitalize()
        if section in texts:
            texts[section].append(text)
    for disease, parts in texts.items():
        joined = " ".join(parts)
        for m in re.finditer(r"contribut.{0,200}?\bwere\b(.*?)(?:\.\s|\.$|$)", joined, re.I):
            yield from _shares(disease, m.group(1))


def _state(text: str) -> Iterator[dict]:
    if m := BER.search(text):
        measure = "MBER" if m.group(1).lower() == "monthly" else "ABER"
        yield {"disease": "Malaria", "measure": measure, "area": "Gujarat", "value": m.group(2)}
    seen = set()
    for m in CHANGE.finditer(text):
        if re.search(r"during\s+(the\s+)?year", text[max(0, m.start() - 40) : m.start()], re.I):
            continue  # the last full year against the one before, not this year so far
        disease = (m.group(1) or m.group(2)).capitalize()
        if disease in seen:
            continue
        seen.add(disease)
        sign = "" if m.group(3).lower() in ("increased", "rised", "rose") else "-"
        value = f"{sign}{m.group(4)}"
        yield {"disease": disease, "measure": "change", "area": "Gujarat", "value": value}


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each figure keyed by disease, measure and place."""
    for page_no, lines in pages:
        text = " ".join(_text(cells) for cells in lines)
        if not re.search(r"Highlights", text, re.I):
            continue
        out = list(_state(text))
        grid = next(
            (
                i
                for i, cells in enumerate(lines)
                if all(re.search(rf"\b{d}\b", _text(cells)) for d in DISEASES)
            ),
            None,
        )
        out += list(_grid(lines, grid) if grid is not None else _prose(lines))
        seen: set[tuple[str, str, str]] = set()
        for row in out:
            key = (row["disease"], row["measure"], row["area"])
            if key not in seen:  # a place printed twice in a column keeps its first share
                seen.add(key)
                yield {**row, "page": page_no}
