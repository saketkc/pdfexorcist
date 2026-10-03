"""Wizard prompts."""

import tempfile
from pathlib import Path

import pandas as pd
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from . import recipe as recipes
from ._recipe_model import CLEANINGS
from ._ui import (
    err,
    esc,
    out,
    plural,
)
from ._wizard_toml import CLEAN, Answers, render
from .pages import IMAGE_SUFFIXES
from .rows import split_values

PREVIEW_PAGES = 2


def _samples(pdf: Path, page: int, limit: int = 8) -> list[tuple[str, list[str]]]:
    """Read sample label and value lines."""
    from .extractors import EXTRACTORS
    from .vote import _pages

    with tempfile.TemporaryDirectory() as tmp:
        cut = _pages(pdf, [page], Path(tmp))
        rows = []
        for _, lines in EXTRACTORS["pymupdf"](cut):
            for cells in lines:
                label, vals = split_values(cells)
                if vals:
                    rows.append((label, vals))
                if len(rows) >= limit:
                    break
    return rows


def _clean_changes(lines: list[tuple[str, list[str]]]) -> dict[str, bool]:
    """Report cleanings that affect sample values."""
    vals = [v for _, vs in lines for v in vs]
    rx = {name: pattern for name, pattern, _ in CLEANINGS}
    return {n: any(rx[field].search(v) for v in vals) for n, (field, _) in CLEAN.items()}


class Asker:
    """Prompt interactively or return defaults."""

    def __init__(self, interactive: bool) -> None:
        self.on = interactive

    def text(self, question: str, default: str = "") -> str:
        if not self.on:
            return default
        return (
            Prompt.ask(
                question,
                default=default or None,
                console=out,
                show_default=bool(default),
            )
            or ""
        )

    def choice(self, question: str, choices: list[str], default: str) -> str:
        if not self.on:
            return default
        return Prompt.ask(question, choices=choices, default=default, console=out)

    def yes(self, question: str, default: bool) -> bool:
        return Confirm.ask(question, default=default, console=out) if self.on else default

    def number(self, question: str, default: int) -> int:
        if not self.on:
            return default
        while True:
            n = IntPrompt.ask(question, default=default, console=out)
            if n >= 1:
                return n
            out.print("[red]Please enter 1 or more.[/]")


def _preview(
    a: Answers, src: Path, pages: list[int], output: Path, kinds: dict[int, dict] | None = None
) -> pd.DataFrame | None:
    """Preview the draft recipe on sample pages."""
    from ._output import to_table
    from ._run import EngineProgress, make_plan, run

    rec = recipes.loads(render(a, output.name), output.resolve())
    try_pages = pages[:PREVIEW_PAGES]
    spec = ",".join(map(str, try_pages))
    out.print(
        f"\nTrying the recipe on {'page' if len(try_pages) == 1 else 'pages'} {spec} of "
        f"{esc(src.name)} ..."
    )
    with tempfile.TemporaryDirectory() as tmp:
        plan = make_plan(
            src,
            rec,
            Path(tmp) / "preview.csv",
            None,
            None if src.suffix.lower() in IMAGE_SUFFIXES else spec,
            None,
            False,
            None,
            "table",
            True,
            kinds=kinds,
        )
        with EngineProgress(plan.methods, err.is_terminal, False) as prog:
            res, key = run(plan, rec, prog)
    table = to_table(res, key, "col").table
    verified = int((res.status == "verified").sum())
    out.print(
        f"{plural(verified, 'value')} agreed, {plural(int(len(res) - verified), 'cell')} "
        "unresolved."
    )
    if table is not None and len(table):
        _show_frame(table, "First rows of the result (blank = engines disagreed)")
    elif verified == 0:
        out.print("[yellow]No value was agreed on. Try other pages, the other parser, or OCR.[/]")
    return res


def _show_frame(df: pd.DataFrame, title: str, rows: int = 12, cols: int = 10) -> None:
    out.print(f"[bold]{esc(title)}[/]")
    t = Table(header_style="bold", show_edge=False)
    shown = list(df.columns[:cols])
    for c in shown:
        t.add_column(esc(c), overflow="ellipsis", max_width=28)
    for r in df.head(rows).itertuples(index=False):
        t.add_row(*["" if pd.isna(v) else esc(v) for v in list(r)[:cols]])
    out.print(t)
    more = [f"{len(df) - rows} more rows"] if len(df) > rows else []
    more += [f"{len(df.columns) - cols} more columns"] if len(df.columns) > cols else []
    if more:
        out.print(f"[dim]... and {' and '.join(more)}[/]")


def _ask_checks(a: Answers, ask: Asker, res: pd.DataFrame) -> None:
    if not ask.yes(
        "\nShould some values add up to a total (e.g. T = M + F, or States = All India)?",
        False,
    ):
        return
    labels = list(dict.fromkeys(res.get("label", pd.Series(dtype=str)).dropna()))
    while True:
        kind = ask.choice(
            "Is the total a row (below or above its parts) or a column (beside them)?",
            ["row", "column"],
            "row",
        )
        if kind == "row":
            guess = next(
                (x for x in reversed(labels) if "total" in x.lower() or "india" in x.lower()),
                "",
            )
            total = ask.text("Label of the total row, exactly as printed", guess)
            parts = ask.text(
                "Labels of the rows that add up to it, separated by + (Enter: all the other rows)",
                "",
            )
            column, by = "label", ["page", "col"]
        else:
            total = ask.text("Number of the total column (as in the preview header)", "0")
            parts = ask.text("Numbers of the columns that add up to it, e.g. 1 + 2", "1 + 2")
            column, by = "col", ["page", "row"]
        op = ask.choice(
            "Must the total equal the sum (=), or be at least the sum (>=)?",
            ["=", ">="],
            "=",
        )
        rule = f"{total} {op} {parts or 'rest'}"
        try:
            recipes.parse_rule(rule)
            a.checks.append({"column": column, "rule": rule, "by": by})
        except ValueError as e:
            out.print(f"[red]{esc(e)}[/]")
        if not ask.yes("Add another total?", False):
            return


def _check_preview(a: Answers, res: pd.DataFrame, output: Path) -> None:
    """Run new checks on the preview."""
    from .checks import validate

    rec = recipes.loads(render(a, output.name), output.resolve())
    ok = res[res.status == "verified"]
    try:
        failed = validate(ok, rec.check_functions())["failed"]
    except recipes.RecipeError as e:
        out.print(f"[red]{esc(e.message)}[/]")
        return
    bad = failed[failed != ""]
    if bad.empty:
        out.print("[green]The totals add up on the sample pages.[/]")
    else:
        out.print(
            f"[yellow]{plural(len(bad), 'value')} break a rule on the sample pages[/] (marked in "
            "the failed column when you run it)."
        )
