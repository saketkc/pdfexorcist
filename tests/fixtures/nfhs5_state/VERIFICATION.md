# NFHS-5 fact sheets: the vote against an independent extraction

Checked on 2026-10-02: every value pdfexorcist's vote reads from the NFHS-5
Key Indicators fact sheets, against the CSVs of
[pratapvardhan/NFHS-5](https://github.com/pratapvardhan/NFHS-5), and each
disagreement against the rendered page.

## Sources

| Source | Version | Used for |
| --- | --- | --- |
| IIPS India Fact Sheet, `India.pdf` (nfhsiips.in) | September 2021 | India, 131 indicators (pages 3-6) |
| IIPS State & UT Fact Sheets, 36 PDFs (nfhsiips.in) | September 2021 (22) and December 2021 (14) | each State/UT, 131 indicators (pages 3-6) |
| IIPS State and District Fact Sheet Compendiums, 36 PDFs (nfhsiips.in) | December 2020, modified May 2021 (22 phase-1 States/UTs); October-November 2021 (14 phase-2) | 705 districts, 104 indicators (three pages each) |
| pratapvardhan/NFHS-5, `NFHS-5-States.csv` and `NFHS-5-Districts.csv` | commit `93c67fed2403c8e533d178d293c5ba0411892b1e` (2021-11-29, "2021 update for states") | the independent extraction: 37 geographies x 131 indicators; 341 districts of the 21 phase-1 States/UTs x 104 indicators |
| [FR375](https://dhsprogram.com/pubs/pdf/FR375/FR375.pdf), NFHS-5 India Report, Volume I (IIPS and ICF, March 2022; 715 pages) | as downloaded 2026-10-02 | corroboration only (below) |

The download URL of each fixture's source is in `manifest.csv` (here and in
`../nfhs5_district/`). FR375 is the national report. It prints no fact sheet
and no district values; its tables "by state/union territory" use the final
data and their own definitions, so they corroborate some State values but are
not the fact sheets.

## Method

1. Read every Key Indicators page of the 37 fact sheets and the 36
   compendiums with the five default text engines and
   `examples/nfhs5/nfhs5_factsheet.py` (3 of 5 must agree), with the parser's two
   checks (no percentage over 100; each State Total between its Urban and
   Rural).
2. Join the agreed values to the CSVs by geography (the page title; the CSVs
   use the same State names, and district names match after ignoring case,
   spaces and "&"/"and") and by indicator number. The CSVs store `(45.6)` as
   45.6, and `*` and `na` as blank; the district CSV marks brackets and `*`
   in its note columns, which are compared too.
3. Look at the rendered page (PyMuPDF to PNG) for every disagreement and
   classify it:
   * Class a: the CSV is wrong; the page prints the vote's value.
   * Class b: pdfexorcist or the parser is wrong (the parser is fixed).
   * Class c: the page itself is inconsistent or misprinted.
   * Class d: naming or alignment only.
   * Class e: the CSV copies another edition of the sheet.

The crops in `evidence/` show each case.

## Results

| | State sheets | District sheets |
| --- | --- | --- |
| Values printed (Key Indicators cells) | 19,388 | 132,910 (705 districts) |
| Agreed by the vote | 19,385 | 132,910 |
| Failed checks | 0 | 0 |
| Compared with the CSV | 19,385 | 62,710 (the CSV's 341 districts) |
| Equal (value, and bracket or `*` note) | 19,258 | 62,635 |
| Class a (CSV wrong) | 0 | 10 (1 value, 9 notes) |
| Class b (pdfexorcist or parser wrong) | 0 after the fixes below | 0 after the fixes below |
| Class c (page misprinted) | 0 | 65, plus 5 CSV cells with no printed value |
| Class d (naming, alignment) | 0 cells | 0 cells |
| Class e (other edition) | 127 | 0 |

The three State cells the vote leaves unresolved are Chandigarh's row 68
(page 4 of the sheet): camelot reads the row with row 40's numbers and only
pdfplumber and PyMuPDF read it as printed, `(7.2) * (7.1) (6.9)`, which the
CSV has too. The CSV's other 8,216 district cells are the NFHS-4 column of 79
districts with no comparable NFHS-4 estimate, which their pages do not print; the CSV leaves
all of them blank.

### Class e: literacy from the December 2020 edition

The 22 phase-1 States/UTs first appeared in the December 2020 compendiums.
IIPS revised their literacy (indicators 14 and 15) in the 2021 State & UT
sheets. The CSV has the 2021 values for every other indicator (indicator 127,
also revised, matches 2021), but for 14 and 15 it has the December 2020
values: each of its 127 differing cells equals the December 2020 compendium's
State page, read by the same vote. FR375 (tables 3.4.1 and 3.4.2, "Percentage
literate") agrees with the 2021 values: 36 of 37 women's and 34 of 37 men's
totals equal the 2021 sheets (the rest differ by 0.1), 15 and 14 equal the
CSV. Evidence: `bihar_literacy_2020.png` (compendium page 7) and
`bihar_literacy_2021.png` (fact sheet page 3).

CSV / printed (Urban / Rural / Total); NFHS-4 is `na` on every sheet:

| State/UT | 14 Women literate: CSV | printed | 15 Men literate: CSV | printed |
| --- | --- | --- | --- | --- |
| Andaman & Nicobar Islands | 86.6 / 85.6 / 86.0 | 81.4 / 79.9 / 80.5 | 89.3 / 94.7 / 92.5 | 81.4 / 92.7 / 88.2 |
| Andhra Pradesh | 79.0 / 63.8 / 68.6 | 77.0 / 62.0 / 66.7 | 86.4 / 76.3 / 79.5 | 83.9 / 73.2 / 76.5 |
| Assam | 87.5 / 75.4 / 77.2 | 86.0 / 73.2 / 75.1 | 92.6 / 82.8 / 84.3 | 91.1 / 79.9 / 81.6 |
| Bihar | 74.9 / 54.5 / 57.8 | 72.9 / 51.6 / 55.0 | 84.0 / 77.0 / 78.5 | 81.8 / 74.9 / 76.4 |
| Dadra & Nagar Haveli and Daman & Diu | 87.7 / 67.9 / 77.3 | 85.4 / 66.8 / 75.6 | 95.4 / 91.6 / 93.4 | 94.5 / 90.6 / 92.5 |
| Goa | 92.6 / 93.4 / 93.0 | 91.8 / 92.9 / 92.2 | 94.9 / 98.5 / 96.3 | 92.2 / 98.0 / 94.3 |
| Gujarat | 86.8 / 69.0 / 76.5 | 84.2 / 65.8 / 73.5 | 95.4 / 87.5 / 90.9 | 93.6 / 82.6 / 87.4 |
| Himachal Pradesh | 95.0 / 91.2 / 91.7 | 94.0 / 90.2 / 90.7 | 91.7 / 95.4 / 94.9 | 91.7 / 93.0 / 92.8 |
| Jammu & Kashmir | 84.3 / 74.7 / 77.3 | 81.9 / 71.6 / 74.3 | 91.8 / 91.4 / 91.5 | 91.0 / 89.9 / 90.2 |
| Karnataka | 85.1 / 71.0 / 76.7 | 81.9 / 67.7 / 73.4 | 90.5 / 87.0 / 88.5 | 87.4 / 83.6 / 85.2 |
| Kerala | 99.1 / 97.5 / 98.3 | 98.5 / 96.3 / 97.4 | 99.2 / 97.4 / 98.2 | 98.7 / 95.8 / 97.1 |
| Ladakh | 77.7 / 76.6 / 76.8 | 77.0 / 74.0 / 74.6 | 91.9 / 94.2 / 93.7 | 91.9 / 92.8 / 92.7 |
| Lakshadweep | 96.4 / 96.8 / 96.5 | 95.3 / 94.6 / 95.2 | 100.0 / 96.3 / 99.1 | 100.0 / (94.5) / 98.6 |
| Maharashtra | 90.2 / 79.5 / 84.6 | 88.2 / 76.9 / 82.3 | 94.6 / 91.5 / 93.0 | 91.9 / 88.6 / 90.2 |
| Manipur | 92.1 / 84.8 / 87.6 | 90.2 / 82.3 / 85.3 | 96.9 / 94.0 / 95.2 | 94.8 / 92.3 / 93.4 |
| Meghalaya | 97.1 / 85.5 / 88.2 | 96.6 / 84.9 / 87.6 | 92.9 / 81.5 / 83.7 | 92.9 / 80.9 / 83.2 |
| Mizoram | 99.1 / 87.7 / 94.4 | 99.0 / 87.0 / 94.0 | 99.2 / 94.2 / 97.1 | 99.2 / 94.0 / 97.0 |
| Nagaland | 91.5 / 82.7 / 85.8 | 90.2 / 79.8 / 83.4 | 97.7 / 90.7 / 93.3 | 97.2 / 89.3 / 92.2 |
| Sikkim | 92.8 / 86.2 / 88.9 | 91.9 / 83.8 / 87.1 | 96.9 / 90.3 / 93.0 | 87.4 / 89.4 / 88.6 |
| Telangana | 81.0 / 58.1 / 66.6 | 78.6 / 56.6 / 64.8 | 90.2 / 81.3 / 84.8 | 87.2 / 78.4 / 82.0 |
| Tripura | 89.9 / 76.9 / 80.6 | 88.9 / 74.1 / 78.3 | 93.5 / 86.0 / 88.2 | 92.2 / 80.0 / 83.6 |
| West Bengal | 83.4 / 72.5 / 76.1 | 80.6 / 69.2 / 72.9 | 89.8 / 77.8 / 81.6 | 88.8 / 76.2 / 80.2 |

(132 cells; 5 are equal in both editions: Himachal Pradesh, Ladakh and
Lakshadweep 15 Urban, Meghalaya and Mizoram 15 Urban.)

### Class a: the CSV is wrong

Compendium pages; the CSV note "( )" is "Based on 25-49 unweighted cases".

| District | Page | Indicator | Column | CSV | Printed | Evidence |
| --- | --- | --- | --- | --- | --- | --- |
| Kangra, Himachal Pradesh | 31 | 16 | NFHS-4 | blank | `2.4` (printed above the row's baseline) | `kangra_16.png` |
| Chamba, Himachal Pradesh | 19 | 31 | NFHS-4 | blank, note ( ) | `*` | `chamba_31.png` |
| Bellary, Karnataka | 39 | 94, 97 | NFHS-4 | blank, note ( ) | `na` | `bellary_94-97.png` |
| Chitradurga, Karnataka | 75 | 94, 97 | NFHS-4 | blank, note ( ) | `na` | `chitradurga_94-97.png` |
| Koppal, Karnataka | 135 | 94, 97 | NFHS-4 | blank, note ( ) | `na` | `koppal_94-97.png` |
| Raigarh, Maharashtra | 171 | 97 | NFHS-5 | 26.4, note ( ) | `26.4` | `raigarh_97.png` |
| Raigarh, Maharashtra | 171 | 97 | NFHS-4 | blank, note ( ) | `na` | `raigarh_97.png` |

### Class c: misprinted pages

| District | Page | What the page prints | CSV | Evidence |
| --- | --- | --- | --- | --- |
| Mahisagar, Gujarat | 121 | No row "10."; rows 11-32 are indicators 10-31 by their labels, so "32." appears on pages 121 and 122 | Renumbered by label; every value equal after the shift | `mahisagar_9-12.png` |
| Wardha, Maharashtra | 211 | The same: no "10.", rows 11-32 are indicators 10-31 | Renumbered by label; every value equal after the shift | `wardha_9-12.png` |
| Dhule, Maharashtra | 63 | Row 101 (women's tobacco use) with no values | Blank values, both with note ( ) | `dhule_101.png` |

The vote keys rows by the printed number, so on Mahisagar and Wardha it
compares the printed row 11 with the CSV's 11 and so on: 65 cells differ (22
and 43; one Wardha cell is equal by chance). The CSV's indicator 10 for the
two districts (3 cells) and Dhule's 101 (2 cells) have no printed cell to
compare with.

### Class d: naming and alignment

No values differ. The CSVs' State names are the page titles; the district CSV
spells the State "Andaman and Nicobar Island" and "Jammu and Kashmir" in its
State column (the district names match). Two Rajasthan titles print no comma
("Jalor Rajasthan - Key Indicators", "Sikar ..."; Rajasthan is not in the
CSV), and Dadra & Nagar Haveli's title wraps onto two lines (the parser joins
them). The State CSV's
labels drop the "Women"/"Men" subheadings, so indicators 113 and 114 have the
same label.

### Class b: parser fixes made during this check

Each was found by a disagreement or a short count, fixed in
`examples/nfhs5/nfhs5_factsheet.py`, and is covered by `tests/test_nfhs5_factsheet.py`:

* A district with no comparable NFHS-4 estimate (boundaries changed, or newly
  formed) has one value column (132 districts).
* Kangra's raised NFHS-4 value comes on a line before its row's label.
* Text outside the page box: Raigarh's page 171 holds stray `na` tokens right
  of the page (x = 606 pt on a 595 pt page). pdfexorcist grows page boxes to
  cover all text, so the engines read a third value on rows 100 and 101; the
  parser now drops tokens right of the table.
* Titles with an en dash (North & Middle Andaman) or wrapped over two lines.
* A compendium's contents page ("1. North Goa  7") was read as indicators 1
  and 2.
* `1037` printed without a thousands separator (Gondiya's NFHS-4 sex ratio).

### FR375

FR375 tables that print the same quantity as a fact sheet indicator, read
from its text layer (pdftotext, with page boxes as they are; see below), for
India and the 36 States/UTs:

| FR375 table | Fact sheet indicator | Cells | = vote (fact sheet) | = CSV |
| --- | --- | --- | --- | --- |
| 2.17 Birth registration, Urban / Rural / Total | 5 | 111 | 106 | 106 |
| 2.19 Death registration, Urban / Rural / Total (both sexes) | 6 | 111 | 10 | 10 |
| 3.4.1 Percentage literate, women | 14 Total | 37 | 36 | 15 |
| 3.4.2 Percentage literate, men | 15 Total | 37 | 34 | 14 |

The fact sheets are labelled provisional and the report uses the final data,
so small differences are expected (death registration differs in most
States by a few tenths). Literacy is the useful case: the report agrees with
the 2021 fact sheets, not with the CSV.

pdfexorcist cannot read FR375 as published: each page carries the facing
page's text outside its media box (an InDesign spread export, at x = -500
pt). pdfplumber and PDFium read that text, and pdfexorcist grows the page box
to cover it, so every engine reads the two pages' tables side by side.
