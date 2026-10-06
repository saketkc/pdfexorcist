---
description: "Runnable pdfexorcist recipes for real reports: MCCD, SRS, IIPS and MoHFW projections, CRS, Crime in India, a lake-level photo, NCVBDC's monthly malaria report, the NFHS-5 and NFHS-6 fact sheets, Maharashtra's Pravah dam report, two NTA NEET documents, and the less common recipe settings."
---

# Examples

Each example is a recipe in the repository's `examples/` folder and runs on a fixture in `tests/fixtures/`.

| Document | The table | What the recipe does |
| --- | --- | --- |
| [MCCD Table 4](mccd-table4.md) | Deaths by cause, sex and State: M/F/T blocks under rotated State names. | Pages found by title regex; a custom parser; State names read from the rotated headers after the vote. |
| [MCCD Tables 2, 5, 9](mccd.md) | The same M/F/T blocks by chapter, with States, age groups or years for columns. | Table 2 reuses Table 4's parser; Tables 5 and 9 share one keyed by Roman numeral, with column names read from the flat header. |
| [SRS life tables](srs.md) | One State a page: Total, Rural and Urban blocks of 19 ages x 12 values. | The State kept out of the key, so camelot (which drops the title) still votes; a survivorship check in Python. |
| [IIPS district projections](census-projections.md#iips-district-projections) | Two blocks a page: five years of Males and Females by single age. | Keyed by block position and printed year; the district from the table title, since some "District:" headers are wrong. |
| [MoHFW State projections](census-projections.md#mohfw-state-projections) | Person, Male and Female by age for six years, in thousands. | Keyed by year, age and sex only (one table crosses a page, one is titled PUNJAB); TOML checks with a rounding tolerance. |
| [CRS State Tables 1-4](crs.md) | A row per State/UT: Rural, Urban and Total by Male, Female and Person. | Table pages found by `match`; `area` and `sex` columns, so the `>=` totals are TOML checks. |
| [Crime in India](../recipes.md#example-a-text-table) | State/UT rows of counts and rates, then total rows. | The generic parser, cleaned numbers, totals that must add up. |
| [BMC lake levels](../recipes.md#example-a-photographed-table) | A phone photo: seven lakes, this year and the two before. | OCR engines only, with your own parser. |
| [NFHS-6 fact sheets](nfhs6-factsheets.md) | Key Indicators by State and district. | `examples/nfhs6/` (`state.toml`, `district.toml`): rows by printed indicator number, placeholders kept as printed, one parser for two layouts. |
| [NFHS-5 fact sheets](nfhs5-factsheets.md) | Key Indicators by State and district, 2019-21. | `examples/nfhs5/` (`state.toml`, `district.toml`): the NFHS-6 parser adapted, checked against an independent extraction. |
| [NEET (UG) 2024 press release](nta-notice.md) | Nine tables on five pages: highlights by year, language, gender, category, State. | One recipe for every table: cells keyed by table, row and column; checks catch a misprinted count. |
| [MMIS monthly malaria situation](mmis.md) | NCVBDC's monthly report: a small table of months under each trend graph, by State and indicator. | Cells keyed by the graph's place on the page; area and indicator from the graph title as extra columns; a TPR check and a check that catches a table under the wrong graph. |
| [Pravah dam storage](pravah.md) | Maharashtra's daily report: a row per dam, grouped by region and district. | Rows keyed by dam name, wrapped names joined, region and district carried from the headings; capacity and % checks. |
| [NTA NEET toppers](nta.md) | A scanned list: Sr. No., application number, name, gender, category, percentile, rank, State. | OCR engines only; rows keyed by Sr. No., wrapped cells joined to their row; rank and percentile order checks. |
| [Other settings](settings.md) | Pages of the documents above. | Small recipes for the settings the others leave at their defaults: the columns parser, column totals, tolerances, page boxes, voting rules, families, a cleaning function, the cells layout and the xlsx, parquet and json formats. |

The [Python library](../library.md) page has short examples for each function, and [Command line](../cli.md) for each command.

`tests/test_examples_gallery.py`, `tests/test_nfhs6_examples.py`, `tests/test_nfhs5_examples.py`, `tests/test_recipe_docs_examples.py` and `tests/test_recipe.py` run the commands on these pages; `test_recipe.py` also checks that every recipe in `examples/` is valid.

## Regression tests

Each test pairs a document parser with values checked against the printed page. It fails on a wrong voted value, a drop in coverage, or broken table arithmetic.

| Test | Document |
| --- | --- |
| `test_bmc_lake_report.py` | BMC daily lake levels (photos, OCR) |
| `test_mccd_table4.py` | MCCD Table 4, cause x State x sex (2009, 2011, 2014) |
| `test_mccd_tables.py` | MCCD Tables 2, 5 and 9: chapter x State, age group or year x sex (2018, 2019) |
| `test_srs_life_table.py` | SRS abridged life tables |
| `test_adsi_state_table.py` | NCRB ADSI State/UT tables (2023, 2024; a 1995 scan with OCR) |
| `test_cii_state_table.py` | NCRB Crime in India State/UT tables (2021, 2023, 2024) |
| `test_mohfw_state_projection.py` | MoHFW population projections by age and sex |
| `test_iips_district_projection.py` | IIPS district projections by single age and sex |
| `test_mmis_malaria.py` | NCVBDC Monthly Malaria Situation, Category II (October 2023) |
| `test_pravah_dams.py` | Maharashtra WRD Pravah daily dam storage |
| `test_nta_toppers.py` | NTA NEET (UG) 2026 toppers list (a scan, OCR) |
| `test_nta_notice.py` | NTA NEET (UG) 2024 press release: nine tables in one recipe |
| `test_crs_state_table.py` | CRS State Tables 1 and 4: births and still births by State, sex and residence (2023) |
| `test_nfhs6_factsheet.py` | NFHS-6 Key Indicators fact sheets, India, States and districts (an outlined page, OCR) |
| `test_nfhs5_factsheet.py` | NFHS-5 Key Indicators fact sheets, India, States and districts (2019-21) |

The OCR tests are slow, so they run on request:

```bash
PDFEXORCIST_OCR_TESTS=1 python -m pytest tests/test_bmc_lake_report.py -s
```

```{toctree}
:hidden:

mccd-table4
mccd
srs
census-projections
crs
nfhs6-factsheets
nfhs5-factsheets
nta-notice
mmis
pravah
nta
settings
```
