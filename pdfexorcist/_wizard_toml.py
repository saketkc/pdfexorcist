"""Render wizard answers as TOML."""

import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from typing import Any

from . import recipe as recipes
from ._ui import (
    CliError,
)

CLEAN = {
    "commas": ("remove_commas", '"1,020" -> "1020"'),
    "footnotes": ("remove_footnote_marks", '"490*" -> "490"'),
    "raised-dots": ("raised_dots", '"65·3" -> "65.3"'),
    "minus": ("minus_signs", '"−4" -> "-4"'),
}


@dataclass
class Answers:
    name: str = ""
    sample: str = ""
    select: str | None = None
    match: str | None = None
    ocr: bool = False
    engines: list[str] | None = None
    min_agree: int | None = None
    parser: str = "rows"
    min_values: int = 2
    clean: dict[str, bool] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)


def parse_total(text: str) -> dict[str, Any]:
    """Convert a total-rule prompt into a checks table."""
    m = re.match(r"^\s*([^:]+?)\s*:\s*(.+?)(?:\s+per\s+([\w\s,]+))?\s*$", text)
    if not m:
        raise CliError(
            f'--total {text!r} should be "COLUMN: RULE".',
            'Examples: --total "label: All India = rest" (a total row), '
            '--total "col: 0 = 1 + 2" (a total column).',
        )
    column, rule, per = m.group(1), m.group(2), m.group(3)
    try:
        recipes.parse_rule(rule)
    except ValueError as e:
        raise CliError(f"--total {text!r}: {e}.") from None
    by = (
        [c.strip() for c in per.split(",") if c.strip()]
        if per
        else (["page", "row"] if column == "col" else ["page", "col"])
    )
    return {"column": column, "rule": rule, "by": by}


def _q(text: str) -> str:
    """Quote TOML strings without escaping regex backslashes."""
    if "'" not in text and "\n" not in text and not re.search(r"[\x00-\x1f]", text):
        return f"'{text}'"
    return json.dumps(text, ensure_ascii=False)


def _s(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


def render(a: Answers, file_name: str) -> str:
    """Render a recipe as commented TOML."""
    lines = [
        f"# pdfexorcist recipe: {a.name}",
        f"# Made with `pdfexorcist recipe new` on {_dt.date.today().isoformat()}. "
        "Edit freely, then",
        f"#   check it:  pdfexorcist recipe check {file_name}",
        f"#   run it:    pdfexorcist extract YOUR.pdf --recipe {file_name}",
        '# Every setting is explained in the README, section "Recipe reference".',
        "",
        f"name = {_s(a.name)}",
        f"sample = {_s(a.sample)}  # the file this recipe was tried on",
        "",
        "[pages]",
        "# Which pages hold the table. Without a page setting every page is read.",
        (f"select = {_s(a.select)}" if a.select else '# select = "3-5"')
        + '  # page numbers: "3", "1-3, 7", "10-" (to the end)',
        "# start = 'TABLE\\s*4'  # or: from the first page whose text matches this,",
        "# stop = 'TABLE\\s*5'   #     up to (not including) the next page that matches this",
        (f"match = {_q(a.match)}" if a.match else "# match = 'All India'")
        + "  # only pages whose text matches (case-insensitive)",
        "",
        "[engines]",
        f"ocr = {'true' if a.ocr else 'false'}  # true: also read the pixels with OCR engines "
        "(scans, photos)",
        (
            f"use = {json.dumps(a.engines)}"
            if a.engines
            else '# use = ["pdfplumber", "pymupdf", "pdfium"]'
        )
        + "  # see: pdfexorcist engines",
        (f"min_agree = {a.min_agree}" if a.min_agree else "# min_agree = 3")
        + "  # engines that must read a value identically",
        "",
        "[normalize]",
        "# Clean every value before the vote, so the engines compare like with like.",
    ]
    for key, (field_name, example) in CLEAN.items():
        lines.append(f"{field_name} = {'true' if a.clean.get(key) else 'false'}  # {example}")
    lines += [
        "",
        "[parser]",
        "# How one line of text becomes cells:",
        '#   "rows":    a label, then the values in reading order (text PDFs)',
        '#   "columns": each value goes to the nearest column by position (scans, photos, blank '
        "cells)",
        '#   "custom":  your own Python function, e.g. function = "my_parser.py:parse"',
        f"type = {_s(a.parser)}",
        f"min_values = {a.min_values}  # skip lines with fewer values (titles, footnotes)",
        "",
    ]
    if not a.checks:
        lines += [
            "# Rules the agreed values must satisfy. A value that breaks one is kept, marked",
            '# in the "failed" column, and the run ends with exit code 1. For example:',
            "# [[checks]]",
            '# column = "label"           # the column that names the total and its parts',
            '# rule = "All India = rest"  # total = part + part ...; "rest" = every other row',
            '# by = ["page", "col"]       # checked separately within each page and column',
            "",
        ]
    for c in a.checks:
        lines += [
            "# A rule the agreed values must satisfy; values that break it are marked in",
            '# the "failed" column, and the run ends with exit code 1.',
            "[[checks]]",
            f"column = {_s(c['column'])}  # the column that names the total and its parts",
            f'rule = {_s(c["rule"])}  # total = part + part ...; "rest" = all the others; >= and '
            "<= work too",
            f"by = {json.dumps(c['by'])}  # checked separately within each of these",
            "",
        ]
    lines += [
        "[output]",
        'layout = "table"  # "table": a grid of agreed values; "cells": one row per cell, with '
        "votes",
        'format = "csv"    # csv, xlsx, parquet or json',
        "",
    ]
    return "\n".join(lines)
