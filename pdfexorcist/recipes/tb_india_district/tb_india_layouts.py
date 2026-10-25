"""The district tables of the TB India reports, one column list per layout.

Columns named None are read but not kept (treatment outcomes and other indicators printed
beside the notification figures).
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Layout:
    """A district table: its name, the patterns its page text matches, and its columns."""

    name: str
    patterns: tuple[str, ...]
    cols: tuple[str | None, ...]

    def matches(self, text: str) -> bool:
        return all(re.search(p, text, re.I) for p in self.patterns)


# 2011-2014: case finding by the old (smear) definitions; rates are per lakh a year
_SMEAR = (
    "pop_lakh", "presumptive_examined", "presumptive_per_lakh_qtr", "presumptive_change_pct",
    "smear_pos_diagnosed", "examined_per_smear_pos", "examined_per_smear_pos_change_pct",
    "nsp_detection_rate_pmr", "nsp_notification_rate_cfr", "total_registered",
    "total_notification_rate", "nsp_notification_rate",
)  # fmt: skip
_SMEAR_RATES = (
    "nsn_notification_rate", "nep_notification_rate", "retreatment_notification_rate",
    "retreatment_sp_notification_rate",
)  # fmt: skip

LAYOUTS = [
    # TB India 2010 (2009 data): one table a district, case finding then outcomes
    Layout(
        "2010",
        (r"Popu", r"Annu-?\s*ali"),
        (
            "pop_lakh",
            "presumptive_examined",
            "presumptive_per_lakh_qtr",
            "smear_pos_diagnosed",
            "smear_pos_pct_of_examined",
            "total_registered",
            "total_notification_rate",
            "nsp_registered",
            "nsp_notification_rate",
            "nsp_detection_pct",
            "nsp_pct_of_new_pulmonary",
            "nsn_registered",
            "nep_registered",
            "nep_pct_of_new",
            "retreatment_registered",
            "retreatment_sp_registered",
            "retreatment_sp_pct_of_sp",
        ),
    ),
    # TB India 2011 and 2012 (2010, 2011 data)
    Layout("2011", (r"Popu", r"change"), _SMEAR + _SMEAR_RATES),
    # TB India 2014 (2013 data): the case finding table is split over two pages
    Layout("2014a", (r"Population", r"change", r"suspects"), _SMEAR),
    Layout(
        "2014b",
        (r"negative", r"pediatric", r"conversion"),
        _SMEAR_RATES + ("pediatric_registered", "pediatric_pct_of_new") + (None,) * 8,
    ),
    # TB India 2014: outcomes and TB-HIV, then private sector facilities and notification
    Layout(
        "2014c",
        (r"Laboratories", r"cured"),
        (None,) * 9
        + (
            "private_lab_facilities",
            "private_single_clinic_facilities",
            "private_multi_clinic_facilities",
            "private_lab_notified",
            "private_single_clinic_notified",
            "private_multi_clinic_notified",
            "private_notified",
            "private_notification_rate",
        ),
    ),
    # TB India 2016 (2015 data): notification by the private sector only
    Layout(
        "2016",
        (r"Laboratories",),
        (
            "private_lab_notified",
            "private_single_clinic_notified",
            "private_multi_clinic_notified",
            "private_notified",
        ),
    ),
    # TB India 2017 (2016 data), Table 6
    Layout(
        "2017",
        (r"Pulmo", r"Pediat", r"private"),
        (
            "population",
            "public_notified",
            "pulmonary",
            "pulmonary_pct",
            "extrapulmonary",
            "extrapulmonary_pct",
            "new",
            "new_pct",
            "previously_treated",
            "previously_treated_pct",
            "microbiologically_confirmed",
            "microbiologically_confirmed_pct",
            "clinically_diagnosed",
            "clinically_diagnosed_pct",
            "pediatric",
            "pediatric_pct",
            "private_notified",
            "private_pct",
            "total_notified",
            "public_notification_rate",
            "private_notification_rate",
            "total_notification_rate",
        ),
    ),
    # TB India Report 2018 (2017 data), Annexure 1b: mostly shares of public notification
    Layout(
        "2018",
        (r"Paedi", r"HIV", r"Private"),
        (
            "population",
            "public_notified",
            "treatment_initiated",
            "treatment_initiated_pct",
            "pulmonary_pct",
            "extrapulmonary_pct",
            "new_pct",
            "previously_treated_pct",
            "microbiologically_confirmed_pct",
            "clinically_diagnosed_pct",
            "pediatric_pct",
            "hiv_status_known_pct",
            "hiv_positive_pct",
            "public_notification_rate",
            "private_notified",
            "private_notification_rate",
            "total_notified",
            "total_notification_rate",
        ),
    ),
    # India TB Report 2019 (2018 data), 1.13 District Wise Indicators; outcomes are 2017's
    Layout(
        "2019",
        (r"Paediatric", r"initiated", r"success"),
        (
            "total_notified",
            "public_notified",
            "private_notified",
            "pediatric",
            "new",
            "previously_treated",
            "pmdt_notified",
            "treatment_initiated",
            "treatment_initiated_public",
            "treatment_initiated_private",
            "success_public_prev_year",
            "success_public_prev_year_pct",
            "success_private_prev_year",
            "success_private_prev_year_pct",
        ),
    ),
]


def layout_of(text: str, counts: set[int]) -> Layout | None:
    """The layout of a page: its patterns match and some rows print its column count, or
    (blank cells at the row's end) up to two fewer."""

    def fits(lay: Layout) -> bool:
        return any(len(lay.cols) - 2 <= c <= len(lay.cols) for c in counts)

    return next((lay for lay in LAYOUTS if lay.matches(text) and fits(lay)), None)


# State and UT names as the 2010-2019 reports print them, folded (see fold)
STATES = {
    "andamanandnicobar", "andamanandnicobarislands", "aandnislands", "ladakh", "telengana",
    "andhrapradesh", "arunachalpradesh", "assam", "bihar", "chandigarh", "chhattisgarh",
    "chhatisgarh", "chattisgarh", "dandnhaveli", "dadraandnagarhaveli", "dadarandnagarhaveli",
    "damananddiu", "delhi", "goa", "gujarat", "haryana", "himachalpradesh", "jammuandkashmir",
    "jharkhand", "karnataka", "kerala", "lakshadweep", "madhyapradesh", "maharashtra", "manipur",
    "meghalaya", "mizoram", "nagaland", "odisha", "orissa", "puducherry", "pondicherry", "punjab",
    "rajasthan", "sikkim", "tamilnadu", "telangana", "tripura", "uttarpradesh", "uttarakhand",
    "uttaranchal", "westbengal",
}  # fmt: skip


def fold(text: str) -> str:
    """Lower case letters only, "&" read as "and"."""
    return re.sub(r"[^a-z]", "", text.lower().replace("&", "and"))


def split_state(state: str, district: str) -> tuple[str, str]:
    """(State, district) of a label; a known State name leading a run read as one cell
    ("Andhra Pradesh Adilabad", on either side of the split) is cut off it."""
    if fold(state) in STATES:
        return state, district
    words = f"{state} {district}".split()
    for i in range(len(words) - 1, 0, -1):
        if fold(" ".join(words[:i])) in STATES:
            return " ".join(words[:i]), " ".join(words[i:])
    return state, district
