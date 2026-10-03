# Changelog

All notable changes to pdfexorcist are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[PEP 440](https://peps.python.org/pep-0440/) (`1.2.0`, `1.2.0rc1`).

Add each change under [Unreleased] as you make it. The Prepare release
workflow moves those entries into a dated section.

## [Unreleased]

### Added

- A link works wherever a file name does: `pdfexorcist extract https://...`
  saves the file in the current folder, and `extract(url)` in Python saves it
  under `$PDFEXORCIST_CACHE`. The download follows Drive, Dropbox and GitHub
  share links, download scripts, and pages that link to, embed or redirect to
  the file.
- A tweet link reads the tweet's photo (`.../photo/N` for another one).
- `--jobs N` (`-j N`) and `extract(jobs=N)` use up to N worker processes:
  engines run at once, and each splits its pages into up to N chunks, so one
  engine on a long PDF is faster too. The result is the same as `-j 1`. Worker
  processes are reused across calls; if they cannot start, the engines read in
  the calling process. `register(..., in_process=True)` keeps an engine there.
- A link that names no file is saved under its server's file name (or its host
  and path) and the time it was downloaded, and is fetched again each time.
- Examples with recipes, tests and docs pages: Maharashtra's Pravah daily dam
  report, the NEET (UG) 2024 press release (nine tables, one recipe) and a
  scanned NEET toppers list (OCR).
- Each example docs page shows what its recipe reads, drawn by
  `pdfexorcist show`; `.github/scripts/doc_images.py` renders the images.
- A server whose TLS chain lacks its intermediate certificate is verified with
  the intermediate its certificate names (AIA), as browsers do; verification
  stays on.
- Extras named after their engines (`chandra`, `paddleocr`, `ocrmac`,
  `glmocr`, `tabula`) and `all` for every engine; `ocr`, `paddle`, `mac` and
  `mlx` still work.
- Extraction by majority vote: several independent engines read each page, and
  a cell is kept only when a strict majority of them (at least 3) read it
  identically. Anything else is reported as unresolved with every engine's
  reading, never guessed.
- Five default text-layer engines (pdftotext, pdfplumber, PyMuPDF, PDFium,
  camelot) and opt-in engines: tabula, Tesseract, Chandra OCR 2, PaddleOCR,
  Apple Vision (ocrmac) and GLM-OCR. An engine that is not installed or crashes
  is skipped with a warning, and the quorum does not drop with it.
- Images (photos, screenshots, scans) as input, read by the OCR engines; a
  photographed page is levelled before it is read.
- Engine families: engines sharing one OCR text layer (an ocrmypdf'd scan)
  vote once; detected automatically for ocrmypdf output.
- Plug-in points: `@register` for engines, your own parser (`parse_rows`,
  `parse_by_columns`, or a function), and validators (`@check`,
  `total_check(..., missing="fail")`) that mark failing values and keep
  them.
- `extract(..., return_readings=True)` returns every engine's own reading with
  its position on the page.
- Command line: `pdfexorcist extract` (CSV, Excel, Parquet or JSON, a review
  file for unresolved cells, `--json` summaries, exit codes for scripts),
  `inspect`, `engines`, `show` and `compare` (a self-contained HTML view of one
  page with every voted cell boxed, plus an optional PNG).
- Recipes: a TOML file holding the pages, engines, value cleaning, parser,
  totals that must add up, post-vote step and output for one kind of table;
  `pdfexorcist recipe new | show | check`, and three example recipes.
- Type information for the package (`py.typed`).
- Example gallery (`examples/`, docs "Examples"): recipes for MCCD Tables 2, 4,
  5 and 9, SRS life tables, IIPS district and MoHFW state projections, CRS
  State tables, NFHS-6 state and district fact sheets, Crime in India and a
  photographed lake report; each runs in the test suite on real pages.
- Regression tests on real pages for MCCD Tables 2, 5 and 9, CRS State tables
  and the NFHS-6 state and district fact sheets.
- `extract(..., fit_boxes=False)` and recipe `[pages] fit_boxes = false` keep
  each page's own box, for reports that carry the facing page's text off-page.
- `nc` ("no cases") is read as a placeholder value.
- NFHS-5 state and district fact-sheet tests and examples, with a verification
  note against an independent extraction.

### Changed

- The docs are built with Sphinx and the Furo theme (Albert Sans, light and
  dark), and deploy to <https://saketlab.github.io/pdfexorcist/> from `main`.
- The package is MIT-licensed, with project URLs on PyPI.
- Each example parser exists once, in `examples/`; the tests import it from
  there. Recipes that share a parser share a folder: `examples/nfhs5/`,
  `examples/nfhs6/` and `examples/mccd/` (`state.toml`, `district.toml`,
  `table4.toml` ...).
- The dev dependency group adds pyarrow and openpyxl, so a local
  `--group dev` install runs the Parquet and xlsx output tests; without
  pyarrow the Parquet test is skipped.
- Chandra and GLM-OCR cache each page by the image they read, not by the PDF's
  bytes, so a read is reused across `--pages` cuts, `show` and the same photo
  in another file. Caches from earlier versions are still used.
- `pdfexorcist --help` starts faster: pandas is loaded only when a command
  needs it.
- Apple Vision (`ocrmac`) reads a document in one worker process instead of
  one per page.
- `--debug` shows third-party logs (PaddleX, camelot); without it the CLI
  quiets them. The library no longer changes their log levels.

### Fixed

- The BMC lake parser voided a row when a scan speck was read next to a number
  ("·141.90", a lone "•"), and lost the date when OCR misspelt the title
  ("Levols"). The lake-photo recipe also sets `min_unopposed = 2`.
- A scan on a page with /Rotate was taken for a blank page by `inspect`, and
  OCR rendered it at the wrong resolution.
- The generic parsers did not take raised-dot decimals (`65·3`) for values, so
  the `raised_dots` setting never reached them; they now do.
- `total_check` failed sums of decimals that add up (65.3 + -4.0 = 61.3) on
  binary rounding noise; it now allows a relative 1e-9.
- The CLI no longer shows the progress bars and advice that transformers and
  Hugging Face Hub print while Chandra and GLM-OCR load (`--debug` shows them).
- pdfplumber and PDFium read text drawn outside the page box, which poppler
  does not; now they read only inside it too (the box still grows to cover
  outside text unless `fit_boxes=False`).
- Apple Vision: when its "accurate" recognizer returns nothing for every image,
  it switches to the "fast" recognizer for the rest of that document.
- Chandra's model loads once per process, like GLM-OCR's and PaddleOCR's, not
  once per `extract()` call.
- `fit_page_boxes` set page boxes in the wrong coordinate space: text just
  above a page's top crashed it ("CropBox not in MediaBox"), and a box grown
  for text below the page grew upward instead. Boxes are now converted from
  page space to PDF space.
- `vote()` crashed when an extra column was empty in every reading of a cell.
- Apple Vision (`ocrmac`) read nothing once Chandra had run on the Mac GPU in
  the same process; pages are now read in a subprocess, retried when Vision
  returns nothing while the GPU is busy.
- `--pages` and grown page boxes wrote PDFs with a new random ID on every run,
  so the Chandra and GLM-OCR caches (keyed by file hash) never hit.
- PaddleOCR's model-loading log lines no longer interrupt the CLI's progress.
- Windows: pdftotext output is decoded as UTF-8, and PDFs opened for page
  cutting and box growing are closed so temporary files can be removed.
- Deskewing works with OpenCV 5 (`HoughLinesP` changed its return shape).
- `show` and `recipe new` give `extract`'s plain error for a broken or
  password-protected PDF.
- `recipe new` offers a number clean-up exactly when it would change a value
  on the sample page (footnote marks after a bracket were missed).

