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
| `pypdf` | text layer | `--engines` | all, extra `pypdf` | no |
| `pdfjs` (Mozilla pdf.js) | text layer | `--engines` | needs Node and `npm install -g pdfjs-dist` | yes |
| `tesseract` | pixels | `--ocr` | needs Tesseract | yes |
| `chandra` (Chandra OCR 2 model) | pixels | `--ocr` | CUDA or Apple GPU, extra `ocr` | no |
| `paddleocr` (PP-OCR) | pixels | `--ocr` | all, CPU, extra `paddle` | yes |
| `doctr` (docTR models on onnxruntime) | pixels | `--ocr` | all, CPU, extra `doctr` | yes |
| `indra` (Datalab's Indra OCR on onnxruntime) | pixels | `--ocr` | all, CPU, extra `indra` | yes |
| `ocrmac` (Apple Vision) | pixels | `--ocr` | macOS, extra `mac` | yes |
| `glmocr` (GLM-OCR model via MLX) | pixels | `--ocr` | Apple Silicon, extra `mlx` | no |
| `unlimitedocr` (Baidu Unlimited-OCR 2 model) | pixels | `--ocr` | CUDA or Apple GPU, `$PDFEXORCIST_UOCR_PYTHON` | no |

* default: runs on every `extract`.
* `--ocr`: added by `--ocr`, `ocr = true` in a recipe, or an image input.
* `--engines`: runs only when named.
* Positions: whether the engine says where each word sits. [show](show.md) borrows the other engines' boxes for those that do not.

`pdfexorcist engines` shows which are installed on your machine. An engine that is not installed, or crashes, is skipped with a warning.

`pdfjs` finds pdfjs-dist in the global npm root, or at `$PDFEXORCIST_PDFJS`. pypdf drops rotated text.

`unlimitedocr` runs its model in a separate Python, because the model's code needs transformers 4.52.
Set `$PDFEXORCIST_UOCR_PYTHON` to a Python with `torch`, `transformers==4.52.1`, `tokenizers==0.21.4`,
`huggingface-hub==0.36.0`, `addict`, `einops`, `easydict` and `pillow`. It reads each picture of a page at its own
resolution, or the whole page when the page has no picture.

`chandra`, `glmocr` and `unlimitedocr` cache each page's reading under `$PDFEXORCIST_CACHE` (default `~/.cache/pdfexorcist/<engine>/`), and a second run on the same file reads that cache.

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

`min_unopposed` (off by default) also accepts a value that this many engines read when none read anything else.
## Families

A family groups engines that share code or a source. A family votes once: its members first settle on their own majority value, and that value counts as one vote. `min_agree` then defaults to a majority of families, at least 2.

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

For the same reason, each OCR lab gets one vote. `indra` and `chandra` both come from Datalab. `--ocr` runs `indra` when both are installed. When you name both in `--engines`, they vote once, as the family `datalab`. Surya (also from Datalab) and PaddleOCR-VL (the PaddleOCR lab) are not included.

The Indra OCR model weights have a separate licence, a modified OpenRAIL-M. Read it on the [model page](https://huggingface.co/datalab-to/indra-ocr) before you use `indra` for commercial work.

## Chandra or Indra

`chandra` and `indra` both come from Datalab, so a run uses one of them.

| | `indra` | `chandra` |
| --- | --- | --- |
| Runs on | CPU; an NVIDIA GPU with `onnxruntime-gpu` | GPU (CUDA or Apple) |
| Download | 76 MB of ONNX models | the Chandra OCR 2 model |
| Positions | yes, a box for each line | no |

Each engine ran alone on the 16 BMC lake-level phone photos in `tests/fixtures/bmc`. The photos have 1,322 hand-checked cells.

| Engine | Right | Wrong | Not read |
| --- | --- | --- | --- |
| `chandra` | 1,277 | 1 | 44 |
| `indra` | 1,026 | 1 | 295 |
| `ocrmac` | 882 | 2 | 438 |
| `tesseract` | 10 | 2 | 1,003 |

Tesseract read nothing on 4 photos. Its row shows the other 12 photos.

On an Apple M4 Max, `indra` read each photo in about 0.5 s. This time includes the model load. On the faded 1995 ADSI scan (`tests/fixtures/adsi/1995_t2A_p6.pdf`), `indra` misread the state names. The ADSI parser placed none of its rows.

`indra` uses CUDA when `onnxruntime-gpu` is installed in place of `onnxruntime` (`pip uninstall onnxruntime && pip install onnxruntime-gpu`). On a Mac, `indra` stays on the CPU. Through CoreML, it took 0.56 s for each photo. On the CPU, it took 0.20 s. Both read the same cells.

* Use `indra` when you have no GPU, when you read many pages, or when `show` needs boxes.
* Use `chandra` for phone photos. Datalab also suggests it for handwriting and faded scans. When both engines are installed, name the engines to use `chandra`: `pdfexorcist extract photo.jpg --engines chandra,ocrmac,paddleocr`.

## When to use --ocr

`pdfexorcist inspect` prints the command to run.

| The file | Run |
| --- | --- |
| A PDF with a text layer | `pdfexorcist extract report.pdf`. The text engines read the exact characters. |
| A scan with no text layer | `pdfexorcist extract scan.pdf --ocr` |
| A scan with an ocrmypdf text layer | `pdfexorcist extract scan.pdf --ocr`, so more than one reading votes. |
| A photo or screenshot (.png, .jpg) | `pdfexorcist extract photo.jpg` (OCR is on for images) |

On a text PDF, `--ocr` adds slower engines that read the same characters from the pixels.

For OCR, place values by position: `type = "columns"` in a recipe, or `parse=parse_by_columns` in Python, so a value one engine missed leaves the others in their columns.

A page that is a single image is read at its own resolution. Tesseract is a weak voter on photos: on a skewed, grainy phone photo it ran the table's columns together.
