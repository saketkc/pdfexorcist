"""Load and check recipe TOML."""

import difflib
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ._recipe_error import RecipeError
from ._recipe_model import FORMATS, LAYOUTS, OPS, PARSERS, Recipe, TotalRule, parse_rule
from .extractors import EXTRACTORS
from .pages import parse_pages

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    import tomli as tomllib

_TEXT = ((str,), 'text in quotes, like "abc"')
_TEXTS = ((list,), 'a list of texts, like ["a", "b"]')
_INT = ((int,), "a whole number, like 3")
_NUM = ((int, float), "a number, like 0.5")
_BOOL = ((bool,), "true or false")
SCHEMA: dict[str, dict[str, tuple[tuple, str]]] = {
    "": {"name": _TEXT, "description": _TEXT, "sample": _TEXT},
    "pages": {
        "select": ((str, int), 'page numbers in quotes, like "1-3, 7" or "21-"'),
        "start": _TEXT,
        "stop": _TEXT,
        "match": _TEXT,
        "fit_boxes": _BOOL,
    },
    "engines": {
        "use": _TEXTS,
        "ocr": _BOOL,
        "min_agree": _INT,
        "min_unopposed": _INT,
        "families": (
            (dict,),
            'a table of lists, like { ocr = ["tesseract", "pdfplumber"] }',
        ),
    },
    "normalize": {
        "raised_dots": _BOOL,
        "remove_commas": _BOOL,
        "remove_footnote_marks": _BOOL,
        "minus_signs": _BOOL,
        "function": _TEXT,
    },
    "parser": {
        "type": _TEXT,
        "min_values": _INT,
        "tolerance": _NUM,
        "function": _TEXT,
        "key": _TEXTS,
    },
    "checks": {
        "name": _TEXT,
        "column": _TEXT,
        "rule": _TEXT,
        "total": ((str, int), "text or a number"),
        "parts": ((list,), 'a list, like ["M", "F"]'),
        "by": _TEXTS,
        "op": _TEXT,
        "where": _TEXT,
        "tolerance": _NUM,
        "abs_tolerance": _NUM,
        "missing": _TEXT,
        "value": _TEXT,
        "function": _TEXT,
    },
    "postprocess": {"function": _TEXT},
    "output": {"layout": _TEXT, "columns": _TEXT, "rows": _TEXTS, "format": _TEXT},
}


def _line(text: str, section: str, key: str | None = None, index: int = 0) -> int | None:
    """Return a key's 1-based line, or its section header's line."""
    current, seen, header = "", -1, None
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if h := re.match(r"^\[\[?\s*([\w.-]+)\s*\]\]?", line):
            current = h.group(1)
            if current == section:
                seen += 1
                if seen == index:
                    header = i
            continue
        name = re.escape(key or "")
        is_key = bool(key) and bool(re.match(rf'^"?{name}"?\s*=', line))
        if current == section and (not section or seen == index) and is_key:
            return i
    return header


def load(path: Path) -> Recipe:
    """Load a recipe, locating invalid entries with RecipeError."""
    path = Path(path)
    if not path.is_file():
        raise RecipeError(
            f"recipe file not found: {path}",
            hint="Create one with: pdfexorcist recipe new",
        )
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
        data = tomllib.loads(text)
    except UnicodeDecodeError:
        raise RecipeError("the recipe is not UTF-8 text", path, hint="Save it as UTF-8.") from None
    except tomllib.TOMLDecodeError as e:
        m = re.search(r"line (\d+)", str(e))
        raise RecipeError(
            f"not valid TOML: {e}",
            path,
            int(m.group(1)) if m else None,
            hint='Texts need quotes ("..."), lists need brackets ([...]); see examples/.',
        ) from None
    return _recipe(data, path, text)


def loads(text: str, path: Path | None = None) -> Recipe:
    """Load a recipe from TOML text."""
    return _recipe(tomllib.loads(text), path, text)


def _recipe(data: dict[str, Any], path: Path | None, text: str) -> Recipe:
    def err(
        msg: str,
        section: str = "",
        key: str | None = None,
        index: int = 0,
        hint: str = "",
    ) -> RecipeError:
        return RecipeError(msg, path, _line(text, section, key, index), hint)

    def check_keys(table: dict[str, Any], section: str, index: int = 0) -> None:
        allowed = SCHEMA[section]
        where = f"[{section}]" if section else "the top of the recipe"
        for k, v in table.items():
            if k not in allowed:
                near = difflib.get_close_matches(k, list(allowed), n=1)
                raise err(
                    f"unknown setting {k!r} in {where}",
                    section,
                    k,
                    index,
                    hint=f"Did you mean {near[0]!r}?"
                    if near
                    else f"Settings there: {', '.join(allowed)}",
                )
            types, desc = allowed[k]
            if not isinstance(v, types) or (isinstance(v, bool) and bool not in types):
                raise err(f"{where} {k} should be {desc}, not {v!r}", section, k, index)

    sections = [k for k in SCHEMA if k]
    for k, v in data.items():
        if isinstance(v, dict) and k not in SCHEMA:
            near = difflib.get_close_matches(k, sections, n=1)
            raise err(
                f"unknown section [{k}]",
                k,
                hint=f"Did you mean [{near[0]}]?" if near else f"Sections: {', '.join(sections)}",
            )
        if k in SCHEMA and k != "checks" and not isinstance(v, dict):
            raise err(f"{k} should be a section: [{k}]", "", k)
    top = {k: v for k, v in data.items() if k not in SCHEMA}
    check_keys(top, "")
    for section in ("pages", "engines", "normalize", "parser", "postprocess", "output"):
        check_keys(data.get(section, {}), section)
    checks_raw = data.get("checks", [])
    if not isinstance(checks_raw, list):
        raise err("checks should be one or more [[checks]] sections", "", "checks")
    for i, c in enumerate(checks_raw):
        check_keys(c, "checks", i)

    pages, eng = data.get("pages", {}), data.get("engines", {})
    norm, par = data.get("normalize", {}), data.get("parser", {})
    out = data.get("output", {})

    select = str(pages["select"]) if "select" in pages else None
    if select is not None:
        try:
            parse_pages(select, n_pages=10**5)
        except ValueError as e:
            raise err(f"[pages] select: {e}", "pages", "select") from None
    for k in ("start", "stop", "match"):
        if k in pages:
            try:
                re.compile(pages[k])
            except re.error as e:
                raise err(
                    f"[pages] {k} is not a valid regular expression: {e}",
                    "pages",
                    k,
                    hint="Write plain words to match them; escape ( ) . * with a backslash, "
                    "and use single quotes '...' so backslashes stay as typed.",
                ) from None
    if "stop" in pages and "start" not in pages:
        raise err("[pages] stop needs a start", "pages", "stop")

    engines = None
    if "use" in eng:
        engines = tuple(eng["use"])
        for name in engines:
            if not isinstance(name, str) or name not in EXTRACTORS:
                near = difflib.get_close_matches(str(name), list(EXTRACTORS), n=1)
                raise err(
                    f"[engines] use: unknown engine {name!r}",
                    "engines",
                    "use",
                    hint=f"Did you mean {near[0]!r}?" if near else "See: pdfexorcist engines",
                )
    for k in ("min_agree", "min_unopposed"):
        if k in eng and eng[k] < 1:
            raise err(f"[engines] {k} must be at least 1", "engines", k)
    families = eng.get("families")
    if families is not None:
        for fam, members in families.items():
            if not isinstance(members, list) or not all(m in EXTRACTORS for m in members):
                raise err(
                    f"[engines] families.{fam} should list engine names",
                    "engines",
                    "families",
                    hint='Example: families = { ocr_layer = ["pdfplumber", "pymupdf"] }',
                )

    ptype = par.get("type", "custom" if "function" in par else "rows")
    if ptype not in PARSERS:
        raise err(
            f"[parser] type must be one of {', '.join(PARSERS)}, not {ptype!r}",
            "parser",
            "type",
            hint='"rows": values in reading order; "columns": values placed by position; '
            '"custom": your own function',
        )
    if ptype == "custom" and "function" not in par:
        raise err(
            '[parser] type "custom" needs function = "my_parser.py:parse"',
            "parser",
            "type",
        )
    if ptype != "custom" and "function" in par:
        raise err('[parser] function is only used with type = "custom"', "parser", "function")
    if "key" in par and ptype != "custom":
        raise err("[parser] key is only used by a custom parser", "parser", "key")
    if "min_values" in par and par["min_values"] < 1:
        raise err("[parser] min_values must be at least 1", "parser", "min_values")
    if "tolerance" in par and not 0 < par["tolerance"] < 1:
        raise err(
            "[parser] tolerance must be between 0 and 1, e.g. 0.45",
            "parser",
            "tolerance",
        )

    checks: list[Any] = []
    for i, c in enumerate(checks_raw):
        checks.append(_check(c, i, err))

    if out.get("layout", "table") not in LAYOUTS:
        raise err(f"[output] layout must be {' or '.join(LAYOUTS)}", "output", "layout")
    if out.get("format", "csv") not in FORMATS:
        raise err(f"[output] format must be one of {', '.join(FORMATS)}", "output", "format")

    return Recipe(
        path=path.resolve() if path else None,
        name=top.get("name", ""),
        description=top.get("description", ""),
        sample=top.get("sample"),
        select=select,
        start=pages.get("start"),
        stop=pages.get("stop"),
        match=pages.get("match"),
        fit_boxes=pages.get("fit_boxes", True),
        engines=engines,
        ocr=eng.get("ocr", False),
        min_agree=eng.get("min_agree"),
        min_unopposed=eng.get("min_unopposed"),
        families=families,
        raised_dots=norm.get("raised_dots", False),
        remove_commas=norm.get("remove_commas", False),
        remove_footnote_marks=norm.get("remove_footnote_marks", False),
        minus_signs=norm.get("minus_signs", False),
        normalize_function=norm.get("function"),
        parser=ptype,
        min_values=par.get("min_values"),
        tolerance=par.get("tolerance"),
        parser_function=par.get("function"),
        key=tuple(par["key"]) if "key" in par else None,
        checks=tuple(checks),
        postprocess=data.get("postprocess", {}).get("function"),
        layout=out.get("layout"),
        columns=out.get("columns"),
        rows=tuple(out["rows"]) if "rows" in out else None,
        format=out.get("format"),
    )


def _check(c: dict[str, Any], i: int, err: Callable[..., RecipeError]) -> Any:
    """Convert one checks table to a rule or Python reference."""
    n = f"[[checks]] number {i + 1}"
    if "function" in c:
        extra = set(c) - {"function", "name"}
        if extra:
            raise err(
                f"{n}: a function check takes no {min(extra)!r}",
                "checks",
                min(extra),
                i,
            )
        return c["function"]
    if "column" not in c:
        raise err(
            f'{n} needs column = "..." (the column that names the total and its parts)',
            "checks",
            None,
            i,
            hint='Example: column = "label" and rule = "Total = rest"',
        )
    if "rule" in c and ("total" in c or "parts" in c):
        raise err(
            f"{n}: give either rule, or total (and parts), not both",
            "checks",
            "rule",
            i,
        )
    if "rule" in c:
        try:
            total, op, parts = parse_rule(c["rule"])
        except ValueError as e:
            raise err(f"{n} rule {c['rule']!r}: {e}", "checks", "rule", i) from None
        if "op" in c:
            raise err(
                f"{n}: the rule already has its =, >= or <=; remove op",
                "checks",
                "op",
                i,
            )
    elif "total" in c:
        total = str(c["total"])
        op = OPS.get(c.get("op", "=="), "")
        if not op:
            raise err(f"{n} op must be =, >= or <=", "checks", "op", i)
        parts = tuple(str(p) for p in c["parts"]) if "parts" in c else None
    else:
        raise err(
            f'{n} needs rule = "Total = A + B" (or total = ... and parts = [...])',
            "checks",
            None,
            i,
        )
    if c.get("missing", "skip") not in ("skip", "fail"):
        raise err(f'{n} missing must be "skip" or "fail"', "checks", "missing", i)
    for k in ("tolerance", "abs_tolerance"):
        if c.get(k, 0) < 0:
            raise err(f"{n} {k} cannot be negative", "checks", k, i)
    return TotalRule(
        column=c["column"],
        total=total,
        op=op,
        parts=parts,
        by=tuple(c.get("by", ())),
        where=c.get("where"),
        tolerance=float(c.get("tolerance", 0.0)),
        abs_tolerance=float(c.get("abs_tolerance", 0.0)),
        missing=c.get("missing", "skip"),
        value=c.get("value", "value"),
        name=c.get("name"),
    )
