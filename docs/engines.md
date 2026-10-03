---
description: "The engines pdfexorcist runs, what each reads, how the vote counts them, and when to add OCR."
---

# Engines

An engine reads a page and returns lines of text with their x positions. pdfexorcist runs several, parses each one's lines the same way, and keeps a value only when enough of them read it identically.

## The engines

| Engine | Reads | Used | Platform | Positions |
| --- | --- | --- | --- | --- |
| `pdftotext` (poppler) | text layer | default | needs poppler | no |
| `pdfplumber` (pdfminer) | text layer | default | all | yes |
| `pymupdf` (MuPDF) | text layer | default | all | yes |
| `pdfium` (PDFium, Chrome's engine) | text layer | default | all | yes |
| `camelot` (table finder) | text layer | default | all | yes |
| `tabula` (tabula-java) | text layer | `--engines` | needs Java, extra `tabula` | |
| `tesseract` | pixels | `--ocr` | needs Tesseract | yes |
| `chandra` (Chandra OCR 2 model) | pixels | `--ocr` | CUDA or Apple GPU, extra `ocr` | no |
| `paddleocr` (PP-OCR) | pixels | `--ocr` | all, CPU, extra `paddle` | yes |
| `ocrmac` (Apple Vision) | pixels | `--ocr` | macOS, extra `mac` | yes |
| `glmocr` (GLM-OCR model via MLX) | pixels | `--ocr` | Apple Silicon, extra `mlx` | no |

* default: runs on every `extract`.
* `--ocr`: added by `--ocr`, `ocr = true` in a recipe, or an image input.
* `--engines`: runs only when named.
* Positions: whether the engine says where each word sits. [show](show.md) borrows the other engines' boxes for those that do not.

`pdfexorcist engines` shows which are installed on your machine. An engine that is not installed, or crashes, is skipped with a warning.

`chandra` and `glmocr` cache each page's reading under `$PDFEXORCIST_CACHE` (default `~/.cache/pdfexorcist/<engine>/`), so a second run on the same file is fast.

## The vote

For each cell, every engine's reading is a vote.

* A value is `verified` when at least `min_agree` engines read it and no other value ties it.
* `min_agree` defaults to a strict majority of the engines, and at least 3: 3 of 4, 3 of 5, 4 of 6. With only OCR engines, at least 2.
* An engine that reads two different values for one cell loses its vote there.
* Anything else is `unresolved`: left blank, with every reading kept in `votes` and `dissent`.

```bash
pdfexorcist extract report.pdf -k 4                  # 4 engines must agree
pdfexorcist extract report.pdf -e pdfplumber,pymupdf,pdfium,camelot
```

`min_agree` does not drop when an engine is missing. With fewer engines than `min_agree`, `extract` stops with exit code 1.

`min_unopposed` (off by default) also accepts a value that this many engines read when none read anything else. It lowers the bar; leave it off unless you mean to.

## Families

Engines that share code or a source share mistakes. A family votes once: its members first settle on their own majority value, and that value counts as one vote. `min_agree` then defaults to a majority of families, at least 2.

camelot reads the text layer through pdfminer, as pdfplumber does, so you can put them in one family:

```python
from pdfexorcist import extract

cells = extract(
    "report.pdf",
    families={"pdfminer": ["pdfplumber", "camelot"]},
)
print(cells.status.value_counts().to_dict())
```

```
{'verified': 242, 'unresolved': 1}
```

Five engines now cast four votes, and three must agree.

pdfexorcist detects a PDF whose text layer ocrmypdf made. Its text engines all read one Tesseract reading, so they become one family, and `extract` asks for independent engines:

```bash
pdfexorcist extract scan.pdf
```

```
╭─ Error ──────────────────────────────────────────────────────────────────────────────────────────╮
│ This PDF's text layer was made by OCR (ocrmypdf), so the text engines all repeat that one        │
│ reading and count as a single vote.                                                              │
│                                                                                                  │
│ How to fix: Add independent OCR engines: pdfexorcist extract scan.pdf --ocr                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────╯
```

For the same reason, the OCR engines come from different labs. Surya (the Chandra lab) and PaddleOCR-VL (the PaddleOCR lab) are not included.

## When to use --ocr

`pdfexorcist inspect` tells you.

| The file | Run |
| --- | --- |
| A PDF with a text layer | `pdfexorcist extract report.pdf`. The text engines read the exact characters. |
| A scan with no text layer | `pdfexorcist extract scan.pdf --ocr` |
| A scan with an ocrmypdf text layer | `pdfexorcist extract scan.pdf --ocr`, so more than one reading votes. |
| A photo or screenshot (.png, .jpg) | `pdfexorcist extract photo.jpg` (OCR is on for images) |

On a text PDF, `--ocr` adds slower engines that can only misread what the text layer already holds exactly.

For OCR, place values by position rather than by order: `type = "columns"` in a recipe, or `parse=parse_by_columns` in Python. A value one engine missed then shifts nothing.

A page that is a single image is read at its own resolution. Tesseract is a weak voter on photos: on a skewed, grainy phone photo it ran the table's columns together.
