"""State and UT names of the India TB Report annexures, and the kinds of table it reads."""

import re

# folded name -> name as the 2024 report prints it; "&" is folded to "and"
STATES = {
    re.sub(r"[^a-z]", "", s.lower().replace("&", "and")): s
    for s in [
        "Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
        "Chandigarh", "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa",
        "Gujarat", "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka",
        "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur",
        "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Puducherry", "Punjab", "Rajasthan",
        "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
        "West Bengal", "India",
    ]
}  # fmt: skip
INDIA = "India"
FIRST = "Andaman and Nicobar Islands"  # the first row of every table

# (kind, caption pattern, header pattern), first match wins; the header pattern names a
# table whose caption turning the page upright drops
KINDS = [
    ("outcome", r"treatment outcome of", None),
    ("notification", r"tb case notification$", r"target.*expected.*notified.*notification rate"),
    ("characteristics", r"notified tb patients\W+characteristics", r"site of disease"),
    ("hiv", r"known hiv status|screening for hiv", r"tb patients with known hiv status"),
    ("pregnancy", r"tb\W+pregnancy", r"screened for pregnancy"),
]


def fold(text: str) -> str:
    """Lower case letters only, "&" read as "and": "Jammu & Kashmir" -> "jammuandkashmir"."""
    return re.sub(r"[^a-z]", "", text.lower().replace("&", "and"))


def state(label: str) -> str | None:
    """The State or UT a row label names, as the 2024 report prints it; None for another label."""
    return STATES.get(fold(label))


def kind_of(caption: str, header: str) -> str | None:
    """The kind of table a caption or header names; None for a table not read."""
    caption, header = caption.lower(), header.lower()
    for kind, by_caption, by_header in KINDS:
        if re.search(by_caption, caption) or (by_header and re.search(by_header, header)):
            return kind
    return None
