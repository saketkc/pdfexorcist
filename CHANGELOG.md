# Changelog

All notable changes to pdfexorcist are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[PEP 440](https://peps.python.org/pep-0440/) (`1.2.0`, `1.2.0rc1`).

Add each change under [Unreleased] as you make it. The Prepare release
workflow moves those entries into a dated section.

## [Unreleased]

### Added

- MMIS example (`examples/mmis_malaria/`): NCVBDC's monthly malaria report

### Fixed

- `is_value` accepts Excel's scientific display of a too-wide number (`2E+05`)

## [0.1.1 - 4 Oct 2026]

### Added

Initial release:
- pdfexorcist also runs in the browser (`web/`) with pyodide! at <https://saketkc.github.io/pdfexorcist/>:
- pdfexorcist is a new package for extracting tables from pdfs (both text and scanned ones) 

