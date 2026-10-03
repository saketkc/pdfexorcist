"""Recipe model."""

from __future__ import annotations

import functools
import inspect
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ._recipe_error import RecipeError
from ._usercode import load_function
from .rows import KEY, parse_by_columns, parse_rows

if TYPE_CHECKING:
    import pandas as pd

    from .checks import Check

logger = logging.getLogger(__name__)

PARSERS = ("rows", "columns", "custom")
LAYOUTS = ("table", "cells")
FORMATS = ("csv", "xlsx", "parquet", "json")
OPS = {"=": "==", "==": "==", ">=": ">=", "<=": "<="}
REST = {"rest", "others", "the rest", "sum of the rest", "everything else", "..."}

# [normalize] switches in run order; the wizard offers those whose pattern hits the sample
CLEANINGS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    ("minus_signs", re.compile(r"^[−–—](?=\d)"), "-"),  # "−4" -> "-4"
    ("raised_dots", re.compile(r"(?<=\d)[·∙•](?=\d)"), "."),  # "65·3" -> "65.3"
    ("remove_commas", re.compile(r"(?<=\d),(?=\d)"), ""),  # "1,020" -> "1020"
    ("remove_footnote_marks", re.compile(r"(?<=[\d)])[*#@+$†‡]+$"), ""),  # "490*" -> "490"
)


@dataclass(frozen=True)
class TotalRule:
    """Total rule with a comparison against its parts' sum."""

    column: str
    total: str
    op: str = "=="
    parts: tuple[str, ...] | None = None  # None: every other value in the group
    by: tuple[str, ...] = ()
    where: str | None = None
    tolerance: float = 0.0
    abs_tolerance: float = 0.0
    missing: str = "skip"
    value: str = "value"
    name: str | None = None

    def describe(self) -> str:
        parts = " + ".join(self.parts) if self.parts else "the rest"
        op = {"==": "=", ">=": ">=", "<=": "<="}[self.op]
        text = f"{self.column} {self.total!r} {op} {parts}"
        if self.by:
            text += f", within each {', '.join(self.by)}"
        if self.where:
            text += f", where {self.where}"
        return text


@dataclass(frozen=True)
class Recipe:
    """Recipe settings, defaulting to the command-line behavior."""

    path: Path | None = None
    name: str = ""
    description: str = ""
    sample: str | None = None
    select: str | None = None
    start: str | None = None
    stop: str | None = None
    match: str | None = None
    fit_boxes: bool = True
    engines: tuple[str, ...] | None = None
    ocr: bool = False
    min_agree: int | None = None
    min_unopposed: int | None = None
    families: dict[str, list[str]] | None = None
    raised_dots: bool = False
    remove_commas: bool = False
    remove_footnote_marks: bool = False
    minus_signs: bool = False
    normalize_function: str | None = None
    parser: str = "rows"
    min_values: int | None = None
    tolerance: float | None = None
    parser_function: str | None = None
    key: tuple[str, ...] | None = None
    checks: tuple[Any, ...] = ()  # TotalRule or "file.py:function"
    postprocess: str | None = None
    layout: str | None = None
    columns: str | None = None
    rows: tuple[str, ...] | None = None
    format: str | None = None

    @property
    def base_dir(self) -> Path:
        return self.path.parent if self.path else Path.cwd()

    @property
    def has_page_text(self) -> bool:
        return bool(self.start or self.match)

    def parse_and_key(self) -> tuple[Callable, list[str]]:
        """Return the parser function and key columns."""
        if self.parser == "custom":
            fn = load_function(self.parser_function or "", self.base_dir, self.path, "parser")
            return fn, list(self.key or KEY)
        base = parse_by_columns if self.parser == "columns" else parse_rows
        opts: dict[str, Any] = {}
        if self.min_values is not None:
            opts["min_values"] = self.min_values
        if self.tolerance is not None and self.parser == "columns":
            opts["tol"] = self.tolerance
        if not opts:
            return base, list(KEY)

        def parse(pages: Iterable) -> Any:
            return base(pages, **opts)

        return parse, list(KEY)

    def normalizer(self) -> Callable[[str], str | None] | None:
        steps: list[Callable[[str], str | None]] = [
            functools.partial(rx.sub, repl) for name, rx, repl in CLEANINGS if getattr(self, name)
        ]
        if self.normalize_function:
            steps.append(
                load_function(self.normalize_function, self.base_dir, self.path, "normalize")
            )
        if not steps:
            return None

        def normalize(value: str) -> str | None:
            out: str | None = value
            for step in steps:
                if out is None:
                    return None
                out = step(out)
            return out

        return normalize

    def check_functions(self) -> list[Check]:
        out: list[Check] = []
        for c in self.checks:
            if isinstance(c, TotalRule):
                out.append(_rule_check(c))
                continue
            obj = load_function(c, self.base_dir, self.path, "check", allow_list=True)
            if isinstance(obj, (list, tuple)):
                out += list(obj)
            elif callable(obj) and not _required(obj):
                made = obj()  # a factory: adsi_checks() -> [check, ...]
                out += list(made) if isinstance(made, (list, tuple)) else [made]
            else:
                out.append(obj)
        return out

    def postprocess_function(self) -> Callable | None:
        if not self.postprocess:
            return None
        return load_function(self.postprocess, self.base_dir, self.path, "postprocess")

    def resolve_all(self) -> None:
        """Import referenced functions or raise RecipeError."""
        self.parse_and_key()
        self.normalizer()
        self.check_functions()
        self.postprocess_function()


def _required(fn: Callable) -> int:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return 1
    return sum(
        p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        for p in sig.parameters.values()
    )


def _rule_check(rule: TotalRule) -> Check:
    """Build a total check after normalizing rule columns to text."""
    from .checks import total_check

    tc = total_check(
        rule.column,
        rule.total,
        list(rule.parts) if rule.parts else None,
        by=list(rule.by),
        value=rule.value,
        op=rule.op,
        rel_tol=rule.tolerance,
        abs_tol=rule.abs_tolerance,
        where=rule.where,
        name=rule.name or rule.describe(),
        missing=rule.missing,
    )

    def fn(df: pd.DataFrame) -> pd.Series:
        need = [rule.column, rule.value, *rule.by]
        lost = [c for c in need if c not in df.columns]
        if lost:
            raise RecipeError(
                f"check {fn.__name__!r} uses column {lost[0]!r}, but the extracted cells "
                f"only have: {', '.join(map(str, df.columns))}",
                hint="Use one of those column names in the check's column / by.",
            )
        named = df[df[rule.column].notna()]  # a cell without a name is no part
        as_text = named[rule.column].map(
            lambda v: str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)
        )
        present = set(as_text)
        unmatched = [x for x in [rule.total, *(rule.parts or ())] if x not in present]
        fn.unmatched = unmatched  # type: ignore[attr-defined]
        if unmatched:
            seen = ", ".join(repr(v) for v in sorted(present, key=str)[:8])
            logger.warning(
                "check %r found no %s named %s, so it checked nothing there (%s values: %s%s)",
                fn.__name__,
                rule.column,
                " or ".join(repr(u) for u in unmatched),
                rule.column,
                seen,
                ", ..." if len(present) > 8 else "",
            )
        try:
            bad = tc(named.assign(**{rule.column: as_text}))
        except Exception as e:  # pandas raises many types for a bad query
            if not rule.where:
                raise
            raise RecipeError(
                f"check {fn.__name__!r}: where = {rule.where!r} failed ({type(e).__name__}: {e})",
                hint='where is a pandas query on the cell columns, e.g. "col <= 2" or '
                "\"label != 'Total'\"; put text in single quotes.",
            ) from None
        return bad.reindex(df.index, fill_value=False)

    fn.__name__ = tc.__name__
    return fn


def parse_rule(text: str) -> tuple[str, str, tuple[str, ...] | None]:
    """Parse a total expression into its label, operator, and parts."""
    m = re.match(r"^\s*(.+?)\s*(>=|<=|==|=)\s*(.+?)\s*$", text)
    if not m:
        raise ValueError(
            "a rule is the total, then =, >= or <=, then its parts joined by +: "
            '"T = M + F", or "All India = rest" for every other row'
        )
    total, op, rhs = m.group(1), OPS[m.group(2)], m.group(3)
    if rhs.lower() in REST:
        return total, op, None
    parts = re.split(r"\s+\+\s+", rhs) if re.search(r"\s\+\s", rhs) else rhs.split("+")
    parts = [p.strip() for p in parts]
    if not all(parts):
        raise ValueError(f"empty part in {rhs!r}")
    return total, op, tuple(parts)
