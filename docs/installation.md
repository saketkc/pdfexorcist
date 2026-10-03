---
description: "Install pdfexorcist with pip or uv, add OCR engines with extras, and install poppler, Tesseract or Java where an engine needs them."
---

# Installation

## Prerequisites

The package requires Python 3.10 or newer.

## Install

```bash
pip install pdfexorcist
```

With [uv](https://docs.astral.sh/uv/), as a command-line tool or as a project dependency:

```bash
uv tool install pdfexorcist
uv add pdfexorcist
```

This installs four of the five default engines: pdfplumber, PyMuPDF, PDFium and camelot. The fifth, `pdftotext`, comes from poppler (see [System tools](#system-tools)).

## Check what is installed

```bash
pdfexorcist engines
```

```
┏━━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Engine     ┃ Installed ┃ Used      ┃ Reads        ┃ What it is                         ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ pdftotext  │ yes       │ default   │ text layer   │ poppler's pdftotext                │
│ pdfplumber │ yes       │ default   │ text layer   │ pdfminer word boxes                │
│ pymupdf    │ yes       │ default   │ text layer   │ MuPDF word boxes                   │
│ camelot    │ yes       │ default   │ text layer   │ camelot table finder               │
│ pdfium     │ yes       │ default   │ text layer   │ PDFium, Chrome's PDF engine        │
│ tabula     │ no        │ --engines │ text layer   │ tabula-java (needs Java)           │
│ tesseract  │ yes       │ --ocr     │ pixels (OCR) │ Tesseract OCR, CPU                 │
...
To install the missing engines (copy and paste):
  tabula: pip install "pdfexorcist[tabula]"

5 default engines ready: text PDFs need at least 3. 5 OCR engines ready: scans and photos
need at least 2.
```

The last lines print the exact command for each missing engine on your system. `pdfexorcist doctor` is the same command.

## Optional engines

Each extra is named after the engine it adds; `all` adds every engine. See
[Engines](engines.md) for what each one reads.

| Extra | Engine | Platform |
| --- | --- | --- |
| `chandra` | Chandra OCR 2 model | GPU: CUDA or Apple Silicon |
| `paddleocr` | PP-OCR | Linux, macOS, Windows; CPU |
| `ocrmac` | Apple Vision | macOS |
| `glmocr` | GLM-OCR model via MLX | Apple Silicon Macs |
| `tabula` | tabula-java | needs Java |

```bash
pip install "pdfexorcist[all]"
uv tool install "pdfexorcist[paddleocr,ocrmac]"
```

The names `ocr`, `paddle`, `mac` and `mlx` also work.

`chandra`, `glmocr` and `paddleocr` download their models on first use.

## System tools

Three engines run a program that pip cannot install.

| Engine | Program | macOS | Debian, Ubuntu | Windows |
| --- | --- | --- | --- | --- |
| `pdftotext` | poppler | `brew install poppler` | `sudo apt install poppler-utils` | `conda install -c conda-forge poppler` |
| `tesseract` | Tesseract | `brew install tesseract` | `sudo apt install tesseract-ocr` | `winget install UB-Mannheim.TesseractOCR` |
| `tabula` | Java | `brew install openjdk` | `sudo apt install default-jre` | `winget install Microsoft.OpenJDK.21` |

An engine whose program is missing is skipped with a warning. Without `pdftotext`, four default engines remain, and three of them must still agree.

## PaddleOCR and OpenCV

PaddleOCR needs `opencv-contrib-python` as the only OpenCV wheel in the environment. camelot and mlx-vlm pull in `opencv-python` or `opencv-python-headless`. The wheels share one `cv2` folder, and PaddleOCR then crashes with a segmentation fault. After installing, keep only one:

```bash
pip uninstall -y opencv-python opencv-python-headless
pip install --force-reinstall --no-deps opencv-contrib-python==4.10.0.84
```

## From source

```bash
git clone https://github.com/saketlab/pdfexorcist
cd pdfexorcist
pip install -e ".[paddleocr]"
```
