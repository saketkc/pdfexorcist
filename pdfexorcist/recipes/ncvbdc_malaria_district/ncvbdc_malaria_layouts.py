"""Column layouts of the NCVBDC malaria annual reports, and fixes to a row's reading.

The count of values in a row names its layout: 12 (2010-2016), 8 (2017-2018), 16 (2019),
20 (2020), 28 (2021), 34 (2022-2023), 37 (2024).
"""

import re

TESTS = ["pop", "bsc", "rdt_collected", "bse", "rdt", "tested_collected", "tested"]
RATES_A = ["pf_pct", "aber", "api", "spr", "sfr", "afi"]  # 2010-2016 order
RATES_B = ["pf_pct", "aber", "api", "spr", "afi", "sfr"]  # 2017 on
SPECIES = ["pv", "pf", "mixed", "pm", "po", "others"]
TAIL = ["rt", "deaths_pv", "deaths_pf"]  # radical treatment, deaths by species


def _cases(prefix: str, species: list[str]) -> list[str]:
    return [f"{prefix}{s}" for s in species] + [f"{prefix}total"]


LAYOUTS: dict[int, tuple[str, list[str]]] = {
    12: ("2010", ["pop", "bse", "pv", "pf", "positive", *RATES_A, "deaths"]),
    8: ("2017", [*RATES_B, "deaths_pv", "deaths_pf"]),
    16: ("2019", ["pop", "bsc", "bse", "pv", "pf", "mixed", "positive", *RATES_B, *TAIL]),
    20: ("2020", [*TESTS, "pv", "pf", "mixed", "positive", *RATES_B, *TAIL]),
    28: (
        "2021",
        [
            *TESTS,
            *_cases("ind_", SPECIES[:3]),
            *_cases("imp_", SPECIES[:3]),
            "pv",
            "pf",
            "mixed",
            "positive",
            *RATES_B,
            *TAIL,
        ],
    ),
    34: (
        "2022",
        [
            *TESTS,
            *_cases("ind_", SPECIES[:3]),
            *_cases("imp_", SPECIES),
            *SPECIES,
            "positive",
            *RATES_B,
            *TAIL,
        ],
    ),
    37: (
        "2024",
        [
            *TESTS,
            *_cases("ind_", SPECIES),
            *_cases("imp_", SPECIES),
            *SPECIES,
            "positive",
            *RATES_B,
            *TAIL,
        ],
    ),
}
NOT_COUNTS = {"pop", *RATES_A}
STATE_TITLE = re.compile(r"\bState\s*:\s*(.+?)\s*$", re.I)
# "Situation Report of Assam 2017", "Situation Report Andhra Pradesh-2022"; no State: India
REPORT_TITLE = re.compile(r"Situation\s+Report(?:\s+of)?\b\s*(.*?)\W*(?:(?:19|20)\d\d\b.*)?$", re.I)
TOTAL = re.compile(r"\btotal\b", re.I)
INDIA = re.compile(r"\bal+\s*(india|states)|grand total", re.I)
NOT_STATE = re.compile(r"\b(state|states|total|all|india|grand)\b|\(P\)", re.I)
# "12 Kurnool", "12. Kurnool", "624Uttar Pradesh Agra" (glued)
SERIAL = re.compile(r"^(\d{1,3})(?![\d,]|\.\d)\.?\s*(.*)$")
INTEGER = re.compile(r"^\d{1,3}$")
# a label with a value glued on ("Diu Total125433", "(UT created 31.10.2019)6240")
GLUED = re.compile(r"^(.*?[A-Za-z)])(\d+)$")
# header and title lines, never part of a district's name
NOISE = re.compile(
    r"district|pop\b|pop'n|b\.?s\.?[ce]\b|\bbse\b|collected|examined|positive|indigenous|"
    r"imported|deaths?\b|parameters|p\.?\s?f\.?\s?%|a\.?b\.?e\.?r|\bpv\b|\bpf\b|mixed|"
    r"directorate|national cent|vector borne|sham\s*nath|delhi-110054|page \d+ of|"
    r"annual report|situation|\bsn\b|\(000|rdt|bsc\+|to malaria|cases\b|f\.no",
    re.I,
)


def state_name(label: str) -> str:
    """The State in a Total row's label ("Assam Total" -> "Assam"; "State Total" -> "")."""
    return " ".join(NOT_STATE.sub(" ", label).split())


def without_state(name: str, state: str) -> str:
    """A 2024 district label without the State printed beside it (and wrapped into it)."""
    drop = [w.lower() for w in state.split()]
    kept = []
    for w in name.split():
        if w.lower() in drop:
            drop.remove(w.lower())
        else:
            kept.append(w)
    return " ".join(kept)


def complete(values: list[str]) -> list[str | None]:
    """A 2010-2016 row with its blank rates put back; other rows as read.

    Pf% is blank without positives, SPR and SFR without smears examined, and ABER, API and
    AFI without population.
    """
    if not 5 <= len(values) < 12 or any("." in v for v in values[:5]):
        return list(values)
    zero = [v.strip("0.") == "" for v in values[:5]]
    # pf_pct, aber, api, spr, sfr, afi: blank when
    blank = [zero[4], zero[0], zero[0], zero[1], zero[1], zero[0]]
    if len(values) != 12 - sum(blank):
        return list(values)
    rates = iter(values[5:])
    filled = [None if b else next(rates) for b in blank]
    return [*values[:5], *filled, *rates]


def unglue(label: str, values: list[str]) -> tuple[str, list[str]]:
    """Split a value an engine read into the label back off it."""
    m = GLUED.match(label)
    if m and len(complete(values)) not in LAYOUTS and len(complete([m[2], *values])) in LAYOUTS:
        return m[1], [m[2], *values]
    return label, values


def row_label(pending: list[str], label: str) -> tuple[str, str]:
    """(serial, name) of a row, from its own label and the label-only lines before it."""
    own = SERIAL.match(label)
    if own:
        # pending lines with a serial belong to rows printed without values
        before = [p for p in pending if not SERIAL.match(p)]
        return own[1], " ".join([*before, own[2]]).strip()
    joined = " ".join([*pending, label]).strip()
    m = SERIAL.match(joined)
    if m:
        return m[1], m[2]
    # the name above, the serial below (one engine's reading of 2017-2018)
    m = re.match(r"^(.*?)\s+(\d{1,3})$", joined)
    return (m[2], m[1]) if m else ("", joined)
