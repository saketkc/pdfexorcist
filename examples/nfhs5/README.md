# NFHS-5 fact sheets

Two recipes share one parser, `nfhs5_factsheet.py`, which the tests import.

## The State sheet: state.toml

`state.toml` reads the "Key Indicators" pages of the NFHS-5 (2019-21) fact
sheets that IIPS publishes for India and each State/UT: 131 indicators over
four pages, with NFHS-5 Urban, Rural and Total, and NFHS-4 Total.

The generic parsers cannot read these pages:

* A row is named by its printed indicator number. A wrapped label puts the
  row's values on a line of their own, between its two label lines.
* Footnote marks sit in the labels ("source1", "facility 2", "birth 15 (%)"),
  and some engines split them off as a cell of their own.
* Values are kept as printed: `(45.6)` is a small-sample value, `*` a
  suppressed one, `na` not available, and `1,020` (sex ratio), `27`
  (adolescent fertility rate) and `3,385` (Rs.) are not percentages.

So the recipe points to `nfhs5_factsheet.py`, the parser
`tests/test_nfhs5_factsheet.py` checks. A row yields values only when it
holds exactly four, so a value one engine missed cannot shift the others. Two
rules run after the vote: no percentage over 100, and every Total between
its Urban and Rural (TFR and the three mortality rates left out).

### Run it

```bash
pdfexorcist extract tests/fixtures/nfhs5_state/nfhs5_chandigarh_p3-6.pdf --recipe examples/nfhs5/state.toml -o chandigarh.csv
```

```
Reading tests/fixtures/nfhs5_state/nfhs5_chandigarh_p3-6.pdf with 5 engines (a majority must agree),
recipe examples/nfhs5/state.toml
  pdftotext   476 readings  0.0s
  pdfplumber  524 readings  0.5s
  pymupdf     524 readings  0.0s
  camelot     472 readings  1.1s
  pdfium      68 readings  0.1s

Agreed          521  99.4% of cells
Unresolved        3  engines disagreed: left blank, not guessed
Checks      2 rules  all passed

Wrote chandigarh.csv (table layout, 131 rows).
Cells to review, with the reason and every engine's reading: chandigarh.review.csv
```

```
geo,indicator_no,level,nfhs5_urban,nfhs5_rural,nfhs5_total,nfhs4_total
Chandigarh,1,state,86.8,(69.2),86.7,83.7
Chandigarh,3,state,918,868,917,934
Chandigarh,6,state,93.6,*,93.6,na
Chandigarh,47,state,"5,586",*,"5,546","2,357"
Chandigarh,67,state,(92.8),*,(92.9),(93.1)
Chandigarh,68,state,,*,,
```

Row 68 is left blank: camelot reads it with row 40's numbers, and only
pdfplumber and PyMuPDF read it as printed (`(7.2)`, `(7.1)`, `(6.9)`). Its
readings are in `chandigarh.review.csv`.

### The whole fact sheet

The `[pages]` pattern keeps the four "<State> - Key Indicators" pages of a
whole IIPS sheet (cover, introduction and back page are skipped):

```bash
pdfexorcist extract NFHS-5_StateAndUTFact_Bihar__Bihar.pdf --recipe examples/nfhs5/state.toml -o bihar.csv
```

On the India sheet and every State & UT sheet (September and December 2021
editions, from nfhsiips.in) this agrees on every value but Chandigarh's row
68, and every rule holds. Each agreed value equals
[pratapvardhan/NFHS-5](https://github.com/pratapvardhan/NFHS-5)'s
`NFHS-5-States.csv` except the literacy cells (indicators 14 and 15) of the
phase-1 States/UTs, where that CSV has the December 2020 edition's values;
see `tests/fixtures/nfhs5_state/VERIFICATION.md`.

## District compendiums: district.toml

`district.toml` reads the "Key Indicators" pages of a State's NFHS-5 (2019-21)
compendium from IIPS: 104 indicators per district over three pages, with
NFHS-5 Total and NFHS-4 Total, or NFHS-5 Total alone where NFHS-4 has no
comparable estimate (boundaries changed, or a new district). The compendium
opens with the State's own sheet (four columns), which the same parser reads.

It uses the same parser: rows by their printed indicator number,
values kept as printed (`(45.6)` small sample, `*` suppressed, `na` not
available), and a row yields values only when it holds exactly the page's
number of columns. The district pages add a few cases:

* A value printed above its row's baseline (Kangra's row 16, NFHS-4 `2.4`) is
  read before the row's label; it is held for the next numbered row.
* Text outside the page box (stray `na` tokens beside Raigarh's rows 100 and
  101, never printed) lies right of the table and is dropped.
* The contents page ("1. North Goa  7") is not an indicator page, and some
  titles use an en dash ("North & Middle Andaman, Andaman & Nicobar Islands –
  Key Indicators") or wrap onto a second line.

### Run it

```bash
pdfexorcist extract tests/fixtures/nfhs5_district/nfhs5_kangra_p31-33.pdf --recipe examples/nfhs5/district.toml -o kangra.csv
```

```
Reading tests/fixtures/nfhs5_district/nfhs5_kangra_p31-33.pdf with 5 engines (a majority must
agree), recipe examples/nfhs5/district.toml
  pdftotext   208 readings  0.0s
  pdfplumber  208 readings  0.3s
  pymupdf     208 readings  0.0s
  camelot     208 readings  0.8s
  pdfium      202 readings  0.0s

Agreed          208  100.0% of cells
Unresolved        0
Checks      2 rules  all passed

Wrote kangra.csv (table layout, 104 rows).
```

```
geo,indicator_no,level,nfhs5_total,nfhs4_total
"Kangra, Himachal Pradesh",1,district,84.1,83.4
"Kangra, Himachal Pradesh",3,district,"1,051","1,107"
"Kangra, Himachal Pradesh",13,district,1.2,na
"Kangra, Himachal Pradesh",16,district,1.5,2.4
"Kangra, Himachal Pradesh",40,district,*,*
"Kangra, Himachal Pradesh",49,district,(83.9),(68.6)
```

### A misnumbered page

Mahisagar, Gujarat (one value column) skips "10." on its first page and
prints 11-32 for indicators 10-31, so the number 32 appears on two pages. The
parser keeps the printed numbers. The vote is keyed by page, so both rows 32
are agreed, but they share one table row: the table leaves it blank and both
go to the review file.

```bash
pdfexorcist extract tests/fixtures/nfhs5_district/nfhs5_mahisagar_p121-123.pdf --recipe examples/nfhs5/district.toml -o mahisagar.csv
```

```
Agreed          104  100.0% of cells
Unresolved        0
Checks      2 rules  all passed
Note: 2 agreed cells were read with different values in different places (e.g. two pages); left
blank in the table and listed for review.

Wrote mahisagar.csv (table layout, 103 rows).
```

### A whole compendium

The `[pages]` pattern keeps only the indicator pages, so a whole compendium
can be read at once, such as Goa's (the State and two districts):

```bash
pdfexorcist extract NFHS-5_StateFact_Goa__Goa.pdf --recipe examples/nfhs5/district.toml -o goa.csv
```

On every compendium the vote agrees on every district value, and every rule
holds. Two Rajasthan titles print no comma ("Jalor Rajasthan"); `geo` is kept
as printed. `tests/fixtures/nfhs5_state/VERIFICATION.md` lists where the
districts in [pratapvardhan/NFHS-5](https://github.com/pratapvardhan/NFHS-5)'s
`NFHS-5-Districts.csv` differ from it.
