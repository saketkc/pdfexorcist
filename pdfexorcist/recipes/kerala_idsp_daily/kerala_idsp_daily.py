"""Kerala DHS communicable diseases daily report (IDSP): counts by district and for the State.

The table column is district, state or dengue_list. Every district cell prints a count or "-",
so its counts are placed by order (columns per layout in kerala_layouts.py). The State's
analysis table leaves blank cells out, so its counts go under the nearest heading.
"-" (none) is written 0.
"""

import re
import warnings
from collections.abc import Iterable, Iterator

import pandas as pd
from kerala_layouts import DISTRICTS, LAYOUTS, TOTAL, page_layout

from pdfexorcist import check, grid
from pdfexorcist.cells import cell_box
from pdfexorcist.rows import Page, is_value, label_key

CODES = [*DISTRICTS, TOTAL]
STATE = "Kerala"
# a district row's label; e-office copies print an approval note sideways in the margin,
# which some engines join to the label ("State 2 KLM")
ROW = re.compile(rf"(?:^|\s)(?:\d{{1,2}}\s+)?({'|'.join(CODES)})$")
LISTED = re.compile(rf"^({'|'.join(DISTRICTS)})\b\s*:?\s*(\d+|-)(?=\s|$)")
HEADS = {"sus.c": "suspected", "sus.d": "suspected_deaths", "con": "confirmed", "death": "deaths"}
PERIODS = ("day", "month", "year")
# printed names (label_key) -> one name for the district and analysis tables alike
NAMES = {
    "denguefever": "Dengue",
    "dengue": "Dengue",
    "cpox": "Chickenpox",
    "chickenpox": "Chickenpox",
    "conje": "JE",
    "je": "JE",
    "aesje": "AES/JE",
    "hepatitisa": "Hepatitis A",
    "hepatitisb": "Hepatitis B",
    "hepatitisc": "Hepatitis C",
    "hepatitise": "Hepatitis E",
    "scrubtyphus": "Scrub typhus",
    "monkeypox": "Mpox",
    "mpox": "Mpox",
    "westnile": "West Nile",
    "amebicmeningoencephalitis": "Amoebic meningoencephalitis",
    "amoebicmeningoencephalitis": "Amoebic meningoencephalitis",
    "meningoencephalitis": "Amoebic meningoencephalitis",  # "Amebic" lost to a wrap
    "covid19": "Covid-19",
    "kfd": "KFD",
    "add": "ADD",
    "aes": "AES",
    "h1n1": "H1N1",
}
KNOWN = {
    *NAMES.values(),
    *("Fever", "Malaria", "Chikungunya", "Leptospirosis", "Cholera", "Typhoid", "Measles"),
    *("Mumps", "Influenza", "Scrub typhus", "Diphtheria", "Rabies", "Zika", "Nipah"),
    *("Shigella", "West Nile"),
}
ORIGIN = {"ind": "indigenous", "imp": "imported"}


def disease(name: str) -> str:
    """One spelling of a printed disease name.

    Engines split "Scrub Typhus" when its letters overprint ("Scrub yp", "Typhus").
    """
    name = re.sub(r"\s+", " ", name).strip(" .:")
    key = label_key(name)
    if key.startswith("scrub") or key == "typhus":
        return "Scrub typhus"
    if key.startswith("chicken"):
        return "Chickenpox"
    return NAMES.get(key, name)


def _count(tok: str) -> str:
    return "0" if tok in ("-", "–", "—") else tok


def _tokens(line: list) -> list[tuple[float, str]]:
    """(centre, token) for each word of a line."""
    return [(mid, t) for _, mid, t in _spans(line)]


def _spans(line: list) -> list[tuple[float, float, str]]:
    """(left, centre, token) for each word of a line: from its box, else from its character
    offset in a pdftotext cell (whose x counts characters)."""
    out = []
    for cell in line:
        x, text = cell[0], cell[1]
        box = cell_box(cell)
        width = max(len(text), 1)
        for m in re.finditer(r"\S+", text):
            if box is not None:
                x0, _, x1, _ = box
                left = x0 + (x1 - x0) * m.start() / width
                mid = x0 + (x1 - x0) * (m.start() + m.end()) / (2 * width)
            else:
                left, mid = x + m.start(), x + (m.start() + m.end()) / 2
            out.append((left, mid, m.group()))
    return out


def _text(line: list) -> str:
    return re.sub(r"\s+", " ", " ".join(t for _, t in line)).strip()


def _district_table(lines: list, page_no: int, layout: str) -> Iterator[dict]:
    cols = LAYOUTS[layout]
    listing: list | None = None  # the lines of the dengue panchayat list, below the table
    pending = None  # a district whose counts an engine put on the next line
    for line in lines:
        toks = [t for _, t in _tokens(line)]
        i = len(toks)
        while i and is_value(toks[i - 1]):
            i -= 1
        label, values = " ".join(toks[:i]), toks[i:]
        m = ROW.search(label)
        area = m[1] if m else None
        if area is None and pending and not re.search("[A-Za-z]", label):
            area = pending
        pending = area if m and not values else None
        if area and len(values) == len(cols):
            for (dis, sub, measure), v in zip(cols, values, strict=True):
                yield {
                    "table": "district",
                    "area": area,
                    "disease": dis,
                    "subgroup": sub,
                    "measure": measure,
                    "period": "day",
                    "value": _count(v),
                    "page": page_no,
                    "layout": layout,
                }
            continue
        text = _text(line)
        if re.match(r"^Disease C D\b", text):
            listing = []
        elif listing is not None and "Lepto" in text:
            yield from _listed(listing, page_no)
            listing = None
        elif listing is not None:
            listing.append(line)


def _listed(lines: list, page_no: int) -> Iterator[dict]:
    """Each district's count in the dengue list. An engine may put a count a line above or
    below its district (the count is centred in a cell of several lines)."""
    spans = [_spans(line) for line in lines]
    codes = [x0 for sp in spans for x0, _, t in sp if t.rstrip(":") in DISTRICTS]
    if not codes:
        return
    left = min(codes) - 1  # the disease totals and the margin note are left of it
    found: dict[str, str] = {}
    pending = orphan = None
    for sp in spans:
        text = " ".join(t for x0, _, t in sp if x0 >= left)
        if m := LISTED.match(text):
            found.setdefault(m[1], m[2])
            pending = orphan = None
        elif m := re.match(rf"^({'|'.join(DISTRICTS)})\b\s*:?$", text):
            if orphan is not None:
                found.setdefault(m[1], orphan)
            pending, orphan = (None if orphan is not None else m[1]), None
        elif m := re.match(r"^(\d+|-)(?=\s|$)", text):
            if pending is not None:
                found.setdefault(pending, m[1])
            pending, orphan = None, (None if pending is not None else m[1])
    for code, n in found.items():
        yield {
            "table": "dengue_list",
            "area": code,
            "disease": "Dengue",
            "subgroup": "",
            "measure": "confirmed",
            "period": "day",
            "value": _count(n),
            "page": page_no,
        }


def _heads(line: list) -> list[tuple[float, str, str]] | None:
    """(centre, measure, period) of the analysis table's twelve headings, or None."""
    toks = [(x, HEADS.get(t.lower())) for x, t in _tokens(line)]
    heads = [(x, h) for x, h in toks if h]
    if len(heads) != 12:
        return None
    return [(x, h, PERIODS[i // 4]) for i, (x, h) in enumerate(heads)]


def _state_table(lines: list, page_no: int) -> Iterator[dict]:
    heads = None
    margin = -1e9  # the left of "Sl.No.": the sideways approval note is left of it
    left = 0.0  # the counts are right of this
    for n, line in enumerate(lines):
        if heads is None:
            heads = _heads(line)
            sl = [x0 for x0, _, t in _spans(line) if t.lower().startswith("sl")]
            margin = sl[0] - 1 if sl else margin
            if heads:
                left = heads[0][0] - 0.6 * (heads[1][0] - heads[0][0])
            continue
        name, values = _row(line, margin, left)
        if len(values) < 4 or len(values) > 12:  # "2 Malaria" sits between Ind. and Imp.
            continue
        sub = ""
        if label_key(name) in ORIGIN:
            dis, sub = "Malaria", ORIGIN[label_key(name)]
        else:
            if not name:
                near = [_row(lines[k], margin, left) for k in (n - 1, n + 1) if 0 <= k < len(lines)]
                name = _wrapped([w for w, v in near if not v])
            dis = disease(name)
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 /-]*", dis):  # skips a death note
                continue
        for x, v in values:
            _, measure, period = min(heads, key=lambda h: abs(h[0] - x))
            yield {
                "table": "state",
                "area": STATE,
                "disease": dis,
                "subgroup": sub,
                "measure": measure,
                "period": period,
                "value": _count(v),
                "page": page_no,
            }


def _wrapped(near: list[str]) -> str:
    """The name of a row printed without one, from the lines above and below.

    A long name is wrapped around its counts ("Amebic", "25 - - ...",
    "Meningoencephalitis"); a short one sits on one of the two lines, beside a name of
    another row or a death note. "" when it cannot be told.
    """
    near = [w for w in near if re.fullmatch(r"[A-Za-z][A-Za-z .-]*", w)]
    known = [w for w in near if disease(w) in KNOWN]
    if len(known) == 1:
        return known[0]
    return " ".join(near) if near and not known else ""


def _row(line: list, margin: float, left: float) -> tuple[str, list[tuple[float, str]]]:
    """A line's disease name (Sl.No. and margin note left out) and its (centre, count)s."""
    toks = [(x, t) for x0, x, t in _spans(line) if x0 >= margin]
    values = [(x, t) for x, t in toks if x >= left and is_value(t)]
    words = [t for _, t in toks if not is_value(t) and not re.fullmatch(r"\d{1,2}\.", t)]
    # a death note an engine put on the row: "West Nile Dengue Death: 37/F, ..."
    for k in range(len(words), 0, -1):
        if disease(" ".join(words[:k])) in KNOWN:
            return " ".join(words[:k]), values
    return " ".join(words), values


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield every count keyed by table, area, disease, subgroup, measure and period."""
    for page_no, lines in pages:
        text = " ".join(_text(line) for line in lines[:12])
        if "REPORTING FORMAT" in text.upper():
            layout = page_layout(grid.current_pdf(), page_no)
            if layout is None:
                warnings.warn(f"page {page_no}: district table of a layout not known", stacklevel=1)
            else:
                yield from _district_table(lines, page_no, layout)
        if "ANALYSIS OF COMMUNICABLE" in text.upper():
            yield from _state_table(lines, page_no)


def _num(df: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(df["value"], errors="coerce")


@check("district TOT = State on the day")
def tot_is_state(df: pd.DataFrame) -> pd.Series:
    """The TOT row against the analysis table's counts on the day, disease by disease.

    Malaria species are summed to imported and indigenous. The State prints the district
    table's cases (fever OP, ADD, chickenpox) as confirmed.
    """
    v = _num(df)
    tot = df[(df["table"] == "district") & (df["area"] == TOTAL)].copy()
    if tot.empty:  # no district table read
        return pd.Series(False, index=df.index)
    tot["v"] = v
    sub = tot["subgroup"].str.extract(r"(imported|indigenous)$", expand=False)
    tot["key_sub"] = sub.fillna("")
    tot["key_measure"] = tot["measure"].replace("cases", "confirmed")
    tot = tot[~((tot["disease"] == "Fever") & (tot["subgroup"] == "IP"))]
    keys = ["disease", "key_sub", "key_measure"]
    sums = tot.groupby(keys)["v"].sum(min_count=1)
    st = df[(df["table"] == "state") & (df["period"] == "day")]
    st_keys = pd.MultiIndex.from_frame(
        st[["disease", "subgroup", "measure"]].set_axis(keys, axis=1)
    )
    want = pd.Series(sums.reindex(st_keys).to_numpy(), index=st.index)
    bad_state = want.notna() & v[st.index].notna() & (want != v[st.index])
    bad_keys = set(map(tuple, st.loc[bad_state, ["disease", "subgroup", "measure"]].to_numpy()))
    bad_tot = pd.Series(
        [k in bad_keys for k in map(tuple, tot[keys].to_numpy())], index=tot.index, dtype=bool
    )
    return pd.concat([bad_state, bad_tot]).reindex(df.index, fill_value=False)


@check("dengue list = district table")
def listed_dengue(df: pd.DataFrame) -> pd.Series:
    """Each district's listed dengue cases against its confirmed dengue in the table."""
    v = _num(df)
    table = (df["table"] == "district") & (df["disease"] == "Dengue")
    table &= df["measure"] == "confirmed"
    by_area = v[table].groupby(df.loc[table, "area"]).first()
    listed = df["table"] == "dengue_list"
    want = df.loc[listed, "area"].map(by_area)
    bad = want.notna() & v[listed].notna() & (want != v[listed])
    return bad.reindex(df.index, fill_value=False)
