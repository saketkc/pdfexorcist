# Changelog

All notable changes to pdfexorcist are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[PEP 440](https://peps.python.org/pep-0440/) (`1.2.0`, `1.2.0rc1`).

Add each change under [Unreleased] as you make it. The Prepare release
workflow moves those entries into a dated section.

## [Unreleased]

### Added

- `nacnet` recipe: NCDC NAC-NET antimicrobial consumption reports, chart values checked against bars.
- `unlimitedocr` engine: Baidu Unlimited-OCR 2, run under `$PDFEXORCIST_UOCR_PYTHON`.

### Fixed

- Sideways pages: digits decide the text direction (`_upright`).
- `charts`: dashed averages, leader lines, short sideways labels and gridless ticks read right.

- Recipes that read tables through their drawn cells and check their totals:
  - `tb_india_district`: TB India annual reports 2010-2019, notification and case finding by
    district.
  - `nhp_multi_year`: CBHI National Health Profile State/UT tables of malaria, dengue,
    chikungunya, kala-azar, AES, JE and H1N1 by year.
  - `insp_sitrep`: DR Congo INSP Ebola situation reports, cases and deaths by province and
    health zone.
  - `cdsco_nsq`: CDSCO monthly lists of drugs Not of Standard Quality, one row per batch.
  - `karnataka_dengue`: Karnataka daily dengue and chikungunya report by district (text PDFs).
    `karnataka_dengue/scan` reads the scanned ones with OCR.
  - `haryana_influenza`: Haryana daily influenza A (H1N1, H3N2) bulletin, cases and deaths by
    district.
  - `ncvbdc_malaria_district`: NCVBDC district-wise malaria annual reports 2010-2024, in their
    seven column layouts.
  - `mumbai_praja_health`: Praja Foundation Mumbai health white papers (2012 to 2024), cases
    in BMC dispensaries by ward and year.
  - `delhi_praja_health`: Praja Foundation State of Health in Delhi reports (2017 to 2024),
    cases by MCD zone, and cases and deaths in MCD and state facilities.
  - `rajasthan_seasonal`: Rajasthan seasonal disease status (scrub typhus, H1N1,
    leptospirosis and brucellosis), cumulative positives and deaths by district.
    `rajasthan_seasonal/scan` reads the scanned dengue, malaria and chikungunya status with OCR.
  - `kerala_idsp_daily`: Kerala DHS communicable diseases daily report (2016 on), counts by
    district, the State's day, month and year counts, and the dengue list by district; the TOT
    row is checked against the State's.
  - `tb_report`: India TB Report State/UT annexures, each % checked against its counts.
  - `ncvbdc_states`: NCVBDC State/UT tables for dengue, chikungunya and malaria.
  - `rhs`: Rural Health Statistics staff tables by State/UT.
- Recipes that read text rows:
  - `kerala_dhs`: Kerala DHS cases and deaths by disease and district.
  - `cbhi_nhp`: CBHI National Health Profile cases and deaths by State/UT and sex.
  - `naco_hiv`: NACO Sankalak and India HIV Estimates by State/UT; "est (lower-upper)" gives
    three cells.
  - `nha`: National Health Accounts Estimates, with ratio and share checks.
  - `meghalaya_idsp`: Meghalaya IDSP monthly bulletin, surveillance totals, outbreaks by
    district and influenza tests.
  - `bihar_idsp_weekly`: State Health Society Bihar weekly IDSP bulletin (2013 to 2018), cases
    for the week and cumulative, this year and last.
  - `bihar_idsp_monthly`: State Health Society Bihar monthly IDSP report (2012 to 2018), the
    month's outbreaks, cases and deaths by disease and district.
  - `bihar_idsp_sheets`: the district sheets annexed to that report, cases by district and
    month.
  - `gujarat_nvbdcp`: Gujarat NVBDCP monthly decks (2018-2019), malaria SPR, SFR, MBER and
    MPI by district and month. `gujarat_nvbdcp/highlights` reads the one-page highlights
    (2020 onwards): blood examination rate, change in cases and district shares.
- `tests/fixtures/download.py` downloads each fixture's source PDF, from the Internet Archive
  when the site fails.

### Fixed

- Scanned pages printed sideways or upside down are turned upright before any engine reads
  them, by tesseract's orientation detection. Off with `PDFEXORCIST_TURN_SCANS=0`.
- Scanned pages 0.3 to 2 degrees askew are levelled before OCR, so a row keeps its own values.
  Off with `PDFEXORCIST_DESKEW=0`.
- `karnataka_dengue/scan` reads the Adobe Scans of July-November 2025.
- `oxr` crops a page's pictures in the page as turned by /Rotate, at the picture's own dpi.
- `grid` finds tables whose rules are drawn as dots.
- `pymupdf` word boxes use pdfplumber's page coordinates, so they fall in `grid` cells on pages
  whose CropBox or MediaBox is offset.
- Turning two or more sideways pages upright raised "source object number out of range".
- Text printed sideways (headings turned a quarter) is kept and read as whole words by every
  text engine; a sideways word joins only the line through its middle.
- `amrsn`: headings printed on staggered lines name every column; "Table- 7.19 A:" is a caption.
- `amrsn` pictures: an "R/n" over "(%)" table with wrapped "%Range" lines is read as one; data-bar
  marks ("SHV O O", "116ął") are not part of a row label or value.
- A % with its count joined as one token (`97.1(68/70)`) is a value.
- `amrsn` pictures: a group printed once beside its rows ("Major errors (n)") is part of their
  row key, and the output is indexed by row key, so repeated labels do not clash; "97.1 (68/70)"
  is one cell; a picture's own caption under the report's keeps the report's number; "Table 4.11
  depicts ..." in the text is not a caption.
- `amrsn` pictures: "(61.4%)" under a count is its (%) (2018 Table 6.1); a table model's
  "4467/7274/(61.4%)" is the count and its (%).
- `karnataka_idsp` reads the weekly reports from week 44 of 2023 on.

## [0.4.0] - 2026-10-24

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

[Unreleased]: https://github.com/saketkc/pdfexorcist/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/saketkc/pdfexorcist/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/saketkc/pdfexorcist/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/saketkc/pdfexorcist/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/saketkc/pdfexorcist/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/saketkc/pdfexorcist/releases/tag/v0.1.1
