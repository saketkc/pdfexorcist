---
description: "Small pdfexorcist recipes for the settings the gallery leaves at their defaults: the columns parser, column checks, tolerances, page selection, page boxes, voting rules, families, cleaning functions and output formats."
---

# Other recipe settings

The gallery recipes leave many settings at their defaults. Each recipe here changes a few of them and runs on a gallery fixture. The generic ones are in `examples/settings/`; the others sit next to the recipe they vary, so they can use its Python. `tests/test_recipe_docs_examples.py` runs each one. Every setting is listed in the [format reference](../recipes.md#format-reference).

## Rows or columns, and a total column

Table 1A.4 of Crime in India 2023 prints, for each State/UT, road-accident deaths three times: in total, by Hit and Run, and by Other Accidents. Each has Incidence, Victims and Rate, so total incidence equals Hit and Run incidence plus Other incidence. Dadra and Nagar Haveli and Daman and Diu wraps its name around its row, which leaves the serial number `31` at the start of the line.

`examples/settings/cii_rows.toml` reads the page with the `rows` parser and checks that total column:

```toml
name = "Crime in India 1A.4, rows parser"
sample = "../../tests/fixtures/cii/cii_2023_1A.4_p47.pdf"

[parser]
type = "rows"
min_values = 3

[[checks]]
column = "col"
total = 0          # the total and its parts, instead of a rule
parts = [3, 6]
op = "="
by = ["page", "row"]  # one check per line
name = "Total I = Hit and Run I + Other I"

[output]
layout = "table"
format = "csv"
```

```bash
pdfexorcist extract tests/fixtures/cii/cii_2023_1A.4_p47.pdf --recipe examples/settings/cii_rows.toml -o cii_rows.csv
```

```
Agreed         352  97.5% of cells
Unresolved       9  engines disagreed: left blank, not guessed
Failed checks    3  agreed values that break a rule
  x Total I = Hit and Run I + Other I: 3 cells

Wrote cii_rows.csv (table layout, 40 rows).
Cells to review, with the reason and every engine's reading: cii_rows.review.csv
Some agreed values break a rule (see the failed column), so the exit code is 1.
```

```
page,label,0,1,2,3,4,5,6,7,8,9
1,1 Andhra Pradesh,7488,8036,14.1,549,575,1.0,6939,7461,13.0,
...
1,,31,77,91,6.0,36,36,2.8,41,55,3.2
```

The `rows` parser numbers values in reading order, so on the unlabelled line `31` becomes column 0 and every value moves one column right. 31 is not 6.0 + 2.8, so those cells fail the check.

`examples/settings/cii_columns.toml` reads the same page with the `columns` parser, which puts each value in the column it sits under. Its parts that differ:

```toml
[parser]
type = "columns"
min_values = 3
tolerance = 0.6  # default 0.45; see below

[[checks]]
column = "col"
total = 1          # the serial number is now column 0
parts = [4, 7]
by = ["page", "row"]
missing = "fail"   # a row with a total but without a part fails
name = "Total I = Hit and Run I + Other I"

[output]
layout = "table"
format = "xlsx"
```

```bash
pdfexorcist extract tests/fixtures/cii/cii_2023_1A.4_p47.pdf --recipe examples/settings/cii_columns.toml -o cii_columns.xlsx
```

```
  pdftotext   387 readings  0.0s
  pdfplumber  387 readings  0.1s
  pymupdf     387 readings  0.0s
  camelot     387 readings  0.3s
  pdfium      387 readings  0.0s

Agreed         387  97.5% of cells
Unresolved      10  engines disagreed: left blank, not guessed
Checks      1 rule  all passed

Wrote cii_columns.xlsx (table layout, 40 rows).
Cells to review, with the reason and every engine's reading: the review sheet.
```

The `table` sheet, as CSV:

```
page,label,0,1,2,3,4,5,6,7,8,9
1,Andhra Pradesh,1,7488,8036,14.1,549,575,1.0,6939,7461,13.0
...
1,,31,77,91,6.0,36,36,2.8,41,55,3.2
1,D&N Daman Haveli & Diu and,,,,,,,,,,
```

The serial numbers have a column of their own, and the unlabelled row's values stay in theirs. Its name, read apart from its values, is a row of its own; only PyMuPDF reads it as a line with values, so its cells are unresolved and on the `review` sheet.

`tolerance` is how far, in column spacings, a value may sit from its column before it is dropped. pdftotext places text by character column, which is coarser than the other engines' points: at the default 0.45 it drops a few values, at 0.6 none.

## A rounded total

Column 3 of Crime in India 2021 Table 1A.1 is the mid-year population in lakhs, rounded to 0.1. The States and UTs add up to 13672.0, and the page prints 13671.8 for All India. `examples/settings/cii_population.toml` allows a relative gap and writes one row per cell:

```toml
name = "Crime in India 1A.1, population"
sample = "../../tests/fixtures/cii/cii_2021_1A.1_p43.pdf"

[pages]
select = "1"

[parser]
type = "rows"
min_values = 3

[[checks]]
column = "label"
rule = "TOTAL ALL INDIA = rest"
by = ["page", "col"]
where = "col == 3 and label != 'TOTAL STATE(S)' and label != 'TOTAL UT(S)'"
tolerance = 0.0001  # 0.01% of the total: 1.4 lakh here

[output]
layout = "cells"
format = "json"
```

```bash
pdfexorcist extract tests/fixtures/cii/cii_2021_1A.1_p43.pdf --recipe examples/settings/cii_population.toml -o population.json
```

```
Agreed         234  100.0% of cells
Unresolved       0
Checks      1 rule  all passed

Wrote population.json (cells layout).
```

One record:

```json
 {
  "page": 1,
  "row": "totalallindia#1",
  "col": 3,
  "label": "TOTAL ALL INDIA",
  "value": "13671.8",
  "status": "verified",
  "failed": "",
  "n_agree": 5,
  "votes": "13671.8×5",
  "sources": "camelot|pdfium|pdfplumber|pdftotext|pymupdf",
  "dissent": ""
 }
```

Without `tolerance` the rule fails on the 0.2 gap. `abs_tolerance` allows a fixed gap instead, as in the [population projections](census-projections.md).

## Pages by number

`examples/crs_state_tables/table4.toml` is the CRS recipe with `[pages] select = "2"`: the fixture holds Table 1 on page 1 and Table 4 (still births) on page 2.

```toml
[pages]
select = "2"
```

```bash
pdfexorcist extract tests/fixtures/crs/crs_2023_t1_t4.pdf --recipe examples/crs_state_tables/table4.toml -o table4.csv
```

```
Reading page 2 of tests/fixtures/crs/crs_2023_t1_t4.pdf with 5 engines (a majority must agree),
recipe examples/crs_state_tables/table4.toml
...
Agreed          324  97.3% of cells
Unresolved        9  engines disagreed: left blank, not guessed
Checks      2 rules  all passed
```

```
page,label,Rural_Male,Rural_Female,Rural_Person,Urban_Male,Urban_Female,Urban_Person,Total_Male,Total_Female,Total_Person
2,India,,,,,,,,,
2,Andhra Pradesh,435,390,825,589,583,1172,1024,973,1997
```

The output keeps the page's number in the original file. The unresolved cells are the India row, as in the [full run](crs.md).

## Page boxes

`examples/mccd/unfitted.toml` is the MCCD Table 4 recipe with `[pages] fit_boxes = false`, run on the 2011 fixture: a two-page spread drawn half outside its page box. By default pdfexorcist widens each page box to cover its text before the engines read it. Without that:

```toml
[pages]
fit_boxes = false
```

```bash
pdfexorcist extract tests/fixtures/mccd/mccd_2011.pdf --recipe examples/mccd/unfitted.toml -o unfitted.csv
```

```
  pdftotext   1,782 readings  0.0s
  pdfplumber  1,782 readings  0.2s
  pymupdf     1,782 readings  0.0s
  camelot     3,564 readings  11.6s
  pdfium      1,782 readings  0.1s

Agreed         1,782  50.0% of cells
Unresolved     1,782  engines disagreed: left blank, not guessed
Failed checks    768  agreed values that break a rule
  x state 'All States (Total)' >= the rest, within each page, code, pocc, sex: 768 cells
Note: 1,044 agreed cells were read with different values in different places (e.g. two pages); left
blank in the table and listed for review.
```

Four engines read only the half inside the box; camelot reads all of it. Half the cells have no majority, and on page 2 the clipped reading starts at another column, so its values are named after the wrong States and the All States check fails. With the default, every cell agrees. Set `fit_boxes = false` only when the text outside a box belongs to another page, as in the NFHS-5 India Report ([NFHS-5 fact sheets](nfhs5-factsheets.md#checked-against-an-independent-extraction)).

## Every engine must agree

`examples/nfhs6/unanimous.toml` is the NFHS-6 State recipe with these `[engines]` settings:

```toml
[engines]
use = ["pdftotext", "pdfplumber", "pymupdf", "camelot", "pdfium"]
min_agree = 5
min_unopposed = 3
```

`min_agree = 5` alone, given here on the command line with `-k 5`:

```bash
pdfexorcist extract tests/fixtures/nfhs6_state/nfhs6_chandigarh_p145-147.pdf --recipe examples/nfhs6/state.toml -k 5 -o chandigarh.csv
```

```
Reading tests/fixtures/nfhs6_state/nfhs6_chandigarh_p145-147.pdf with 5 engines (5 must agree),
recipe examples/nfhs6/state.toml
  pdftotext   404 readings  0.0s
  pdfplumber  404 readings  0.4s
  pymupdf     404 readings  0.0s
  camelot     384 readings  0.8s
  pdfium      276 readings  0.0s

Agreed          260  64.4% of cells
Unresolved      144  engines disagreed: left blank, not guessed
Checks      2 rules  all passed
```

pdfium and camelot read nothing for some values, so those cells cannot reach 5. `min_unopposed = 3` also accepts a value that 3 engines read when no engine read another:

```bash
pdfexorcist extract tests/fixtures/nfhs6_state/nfhs6_chandigarh_p145-147.pdf --recipe examples/nfhs6/unanimous.toml -o chandigarh.csv --force
```

```
Agreed          404  100.0% of cells
Unresolved        0
Checks      2 rules  all passed
```

A value two engines read differently still needs all five. `use` names the engines, so one that is not installed is an error instead of a smaller vote.

## Engines that vote once

pdfplumber and camelot both read the text layer with pdfminer, so a pdfminer misreading would count twice. `examples/nfhs5/families.toml` is the NFHS-5 State recipe with:

```toml
[engines]
families = { pdfminer = ["pdfplumber", "camelot"] }
```

The two settle on one value first, and that value counts as one vote. Five engines make four voters, and 3 must agree.

```bash
pdfexorcist extract tests/fixtures/nfhs5_state/nfhs5_chandigarh_p3-6.pdf --recipe examples/nfhs5/families.toml -o chandigarh.csv
```

```
  pdftotext   476 readings  0.0s
  pdfplumber  524 readings  0.4s
  pymupdf     524 readings  0.0s
  camelot     472 readings  1.0s
  pdfium      68 readings  0.1s

Agreed          477  91.0% of cells
Unresolved       47  engines disagreed: left blank, not guessed
Checks      2 rules  all passed
```

Most cells lost against the [plain run](nfhs5-factsheets.md#run-it) were read only by pdfplumber, camelot and PyMuPDF: two independent readings, not three. On row 126, pdfplumber and camelot read different values, so the family casts no vote. Families matter most for a PDF whose text layer came from OCR, where every text engine repeats one reading. See [Engines](../engines.md#families).

## Cleaning values

`examples/nfhs5/numbers.toml` is the NFHS-5 State recipe with numbers cleaned before the vote and Parquet output:

```toml
[normalize]
remove_commas = true            # "5,586" -> "5586"
function = "clean.py:drop_na"   # "na" -> no reading, so a blank cell

[output]
format = "parquet"
```

`clean.py`, next to the recipe:

```python
def drop_na(value: str) -> str | None:
    """Return the value to vote on, or None to drop the reading."""
    return None if value == "na" else value
```

```bash
pdfexorcist extract tests/fixtures/nfhs5_state/nfhs5_chandigarh_p3-6.pdf --recipe examples/nfhs5/numbers.toml -o chandigarh.parquet
```

```
Agreed          490  99.4% of cells
Unresolved        3  engines disagreed: left blank, not guessed
Checks      2 rules  all passed

Wrote chandigarh.parquet (table layout, 131 rows).
Cells to review, with the reason and every engine's reading: chandigarh.review.parquet
```

Read back with pandas (`pd.read_parquet("chandigarh.parquet")`), rows 3, 6 and 47:

```
       geo  indicator_no level nfhs5_urban nfhs5_rural nfhs5_total nfhs4_total
Chandigarh             3 state         918         868         917         934
Chandigarh             6 state        93.6           *        93.6         NaN
Chandigarh            47 state        5586           *        5546        2357
```

The `na` readings are gone; brackets and `*` are kept. The values stay text in the Parquet file.

## Printed numbers that need cleaning

`tests/fixtures/synthetic/cleaning.pdf` is a small synthetic table (`make_fixtures.py` next to it builds it). It prints numbers the way some reports do: raised-dot decimals (`65·3`), Unicode minus signs (`−4·0`), a footnote mark (`13·4*`) and a small-sample value in brackets (`(7·0)`). `examples/settings/cleaning.toml` cleans them before the vote and checks the table after it:

```toml
[normalize]
raised_dots = true             # "65·3" -> "65.3"
minus_signs = true             # "−4.0" -> "-4.0"
remove_footnote_marks = true   # "13.4*" -> "13.4"

[parser]
type = "rows"

[postprocess]
function = "numbers.py:add_number"   # adds `number`: "(7.0)" -> 7.0

[[checks]]
column = "col"
total = 2
parts = [0, 1]
by = ["page", "row"]
value = "number"
name = "Total = A + B"

[[checks]]
column = "label"
rule = "All regions = rest"
by = ["page", "col"]
value = "number"
```

`numbers.py`, next to the recipe:

```python
def add_number(cells: pd.DataFrame, pdf: object) -> pd.DataFrame:
    text = cells["value"].astype(str).str.strip("()")
    return cells.assign(number=pd.to_numeric(text, errors="coerce"))
```

```bash
pdfexorcist extract tests/fixtures/synthetic/cleaning.pdf --recipe examples/settings/cleaning.toml -o cleaning.csv
```

```
Agreed           12  100.0% of cells
Unresolved        0
Checks      2 rules  all passed
```

```
page,label,0,1,2
1,North,65.3,-4.0,61.3
1,South,12.5,(7.0),19.5
1,East,500.0,13.4,513.4
1,All regions,577.8,16.4,594.2
```

The checks read `number` (`value = "number"`): `(7.0)` is not a number, so a check on `value` would leave the South row unchecked. The cell itself keeps its brackets.

## OCR for an image

`examples/settings/cleaning_ocr.toml` reads the same table from an image, `cleaning.png`. An image has no text layer, so `ocr = true` adds every installed OCR engine; a majority of them, at least 2, must agree:

```toml
[engines]
ocr = true

[parser]
type = "columns"   # OCR engines place words by x; values go to the nearest column
```

```bash
pdfexorcist extract tests/fixtures/synthetic/cleaning.png --recipe examples/settings/cleaning_ocr.toml -o cleaning.csv
```

```
Reading tests/fixtures/synthetic/cleaning.png with 5 engines (3 must agree), recipe
examples/settings/cleaning_ocr.toml
  tesseract  0 readings  0.2s
  chandra    12 readings  0.0s
  paddleocr  12 readings  6.0s
  ocrmac     8 readings  26.2s
  glmocr     12 readings  3.0s
  tesseract read no values on these pages.

Agreed          12  85.7% of cells
Unresolved       2  engines disagreed: left blank, not guessed
Checks      1 rule  all passed
```

Every cell of the table is agreed and equals the PDF's. The unresolved cells are a row only one engine read (`East 13.4.`). The engines depend on what is installed (`pdfexorcist engines`); the [lake photo](../recipes.md#example-a-photographed-table) names its OCR engines with `use` instead.
