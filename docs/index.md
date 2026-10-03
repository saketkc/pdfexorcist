---
description: "Extract tables from PDFs, scans and photos by majority vote across independent engines, from Python or the shell."
---

# pdfexorcist

```{image} assets/logo/logo.svg
:alt: pdfexorcist logo
:align: right
:width: 140px
```

`pdfexorcist` pulls tables out of PDFs, scans and photos. Several independent engines read every page, and a value is kept only when most of them read it identically.

A cell the engines disagree on is left blank, never guessed, and listed for review with every engine's reading.

## Quick start

### From the command line

```bash
pip install pdfexorcist
pdfexorcist extract report.pdf
```

```
Reading report.pdf with 5 engines (a majority must agree)
  pdftotext   242 readings  0.0s
  pdfplumber  242 readings  0.1s
  pymupdf     242 readings  0.0s
  camelot     237 readings  0.3s
  pdfium      243 readings  0.0s

Agreed      242  99.6% of cells
Unresolved    1  engines disagreed: left blank, not guessed

Wrote report.csv (table layout, 48 rows).
Cells to review, with the reason and every engine's reading: report.review.csv
```

`report.csv` holds the agreed values as a grid:

```
page,label,0,1,2,3,4,5
1,1 Andhra Pradesh,119229,188997,179611,528.5,339.9,92.9
1,2 Arunachal Pradesh,2590,2244,2626,15.4,170.9,51.7
1,3 Assam,123512,111558,119883,351.6,341.0,38.2
```

### In Python

```python
from pdfexorcist import extract

cells = extract("report.pdf")
print(cells.status.value_counts().to_dict())
# {'verified': 242, 'unresolved': 1}
```

`extract()` returns one row per cell, with the agreed `value`, the `votes` behind it and a `status`.

## How it works

1. Five text-layer engines read the PDF: pdftotext, pdfplumber, PyMuPDF, PDFium and camelot. For scans and photos, OCR engines read the pixels.
2. A parser turns each engine's lines into keyed cells, such as (page, row, column). The same parser runs on every engine's output.
3. In the vote, a cell is `verified` when a strict majority of engines, and at least 3, read the same value. Otherwise it is `unresolved`.
4. Your rules, such as "the total equals the sum of its parts", run on the verified values. A value that breaks one is kept and flagged in the `failed` column.

## What it does

* [Command line](cli.md): `extract`, `inspect`, `engines`, `show`, `compare` and `recipe`.
* [Python library](library.md): `extract()`, `vote()`, parsers, checks, your own engines.
* [Recipes](recipes.md): save the settings for one kind of table in a TOML file.
* [Engines](engines.md): which engines exist, what they read, and how the vote counts them.
* [See what it extracts](show.md): a page with a box on every cell, and the engines side by side.
* [Reference](reference/index.md): every public function.

```{toctree}
:hidden:

installation
cli
library
recipes
engines
show
reference/index
examples/index
changelog
```
