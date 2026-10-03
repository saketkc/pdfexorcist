"""Describe a recipe in words or JSON."""

from pathlib import Path
from typing import Any

from .recipe import Recipe, TotalRule
from .rows import KEY


def describe(r: Recipe) -> list[tuple[str, str]]:
    """Return plain-language setting pairs for recipe show."""
    rows: list[tuple[str, str]] = []
    if r.name or r.description:
        rows.append(("Name", " - ".join(x for x in (r.name, r.description) if x)))
    if r.sample:
        rows.append(("Made with", r.sample))
    pages = []
    if r.select:
        pages.append(f"pages {r.select}")
    if r.start:
        pages.append(f"from the first page matching '{r.start}'")
        pages.append(f"up to the page matching '{r.stop}'" if r.stop else "to the end")
    if r.match:
        pages.append(f"only pages matching '{r.match}'")
    if not r.fit_boxes:
        pages.append("page boxes kept as printed (text outside them ignored)")
    rows.append(("Pages", ", ".join(pages) if pages else "every page"))
    eng = ", ".join(r.engines) if r.engines else "the installed default engines"
    if r.ocr and not r.engines:
        eng += " + the installed OCR engines"
    rows.append(("Engines", eng))
    rows.append(
        (
            "Agreement",
            f"{r.min_agree} must read a value identically"
            if r.min_agree
            else "a strict majority, at least 3 (2 for OCR-only votes)",
        )
    )
    if r.min_unopposed:
        rows.append(
            (
                "Also accept",
                f"a value {r.min_unopposed} engines read when none read another",
            )
        )
    if r.families:
        rows.append(
            (
                "Families",
                "; ".join(f"{k}: {', '.join(v)} vote once" for k, v in r.families.items()),
            )
        )
    norm = [
        label
        for on, label in (
            (r.minus_signs, "unicode minus to -"),
            (r.raised_dots, "raised dots to decimal points (65·3 -> 65.3)"),
            (r.remove_commas, "remove thousands commas"),
            (r.remove_footnote_marks, "remove footnote marks (490* -> 490)"),
            (bool(r.normalize_function), f"your function {r.normalize_function}"),
        )
        if on
    ]
    rows.append(("Clean values", "; ".join(norm) if norm else "no"))
    if r.parser == "custom":
        rows.append(
            (
                "Parser",
                f"your function {r.parser_function}, cells keyed by {', '.join(r.key or KEY)}",
            )
        )
    else:
        how = (
            "values placed by their position (columns)"
            if r.parser == "columns"
            else "values in reading order (rows)"
        )
        opts = [f"rows with at least {r.min_values} values"] if r.min_values else []
        if r.tolerance is not None and r.parser == "columns":
            opts.append(f"tolerance {r.tolerance}")
        rows.append(("Parser", how + (f"; {', '.join(opts)}" if opts else "")))
    rows.extend(
        ("Check", c.describe() if isinstance(c, TotalRule) else f"your function {c}")
        for c in r.checks
    )
    if r.postprocess:
        rows.append(("After the vote", f"your function {r.postprocess}"))
    out = r.layout or "table"
    rows.append(
        (
            "Output",
            f"{r.format or 'csv'}, {out} layout"
            + (f", one column per {r.columns!r} value" if r.columns else "")
            + (f", one row per {', '.join(r.rows)}" if r.rows else ""),
        )
    )
    return rows


def as_dict(r: Recipe) -> dict[str, Any]:
    """Return a JSON-ready recipe view."""
    return {
        k: (list(v) if isinstance(v, tuple) else str(v) if isinstance(v, Path) else v)
        for k, v in r.__dict__.items()
        if not k.startswith("_") and k != "checks"
    } | {"checks": [c.describe() if isinstance(c, TotalRule) else c for c in r.checks]}
