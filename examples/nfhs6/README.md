# NFHS-6 fact sheets

Two recipes share one parser, `nfhs6_factsheet.py`, which the tests import.

## The State sheet: state.toml

`state.toml` reads the "Key Indicators" pages of the NFHS-6 (2023-24) fact
sheets that IIPS publishes for India and each State/UT: 101 indicators over
three pages, with NFHS-6 Urban, Rural and Total, and NFHS-5 Total.

The generic parsers cannot read these pages:

* A row is named by its printed indicator number. A wrapped label puts the
  row's values on a line of their own, between its two label lines.
* Some labels are drawn as graphics (the rows with a "≥" sign), so the text
  layer holds only the bare number ("76", "85"), or on some States' pages
  nothing. A bare number is taken only as the next indicator in sequence; a row
  with no number at all is not read.
* Footnote marks sit in the labels ("source1", "period18"), and some engines
  split them off as a cell of their own.
* Values are kept as printed: `(45.6)` is a small-sample value, `*` a
  suppressed one.

So the recipe points to `nfhs6_factsheet.py`, the parser
`tests/test_nfhs6_factsheet.py` checks against verified values. A row yields
values only when it holds exactly four, so a value one engine missed cannot
shift the others. Two rules run after the vote: no percentage over 100 (the
total fertility rate is not a percentage), and every Total between its Urban
and Rural.

### Run it

```bash
pdfexorcist extract tests/fixtures/nfhs6_state/nfhs6_chandigarh_p145-147.pdf --recipe examples/nfhs6/state.toml -o chandigarh.csv
```

```
Reading tests/fixtures/nfhs6_state/nfhs6_chandigarh_p145-147.pdf with 5 engines (a majority must
agree), recipe examples/nfhs6/state.toml
  pdftotext   404 readings  0.0s
  pdfplumber  404 readings  0.4s
  pymupdf     404 readings  0.0s
  camelot     384 readings  0.9s
  pdfium      276 readings  0.0s

Agreed          404  100.0% of cells
Unresolved        0
Checks      2 rules  all passed

Wrote chandigarh.csv (table layout, 101 rows).
```

```
geo,indicator_no,level,nfhs6_urban,nfhs6_rural,nfhs6_total,nfhs5_total
Chandigarh,1,state,6.1,6.1,6.1,5.9
Chandigarh,2,state,20.6,21.2,20.7,23.3
Chandigarh,6,state,96.4,(97.7),96.5,96.8
Chandigarh,11,state,52.5,*,52.6,26.5
Chandigarh,17,state,*,*,*,*
Chandigarh,18,state,1.8,*,1.8,1.4
Chandigarh,39,state,*,*,(65.0),(44.3)
```

### The whole fact sheet

The `[pages]` pattern picks the "Key Indicators" pages of the full
`NFHS 6 factsheet.pdf`. Give it pages 26-171: the appendix pages after them
also match it but are not fact sheets, and their values fail the recipe's
checks.

```bash
pdfexorcist extract "NFHS 6 factsheet.pdf" --recipe examples/nfhs6/state.toml --pages 26-171 -o nfhs6_states.csv
```

Some pages (Andhra Pradesh, Rajasthan to West Bengal in the printed order,
A & N Islands, DNHDD, Ladakh and Lakshadweep) draw every glyph as a path, with
no text layer for the values: add `--ocr` for those. The Tamil Nadu fixture is
one such page:

```bash
pdfexorcist extract tests/fixtures/nfhs6_state/nfhs6_tamil_nadu_p115.pdf --recipe examples/nfhs6/state.toml --ocr -o tamil_nadu.csv
```

```
  tesseract   160 readings  2.3s
  chandra     160 readings  0.1s
  paddleocr   160 readings  61.1s
  ocrmac      156 readings  1.0s
  glmocr      160 readings  1.8s
  pdftotext read no values on these pages.
  ...

Agreed          160  100.0% of cells
Unresolved        0
Checks      2 rules  all passed
```

(Chandra's and GLM-OCR's reads were cached from an earlier run.)

On the geographies with a text layer every agreed value equals the value
nfhs6 verified but two: on Assam's indicator 20 and Goa's
21 (Total) the ".0" is drawn as a path while the digits are text, so every
text engine reads `71` and `39` where the page prints `71.0` and `39.0`. The
engines agree, so the vote cannot catch it. On some States' pages some of rows
76, 77, 85, 86, 88 and 89 are not read: their numbers are graphics too.

## District compendiums: district.toml

`district.toml` reads the "Key Indicators" pages of a State's NFHS-6 (2023-24)
compendium from IIPS: 93 indicators per district over three pages, with
NFHS-6 Total and NFHS-5 Total, or NFHS-6 Total alone for a district that
NFHS-5 did not report on. The compendium opens with the State's own sheet
(four columns), which the same parser reads.

It uses the same parser: rows by their printed indicator number,
values kept as printed (`(45.6)` small sample, `*` suppressed, `12` without
a decimal where the page prints none), and a row yields values only when it
holds exactly the page's number of columns. On a one-column page a number at
the end of a wrapped label ("... within 2 days") sits well left of the values
and stays label text.

### Run it

```bash
pdfexorcist extract tests/fixtures/nfhs6_district/nfhs6_anantapur_p15-17.pdf --recipe examples/nfhs6/district.toml -o anantapur.csv
```

```
Reading tests/fixtures/nfhs6_district/nfhs6_anantapur_p15-17.pdf with 5 engines (a majority must
agree), recipe examples/nfhs6/district.toml
  pdftotext   186 readings  0.0s
  pdfplumber  186 readings  0.3s
  pymupdf     186 readings  0.0s
  camelot     186 readings  0.7s
  pdfium      184 readings  0.0s

Agreed          186  100.0% of cells
Unresolved        0
Checks      2 rules  all passed

Wrote anantapur.csv (table layout, 93 rows).
```

```
geo,indicator_no,level,nfhs6_total,nfhs5_total
"Anantapur, Andhra Pradesh",1,district,8.8,7.5
"Anantapur, Andhra Pradesh",2,district,24.2,24.3
"Anantapur, Andhra Pradesh",4,district,100.0,99.6
"Anantapur, Andhra Pradesh",17,district,(13.0),*
```

Jhargram, West Bengal prints no NFHS-5 column, so its table has one value
column (camelot reads its middle page as a single cell; the other four
engines agree on every value):

```bash
pdfexorcist extract tests/fixtures/nfhs6_district/nfhs6_jhargram_p51-53.pdf --recipe examples/nfhs6/district.toml -o jhargram.csv
```

```
geo,indicator_no,level,nfhs6_total
"Jhargram, West Bengal",41,district,85.3
"Jhargram, West Bengal",42,district,*
"Jhargram, West Bengal",43,district,88.6
"Jhargram, West Bengal",44,district,(96.6)
```

### A whole compendium

The `[pages]` pattern keeps only the indicator pages, so a whole compendium
can be read at once; on Goa's (the State and two districts) every value
agrees with the values nfhs6 verified:

```bash
pdfexorcist extract goa_compendium.pdf --recipe examples/nfhs6/district.toml -o goa.csv
```
