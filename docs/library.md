---
description: "extract(), vote(), parsers, checks and custom engines in the pdfexorcist Python library, with runnable examples."
---

# Python library

`extract()` runs the whole pipeline: engines, parser, vote, checks. You can replace each step with your own function.

The examples read `report.pdf`, a copy of `tests/fixtures/cii/cii_2021_1A.1_p43.pdf` (NCRB Crime in India, Table 1A.1).

## Extract a table

```python
from pdfexorcist import extract

cells = extract("report.pdf")
print(cells.status.value_counts())
```

```
status
verified      242
unresolved      1
```

The result is a pandas DataFrame with one row per cell:

| Column | Meaning |
| --- | --- |
| `page`, `row`, `col` | The cell's key from the default parser: page, row label with its occurrence, value's place in the row. |
| `label` | The row's text. |
| `value` | The agreed value; empty when unresolved. |
| `status` | `verified` or `unresolved`. |
| `n_agree` | How many engines read the agreed value. |
| `votes` | Every candidate value with its count, e.g. `123512×3 \| 128512×1`. |
| `sources` | The engines that read the agreed value. |
| `dissent` | What the other engines read. `<missing>`: no reading for this cell. |
| `failed` | Names of the checks this value breaks; empty when it passes. |

```python
print(cells[cells.status == "unresolved"][["row", "col", "votes", "dissent"]])
```

```
    row  col votes                                            dissent
242  #3    0   9×1  camelot=<missing>|pdfplumber=<missing>|pdftote...
```

### Common arguments

| Argument | What it does |
| --- | --- |
| `methods=["pdfplumber", "pymupdf", "pdfium"]` | Engines to run. Default: the five text-layer engines. |
| `pages=[3, 4]` | Read only these pages (1-based). Result pages are numbered 1..n. |
| `min_agree=3` | Engines that must agree. Default: a strict majority, at least 3. |
| `jobs=4` | Worker processes: engines run at once and each reads its pages in up to 4 chunks (Chandra and GLM-OCR stay in this process). Same result. Default: 1. |
| `normalize=fn` | Rewrite each value before the vote; return `None` to drop it. |
| `parse=fn`, `key=[...]` | Your parser and the columns that identify a cell. |
| `checks=[...]` | Rules the verified values must satisfy. |
| `families={...}` | Engines that are not independent vote once. See [Engines](engines.md#families). |
| `return_readings=True` | Also return every engine's own reading and its position. |

With fewer engines than `min_agree`, `extract()` raises.

## Check the values

A check takes the verified cells and returns `True` where a row fails. `@check` names it. `total_check()` builds the common one: a total row must equal the sum of its parts.

```python
from functools import partial

import pandas as pd

from pdfexorcist import check, extract, parse_rows, total_check


def clean(value):
    return value.replace(",", "")


@check("no negative counts")
def non_negative(df):
    return pd.to_numeric(df.value, errors="coerce") < 0


cells = extract(
    "report.pdf",
    parse=partial(parse_rows, min_values=3),
    normalize=clean,
    checks=[
        non_negative,
        total_check(
            "label",
            "TOTAL ALL INDIA",
            ["TOTAL STATE(S)", "TOTAL UT(S)"],
            by=["page", "col"],
            where="col <= 2",
        ),
    ],
)
print(cells.status.value_counts().to_dict())
print(cells[cells.label == "TOTAL ALL INDIA"][["label", "col", "value"]].head(3))
```

```
{'verified': 234}
               label  col    value
228  TOTAL ALL INDIA    0  3225597
229  TOTAL ALL INDIA    1  4254356
230  TOTAL ALL INDIA    2  3663360
```

`min_values=3` skips titles and footnotes. `where="col <= 2"` limits the sum to the three count columns; the rates in columns 3 to 5 do not add up.

Checks never drop rows. A failing value is kept and named in `failed`, so `cells[cells.failed != ""]` lists them.

`total_check()` options:

| Argument | What it does |
| --- | --- |
| `op` | `"=="` (default), `">="` (the total may exceed its parts) or `"<="`. |
| `parts` | The rows that add up to the total. Default: every other row of the group. |
| `by` | Columns that identify one group, e.g. `["page", "col"]`. |
| `rel_tol`, `abs_tol` | Allowed relative or absolute gap, for rounded numbers. |
| `missing` | `"skip"` (default): a group missing a part is not judged. `"fail"`: it fails, so lost data cannot pass. |

### Checks that need more columns

`validate()` runs checks after the vote, once you have added the columns they need:

```python
from functools import partial

from pdfexorcist import extract, parse_rows, total_check, validate

cells = extract("report.pdf", parse=partial(parse_rows, min_values=3))

# a column the parser does not produce: the State name without its serial number
cells["state"] = cells.label.str.replace(r"^\d+\s+", "", regex=True)
cells = cells[~cells.state.isin(["TOTAL STATE(S)", "TOTAL UT(S)"])]

rule = total_check("state", "TOTAL ALL INDIA", by=["col"], where="col <= 2")
checked = validate(cells, [rule])
print((checked.failed != "").sum(), "rows fail")
```

```
0 rows fail
```

The States and UTs add up to the national total in each year.

## Write a parser

A parser receives each engine's pages as `(page_no, lines)` pairs. A line is a list of `(x, text)` cells. The parser yields one dict per value, with the key columns and `"value"`. It runs once per engine, and the vote compares cells with the same key.

This one keys each count by State and year:

```python
import re

from pdfexorcist import extract

YEARS = [2019, 2020, 2021]


def parse_states(pages):
    """Each State row: a serial number and name, then six numbers."""
    for page_no, lines in pages:
        for line in lines:
            texts = [text for _, text in line]
            label = " ".join(texts[:-6])
            if not re.match(r"\d+ ", label):
                continue
            state = label.split(" ", 1)[1].rstrip("*+@")  # drop footnote marks
            for year, value in zip(YEARS, texts[-6:-3]):
                yield {"page": page_no, "state": state, "year": year, "value": value}


cells = extract("report.pdf", parse=parse_states, key=["page", "state", "year"])
print(cells.status.value_counts().to_dict())
print(cells.pivot(index="state", columns="year", values="value").head(4))
```

```
{'verified': 108}
year                 2019    2020    2021
state
A&N Islands           564     482     386
Andhra Pradesh     119229  188997  179611
Arunachal Pradesh    2590    2244    2626
Assam              123512  111558  119883
```

Engines split a line differently. pdftotext and camelot give `"3 Assam"` as one cell, pdfplumber gives `"3"` and `"Assam"`. Taking the values from the end of the line and joining the rest makes the key the same for all of them. `.rstrip("*+@")` matters too: PDFium reads `Jammu & Kashmir` where the others read `Jammu & Kashmir*`, and without it those three cells get different keys and stay unresolved.

Two parsers ship with the package:

* `parse_rows` (default): a label, then values in reading order. Key: `page`, `row`, `col`.
* `parse_by_columns`: places each value in the nearest column by its x position. A value one engine missed then shifts nothing. Use it for OCR.

For a larger example, see [MCCD Table 4](examples/mccd-table4.md).

## Vote on your own readings

`vote()` is the vote alone. It takes one row per engine reading:

```python
import pandas as pd

from pdfexorcist import vote

readings = pd.DataFrame(
    [
        ("pdfplumber", 1, "Assam", 0, "123512"),
        ("pymupdf", 1, "Assam", 0, "123512"),
        ("pdfium", 1, "Assam", 0, "123512"),
        ("camelot", 1, "Assam", 0, "128512"),
        ("pdfplumber", 1, "Bihar", 0, "197935"),
        ("pymupdf", 1, "Bihar", 0, "197985"),
        ("pdfium", 1, "Bihar", 0, "197935"),
        ("camelot", 1, "Bihar", 0, "197985"),
    ],
    columns=["method", "page", "row", "col", "value"],
)
print(vote(readings)[["row", "value", "status", "votes"]])
```

```
     row   value      status                votes
0  Assam  123512    verified  123512×3 | 128512×1
1  Bihar          unresolved  197935×2 | 197985×2
```

Three of four is a strict majority. A 2-2 tie is not, so Bihar stays blank.

## Add an engine

`@register` adds an engine. It takes the path of a PDF and yields `(page_no, lines)`. `group_words` turns `(x0, x1, y_bottom, text, y_top)` word boxes into lines.

```python
import pdfplumber

from pdfexorcist import EXTRACTORS, extract, group_words, register


@register("plumber_tight", default=False)
def plumber_tight(pdf):
    with pdfplumber.open(pdf) as doc:
        for page_no, page in enumerate(doc.pages, start=1):
            words = page.extract_words(x_tolerance=1)
            yield (
                page_no,
                group_words([(w["x0"], w["x1"], w["bottom"], w["text"], w["top"]) for w in words]),
            )


print(sorted(EXTRACTORS))
cells = extract("report.pdf", methods=["pymupdf", "pdfium", "plumber_tight"])
print(cells.status.value_counts().to_dict())
```

```
['camelot', 'chandra', 'glmocr', 'ocrmac', 'paddleocr', 'pdfium', 'pdfplumber', 'pdftotext', 'plumber_tight', 'pymupdf', 'tabula', 'tesseract']
{'verified': 241, 'unresolved': 2}
```

With `extract(..., jobs=N)`, built-in engines read in worker processes; your own engines, and those registered with `in_process=True` (Chandra, GLM-OCR), read in the calling one.

`default=False` keeps it out of the default set; name it in `methods` to use it. This example only shows the interface: a second pdfplumber setup shares pdfplumber's misreads, so it is not an independent voter. A useful engine reads the page by different means.

The `x` units are the engine's own (points, character columns). Only the column order they give has to agree.

## Images and photos

`extract()` also takes an image. Only OCR engines can read one, so name them. `report.png` is `report.pdf` rendered at 200 dpi, as a stand-in for a screenshot:

```python
from pdfexorcist import extract, parse_by_columns

cells, readings = extract(
    "report.png",
    methods=["tesseract", "paddleocr", "glmocr"],
    parse=parse_by_columns,
    return_readings=True,
)
print(cells.status.value_counts().to_dict())
print(cells[cells.label == "Assam"][["col", "value", "votes"]])
```

```
{'verified': 262, 'unresolved': 25}
    col   value     votes
14    0       3       3×3
15    1  123512  123512×3
16    2  111558  111558×3
17    3  119883  119883×3
18    4   351.6   351.6×3
19    5   341.0   341.0×3
20    6    38.2    38.2×3
```

With only OCR engines, the default `min_agree` is a strict majority of at least 2.

## Where each value sits

`return_readings=True` returns `(cells, readings)`. `readings.cells` has every engine's own reading before the vote, with its `box` in PDF points (origin top-left), or `None` when the engine gives no position:

```python
r = readings.cells
print(r[(r.label == "Assam") & (r.col == 1)][["method", "value", "box"]])
```

```
        method   value                               box
15   tesseract  123512  (189.12, 191.28, 221.52, 198.48)
288  paddleocr  123512  (185.04, 186.48, 223.56, 200.88)
565     glmocr  123512                              None
```

The result `cells` is the same with or without `return_readings`.

## Choose pages

```python
from pdfexorcist import pages_matching, parse_pages

print(parse_pages("1-3, 7, 10-", n_pages=12))
print(pages_matching("mccd_2009.pdf", start=r"TABLE\s*4", match="Septicaemia"))
```

```
[1, 2, 3, 7, 10, 11, 12]
[1, 2]
```

`pages_matching` finds pages by their text: from the first page matching `start` up to (not including) the one matching `stop`, keeping those that match `match`. Pass the result to `extract(..., pages=...)`.
