---
description: Every public pdfexorcist function, grouped by topic.
---

# Reference

Every public function, grouped by what it is for. Each entry links to its full signature and description. All are importable from `pdfexorcist`.

## Extracting

| | |
| --- | --- |
| {py:func}`extract() <pdfexorcist.extract>` | Read a PDF or image with several engines, parse, vote and check |
| {py:func}`vote() <pdfexorcist.vote.vote>` | The vote alone, on one row per engine reading |

## Parsers

| | |
| --- | --- |
| {py:func}`parse_rows() <pdfexorcist.parse_rows>` | The default parser: a label, then values in reading order |
| {py:func}`parse_by_columns() <pdfexorcist.parse_by_columns>` | Places each value in the nearest column by its x position |
| {py:func}`group_words() <pdfexorcist.group_words>` | Word boxes to lines of `(x, text)` cells |
| {py:data}`KEY <pdfexorcist.KEY>` | The default parser's key: `["page", "row", "col"]` |

## Checks

| | |
| --- | --- |
| {py:func}`check() <pdfexorcist.check>` | Name a check |
| {py:func}`total_check() <pdfexorcist.total_check>` | A total must equal, or bound, the sum of its parts |
| {py:func}`validate() <pdfexorcist.validate>` | Run checks on a DataFrame and fill its `failed` column |

## Engines and pages

| | |
| --- | --- |
| {py:func}`register() <pdfexorcist.register>` | Add an engine |
| {py:data}`EXTRACTORS <pdfexorcist.EXTRACTORS>` | Every registered engine, by name |
| {py:func}`pages_matching() <pdfexorcist.pages_matching>` | Pages chosen by the text they contain |
| {py:func}`parse_pages() <pdfexorcist.parse_pages>` | `"1-3, 7, 10-"` to a list of page numbers |
| {py:func}`fit_page_boxes() <pdfexorcist.fit_page_boxes>` | A copy of a PDF whose page boxes cover all their text |

```{toctree}
:hidden:

extract
parsers
checks
engines
```
