"""Extract tables from PDFs by majority vote."""

import importlib
import sys
import types
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .checks import check, total_check, validate
    from .extractors import EXTRACTORS, register
    from .pages import pages_matching, parse_pages
    from .rows import KEY, group_words, parse_by_columns, parse_rows
    from .vote import extract, fit_page_boxes, vote

_MODULE = {
    "EXTRACTORS": "extractors",
    "KEY": "rows",
    "check": "checks",
    "extract": "vote",
    "fit_page_boxes": "vote",
    "group_words": "rows",
    "pages_matching": "pages",
    "parse_by_columns": "rows",
    "parse_pages": "pages",
    "parse_rows": "rows",
    "register": "extractors",
    "total_check": "checks",
    "validate": "checks",
    "vote": "vote",
}

__all__ = [
    "EXTRACTORS",
    "KEY",
    "check",
    "extract",
    "fit_page_boxes",
    "group_words",
    "pages_matching",
    "parse_by_columns",
    "parse_pages",
    "parse_rows",
    "register",
    "total_check",
    "validate",
    "vote",
]


def __getattr__(name: str) -> Any:
    if name not in _MODULE:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f".{_MODULE[name]}", __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


class _Package(types.ModuleType):
    """Preserve the vote function when its submodule loads."""

    def __setattr__(self, name: str, value: Any) -> None:
        if isinstance(value, types.ModuleType) and name in _MODULE and _MODULE[name] == name:
            value = getattr(value, name)
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _Package
