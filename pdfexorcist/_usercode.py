"""Load a recipe's Python from its folder."""

import difflib
import hashlib
import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

from ._recipe_error import RecipeError

_MODULES: dict[Path, Any] = {}


def load_function(
    ref: str, base: Path, recipe: Path | None, what: str, allow_list: bool = False
) -> Any:
    """Import a function from a recipe-relative Python file."""
    m = re.fullmatch(r"\s*([^:]+\.py)\s*:\s*([A-Za-z_]\w*)\s*", ref or "")
    if not m:
        raise RecipeError(
            f'{what} function {ref!r} should look like "my_file.py:function_name"',
            recipe,
            hint="Name a .py file next to the recipe, a colon, and the function in it.",
        )
    rel, name = m.group(1), m.group(2)
    base = base.resolve()
    file = (base / rel).resolve()
    try:
        file.relative_to(base)
    except ValueError:
        raise RecipeError(
            f"{what} file {rel!r} is outside the recipe's folder ({base})",
            recipe,
            hint="Keep the .py file in the same folder as the recipe (or below it).",
        ) from None
    if not file.is_file():
        near = difflib.get_close_matches(rel, [p.name for p in base.glob("*.py")], n=1)
        raise RecipeError(
            f"{what} file {rel!r} not found in {base}",
            recipe,
            hint=f"Did you mean {near[0]!r}?" if near else "Check the file name and its folder.",
        )
    module = _MODULES.get(file) or _import(file, recipe)
    if not hasattr(module, name):
        funcs = [k for k, v in vars(module).items() if callable(v) and not k.startswith("_")]
        near = difflib.get_close_matches(name, funcs, n=1)
        raise RecipeError(
            f"{rel} has no function {name!r}",
            recipe,
            hint=f"Did you mean {near[0]!r}?"
            if near
            else f"Functions in {rel}: {', '.join(funcs) or 'none'}",
        )
    obj = getattr(module, name)
    if not (callable(obj) or (allow_list and isinstance(obj, (list, tuple)))):
        raise RecipeError(f"{rel}:{name} is not a function", recipe)
    return obj


def _import(file: Path, recipe: Path | None) -> Any:
    folder = str(file.parent)
    if folder not in sys.path:  # so the file can import its neighbours
        sys.path.insert(0, folder)
    digest = hashlib.md5(str(file).encode()).hexdigest()[:8]
    spec = importlib.util.spec_from_file_location(f"pdfexorcist_recipe_{file.stem}_{digest}", file)
    if spec is None or spec.loader is None:
        raise RecipeError(f"cannot load {file}", recipe)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SyntaxError as e:
        raise RecipeError(
            f"{file.name} line {e.lineno}: {e.msg}",
            recipe,
            hint="Fix the Python syntax error there.",
        ) from e
    except Exception as e:  # any import-time failure in user code
        hint = (
            f"Install it: pip install {e.name}"
            if isinstance(e, ModuleNotFoundError) and e.name
            else "Run the file with python to see the full error, or use --debug."
        )
        raise RecipeError(
            f"{file.name} failed to import: {type(e).__name__}: {e}", recipe, hint=hint
        ) from e
    _MODULES[file] = module
    return module
