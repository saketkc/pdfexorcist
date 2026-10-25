"""Kerala DHS communicable disease data: cases and deaths by district and disease.

Fever prints three lines: OP cases, the Sl.No. with the deaths, IP cases. A disease is
keyed by its name, since a Sl.No. can repeat. Text left of the Sl.No. column is dropped.
"""

import re
from collections.abc import Iterable, Iterator

import pandas as pd

from pdfexorcist import check
from pdfexorcist.checks import total_check
from pdfexorcist.rows import Page, label_key

STATE = "Kerala"
DISTRICTS = {
    "Thiruvananthapuram": ["trivandrum", "tvm"],
    "Kollam": [],
    "Pathanamthitta": [],
    "Alappuzha": ["alleppey"],
    "Kottayam": [],
    "Idukki": [],
    "Ernakulam": ["earnakulam"],
    "Thrissur": ["trissur"],
    "Palakkad": [],
    "Malappuram": [],
    "Kozhikode": ["kozhikkode", "calicut"],
    "Wayanad": [],
    "Kannur": [],
    "Kasaragod": ["kasaragode", "kasargod", "kasargode"],
}
AREA = {label_key(a): name for name, alias in DISTRICTS.items() for a in [name, *alias]}
# label_key of a printed name -> the name the State page prints
ALIASES = {"acuteencephalitissyndrome": "AES", "cpox": "Chicken Pox"}
FEVER = "Fever"
NUM = r"(?:\d[\d,]*\*?|-)"  # "439*": a footnote mark, removed by [normalize]; "-": none (2011)
ROW = re.compile(rf"^(\d{{1,2}}) (?P<name>.*?[A-Za-z].*?) (?P<cases>{NUM}) (?P<deaths>{NUM})$")
# a name wrapped around its numbers: "Hand Foot and Mouth Disease", "16 408 0", "(HFMD)"
WRAPPED = re.compile(rf"^(\d{{1,2}})(?P<name>) (?P<cases>{NUM}) (?P<deaths>{NUM})$")
WORDS = re.compile(r"^\D*[A-Za-z]\D*$")
OPIP = re.compile(rf"\b(OP|IP) ({NUM})(?: -)?$")  # 2011 prints "-" deaths beside each
FEVER_DEATHS = re.compile(rf"^(\d{{1,2}} )?(?:Fever )?({NUM})$")  # Kannur 2024 prints no Sl.No.
HEADER = re.compile(r"^Sl\.\s*(No\.?)?$")
YEAR = re.compile(r"^(20\d\d)$")


def disease(name: str) -> str:
    """The name evenly spaced, or its alias: "Prob:Hepatitis - A" -> "Prob: Hepatitis - A"."""
    name = re.sub(r"\s*:\s*", ": ", re.sub(r"\s*-\s*", " - ", name))
    name = re.sub(r"\s+", " ", name).strip()
    return ALIASES.get(label_key(name), name)


def _area(lines: list[list]) -> str | None:
    """The district named above the table, or Kerala on the State page.

    A district name wins over the title "District Wise Data on Communicable Disease".
    """
    state = False
    for line in lines:
        if any(HEADER.match(t) for _, t in line):
            break
        for _, t in line:
            if (key := label_key(t)) in AREA:
                return AREA[key]
        key = label_key(" ".join(t for _, t in line))
        # "Data on Communicable Diseases"; up to 2013 "Communicable Diseases Data"
        state |= "dataoncommunicabledisease" in key or "communicablediseasesdata" in key
    return STATE if state else None


def _body(lines: list[list]) -> tuple[str | None, list[str]]:
    """The year in the header, and the text of each line below it, margin left out."""
    left = None  # x of the Sl.No. column; text left of it is the margin note
    year = None
    texts = []
    for line in lines:
        if left is None:
            year = next((m[1] for _, t in line if (m := YEAR.match(t))), year)
            head = next((x for x, t in line if HEADER.match(t)), None)
            left = None if head is None else head * 0.8
            continue
        text = re.sub(r"\s+", " ", " ".join(t for x, t in line if x >= left)).strip()
        if m := YEAR.match(text):
            year = m[1]
        elif text:
            texts.append(text)
    return year, texts


def parse(pages: Iterable[Page]) -> Iterator[dict]:
    """Yield each case and death count keyed by area, disease and column."""
    for page_no, lines in pages:
        area = _area(lines)
        if area is None:
            continue
        year, texts = _body(lines)
        base = {"area": area, "page": page_no, "year": year}
        fever = False  # an OP line came first: a lone number is the fever deaths
        for i, text in enumerate(texts):
            if m := OPIP.search(text):
                fever = m[1] == "OP"
                yield {**base, "disease": FEVER, "col": m[1].lower(), "value": m[2]}
            elif fever and (m := FEVER_DEATHS.match(text)):
                sl = m[1].strip() if m[1] else None
                yield {**base, "disease": FEVER, "col": "deaths", "sl": sl, "value": m[2]}
            elif (m := ROW.match(text)) or (m := WRAPPED.match(text)):
                name = m["name"] or " ".join(t for t in texts[i - 1 : i + 2 : 2] if WORDS.match(t))
                for col, v in (("cases", m["cases"]), ("deaths", m["deaths"])):
                    yield {**base, "disease": disease(name), "col": col, "sl": m[1], "value": v}


@check("districts = Kerala")
def districts_add_up(df: pd.DataFrame) -> pd.Series:
    """Check that the districts add up to the State page, disease by disease.

    With a district page missing, the State need only exceed the sum.
    """
    n = df.loc[df.area != STATE, "area"].nunique()
    op = "==" if n == len(DISTRICTS) else ">="
    return total_check("area", STATE, by=["disease", "col"], op=op)(df)
