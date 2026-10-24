"""State/UT names as NACO prints them, and the row labels that name them."""

import re

from pdfexorcist.rows import label_key

TOTAL = "India"
JK_LADAKH = "Jammu & Kashmir and Ladakh"

# name -> printed spellings, as label_key() folds them
STATES: dict[str, tuple[str, ...]] = {
    "Andaman & Nicobar Islands": (
        "andamannicobarislands", "andamanandnicobarislands", "anislands", "andnislands",
        "ani", "andamannicobar",
    ),
    "Andhra Pradesh": ("andhrapradesh",),
    "Arunachal Pradesh": ("arunachalpradesh",),
    "Assam": ("assam",),
    "Bihar": ("bihar",),
    "Chandigarh": ("chandigarh",),
    "Chhattisgarh": ("chhattisgarh", "chattisgarh"),
    "Dadra & Nagar Haveli and Daman & Diu": (
        "dnhdd", "dnhanddd", "dadranagarhavelianddamandiu", "dadranagarhavelidamandiu",
        "dadraandnagarhavelianddamananddiu", "dadranagarhavelianddamananddiu",
    ),
    "Dadra & Nagar Haveli": ("dnh", "dadranagarhaveli", "dadraandnagarhaveli"),
    "Daman & Diu": ("damandiu", "damananddiu"),
    "Delhi": ("delhi", "nctofdelhi"),
    "Goa": ("goa",),
    "Gujarat": ("gujarat",),
    "Haryana": ("haryana",),
    "Himachal Pradesh": ("himachalpradesh",),
    # "and Ladakh" is the second line of "Jammu & Kashmir and Ladakh"
    JK_LADAKH: ("jammukashmirandladakh", "jammuandkashmirandladakh", "jkandladakh", "andladakh"),
    "Jammu & Kashmir": ("jammukashmir", "jammuandkashmir", "jk"),
    "Jharkhand": ("jharkhand",),
    "Karnataka": ("karnataka",),
    "Kerala": ("kerala",),
    "Ladakh": ("ladakh",),
    "Lakshadweep": ("lakshadweep",),
    "Madhya Pradesh": ("madhyapradesh",),
    "Maharashtra": ("maharashtra",),
    "Manipur": ("manipur",),
    "Meghalaya": ("meghalaya",),
    "Mizoram": ("mizoram",),
    "Nagaland": ("nagaland",),
    "Odisha": ("odisha", "orissa"),
    "Puducherry": ("puducherry", "pondicherry"),
    "Punjab": ("punjab",),
    "Rajasthan": ("rajasthan",),
    "Sikkim": ("sikkim",),
    "Tamil Nadu": ("tamilnadu",),
    "Telangana": ("telangana",),
    "Tripura": ("tripura",),
    "Uttar Pradesh": ("uttarpradesh",),
    "Uttarakhand": ("uttarakhand", "uttaranchal"),
    "West Bengal": ("westbengal",),
    "Ahmedabad": ("ahmedabad", "ahmedabadmc", "amcacs", "ahmedabadmcacs"),
    "Mumbai": ("mumbai", "mumbaidacs", "mdacs"),
    TOTAL: ("india", "allindia", "total", "grandtotal", "national", "nationaltotal"),
}  # fmt: skip

ALIASES = {alias: name for name, aliases in STATES.items() for alias in aliases}
# longest first, so "jammukashmirandladakh" wins over "ladakh"
_BY_LENGTH = sorted(ALIASES, key=len, reverse=True)
SERIAL = re.compile(r"^\d{1,2}[.)]?$")
MARKS = "*#@$^†‡"


def state(label: str) -> str | None:
    """The State/UT a row label names, or None.

    A serial number, or a running head an engine joined to the row, may lead the label; the
    serial must come just before the name. Footnote marks are dropped.
    """
    words = label.strip(" " + MARKS).split()
    words = [w.strip(MARKS) for w in words if w.strip(MARKS)]
    if not words:
        return None
    for alias in _BY_LENGTH:
        for i in range(len(words)):
            if label_key("".join(words[i:])) != alias:
                continue
            before = words[:i]
            if not before or SERIAL.match(before[-1]):
                return ALIASES[alias]
            return None
    return None
