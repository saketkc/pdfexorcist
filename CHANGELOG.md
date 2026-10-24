# Changelog

All notable changes to pdfexorcist are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[PEP 440](https://peps.python.org/pep-0440/) (`1.2.0`, `1.2.0rc1`).

Add each change under [Unreleased] as you make it. The Prepare release
workflow moves those entries into a dated section.

## [Unreleased]

### Added

- Web results show the CLI command that gives the same result.
- `[charts] require_line`: a chart-picture value with no line to check it against fails.
- Add `amrsn` recipe
- Opt-in OCR engine `oxr` (SoMark OXR-1.0 through MLX, Apple Silicon; extra `glmocr`). 

### Fixed

- `ocrmac`: after an empty accurate reading, each later page still gets one accurate try.
- `recipe suggest`: a recipe fits when its checks fail on 2% of cells or fewer.
  On a text PDF, recipes that read only by OCR come after the text recipes.
- `recipe suggest` does not run a trial extract for a `[charts]` recipe.
  `ncvbdc_charts` checks pass when no chart was read.
- A space stays when the next letter only overhangs it. PDFium read "Enterococcus faecalis"
  as one word.
- A zero-width space now ends a word in a pdfium

## [0.3.0] - 2026-10-22

### Added

- `pdfexorcist charts FILE` can now read line chartsa; charts pasted as pictures are read by the OCR engines
- `charts --recipe`: a recipe's `[charts]` section (`kind`, `title`, `categories`, `series`, `names`, `crop`, `cells` and more), its `[engines]` and its `[[checks]]` set how charts are read
- `[charts] cells = "file.py:cells"` tells where the values are printed in a chart picture (bar charts, values without boxes); pdfexorcist still reads and votes on each value
- Example recipe `ncvbdc_charts`: NCVBDC's Monthly Malaria Situation charts in pictures, with TPR and PF checks
- Web: "What to read: Line charts" reads the drawn charts of a PDF, with a demo of NCVBDC's August 2026 Category III report
- Opt-in OCR engine `indra` (Datalab's Indra OCR on onnxruntime, CPU; extra `indra`, also in `.[all]`); the model weights have a separate licence; `indra` runs on an NVIDIA GPU when `onnxruntime-gpu` is installed

## [0.2.0] - 2026-10-19

### Added

- The wheel ships the example recipes; `--recipe cpcb_aqi` finds one by name
- `recipe suggest FILE` ranks the shipped recipes for a PDF, a photo or a scan by words, layout and a trial run; `--jobs N` runs the trials in parallel
- `extract(cleaned=True)` skips the cleaning steps for a PDF that `_clean.clean_pdf` already cleaned
- Examples, also on the web: the CPCB daily AQI bulletin (`cpcb_aqi`), the IDSP and Karnataka IDSP weekly reports (`idsp_outbreaks`, `karnataka_idsp`), the IMI Coverage Evaluation Survey 2018 (`imi_ces`), the CWC weekly reservoir bulletin (`cwc_reservoirs`), and CRS State Table 6 and District Tables 7-10
- Examples for NCRB Prison Statistics India (`prison_stats`), the SRS Statistical Report (`srs_statistical_report`), the SRS maternal mortality bulletin and Cause of Death report (`srs_maternal_mortality`), MoRTH Road Accidents in India (`road_accidents`) and the CBHI National Health Profile's malaria table (`nhp_malaria`)
- Web: recipes go by short name, as `--recipe` takes them; an example's recipe runs on your own PDF; you choose the engines that read an upload; each example has its own URL
- `placement="both"` (`parse_by_columns`, recipe `[parser]`): a value counts only where its order and x agree; otherwise the cell is unresolved
- `pages.find(pdf, pattern)` and `extract --pages-matching REGEX`; pages without text are matched by OCR of their top strip
- Type3 fonts without a Unicode map are decoded by tesseract; `extract(decode_fonts=False)` turns it off
- Built-in check `lossy value` fails `2E+05`, `#####` and `#REF!`

### Changed

- The example recipes moved from `examples/` to `pdfexorcist/recipes/`, inside the package
- The BMC lake-level photo recipe is `mybmc_lakes`, named "MyBMC lakes" (was `lake_photo`)
- A link to a deleted or mistyped tweet reports that X has no such tweet
- Words printed flush against each other join without a space (subscripts: `PM2.5`)
- camelot joins a wrapped cell's lines with one space, and lays out each page once for all its flavors
- `extract` raises `vote.TooFewReadings`, a `RuntimeError`, when too few engines read anything
- Rules drawn as many short pieces are redrawn whole before the engines read the page
- Tests run one worker per core (`pytest -n auto`); the Pyodide suite runs in 8 CI shards

### Fixed

- pymupdf and pdfium drop spaces drawn over letters, so letter-spaced words stay whole ("Bombay d u c k")
- Invisible text (render mode 3, zero opacity, white on a light fill) is dropped ("Z.Eggs" in IFCT 2017)
- A value with its uncertainty (`9.20±0.40`, `12+/-3`) is one value; values in narrow columns stay in separate cells
- The `pypdf` extra is pinned to 6.20.0, the version the web build ships
- Slanted text across a table ("Not Available") is dropped so it cannot chain rows
- Fake bold (text drawn 3-4 times) is read once by pdfplumber, pymupdf, pdfium, camelot and pdftotext
- pdftotext splits narrow-column values joined by one space
- PDFium reads Type3 fonts with oversized glyph boxes
- A cell every engine read two values for is output as unresolved
- Sideways tables on upright pages (no `/Rotate`) are turned upright

## [0.1.2] - 2026-10-11

### Added

- MMIS example (`examples/mmis_malaria/`): NCVBDC's monthly malaria report
- Opt-in engines `pypdf` (extra `pypdf`), `pdfjs` (Mozilla pdf.js through Node) and `doctr` (docTR models on onnxruntime, extra `doctr`)
- camelot tries its network, hybrid and ml flavors too; ml needs extra `camelot-ml`
- The web version runs `pypdf` and `pdfjs`

### Changed

- camelot needs camelot-py 2 or later
- camelot drops tables nested in a larger one, so network and hybrid do not count a row twice

### Fixed

- `is_value` accepts Excel's scientific display of a too-wide number (`2E+05`)
- `--jobs` frees each engine's pages once parsed

## [0.1.1] - 2026-10-04

### Added

Initial release:
- pdfexorcist also runs in the browser (`web/`) with pyodide at <https://pdfexorcist.in/>
- pdfexorcist is a new package for extracting tables from pdfs (text and scanned)

[Unreleased]: https://github.com/saketkc/pdfexorcist/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/saketkc/pdfexorcist/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/saketkc/pdfexorcist/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/saketkc/pdfexorcist/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/saketkc/pdfexorcist/releases/tag/v0.1.1
