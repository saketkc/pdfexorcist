"""Recipes."""

from pathlib import Path

from ._recipe_error import RecipeError
from ._recipe_load import SCHEMA, load, loads
from ._recipe_model import FORMATS, LAYOUTS, OPS, PARSERS, REST, Recipe, TotalRule, parse_rule
from .pages import parse_pages

__all__ = [
    "FORMATS",
    "LAYOUTS",
    "OPS",
    "PARSERS",
    "REST",
    "SCHEMA",
    "Recipe",
    "RecipeError",
    "TotalRule",
    "load",
    "loads",
    "page_list",
    "parse_rule",
]


def page_list(r: Recipe, pdf: Path, n_pages: int, override: str | None = None) -> list[int] | None:
    """Pages a run reads (None: all). --pages overrides the recipe's page choice."""
    from .pages import pages_matching

    if override:
        return parse_pages(override, n_pages)
    within = parse_pages(r.select, n_pages) if r.select else None
    if r.has_page_text:
        return pages_matching(pdf, r.start, r.stop, r.match, within)
    return within
