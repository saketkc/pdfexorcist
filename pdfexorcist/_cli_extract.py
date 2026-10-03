"""The extract command."""

from pathlib import Path

import typer

from . import recipe as recipes
from ._cli_app import (
    ADV_PANEL,
    ENG_PANEL,
    OUT_PANEL,
    Debug,
    Engines,
    Force,
    Jobs,
    MinAgree,
    Ocr,
    Quiet,
    __version__,
    app,
)
from ._ui import (
    CliError,
    check_min_agree,
    err,
    esc,
    guard,
    path_text,
    plural,
    print_json,
    resolve_input,
    setup_logging,
)


@app.command(
    epilog="[bold]Examples[/]\n\n"
    "  pdfexorcist extract report.pdf                   [dim]# writes report.csv[/]\n\n"
    "  pdfexorcist extract report.pdf --pages 3-5 -o tables.xlsx\n\n"
    "  pdfexorcist extract scan.pdf --ocr               [dim]# scans and photos[/]\n\n"
    "  pdfexorcist extract report.pdf --recipe mccd.toml\n\n"
    "  pdfexorcist extract report.pdf --json --quiet    [dim]# for scripts[/]",
)
def extract(
    file: str = typer.Argument(
        ...,
        metavar="FILE",
        help="The PDF or image (.png, .jpg, ...) to read, or a link to one.",
        show_default=False,
    ),
    recipe: Path | None = typer.Option(
        None,
        "--recipe",
        "-r",
        metavar="RECIPE",
        help="Settings saved with [cyan]pdfexorcist recipe new[/].",
        show_default=False,
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        rich_help_panel=OUT_PANEL,
        show_default=False,
        metavar="PATH",
        help="Where to write: a file (its ending picks the format) or a folder. Default: next to "
        "the input.",
    ),
    fmt: str | None = typer.Option(
        None,
        "--format",
        "-f",
        rich_help_panel=OUT_PANEL,
        show_default=False,
        metavar="FORMAT",
        help="csv (default), xlsx, parquet or json.",
    ),
    layout: str | None = typer.Option(
        None,
        "--layout",
        rich_help_panel=OUT_PANEL,
        show_default=False,
        metavar="table|cells",
        help="table (default): the agreed values as a grid, plus a .review file of cells to check. "
        "cells: one row per cell with every engine's reading.",
    ),
    force: Force = False,
    pages: str | None = typer.Option(
        None,
        "--pages",
        "-p",
        rich_help_panel=ENG_PANEL,
        show_default=False,
        metavar="PAGES",
        help='Pages to read, e.g. "3" or "1-3,7" or "10-". Default: all (or the recipe\'s).',
    ),
    ocr: Ocr = False,
    engines: Engines = None,
    min_agree: MinAgree = None,
    jobs: Jobs = 1,
    quiet: Quiet = False,
    as_json: bool = typer.Option(
        False,
        "--json",
        rich_help_panel=ADV_PANEL,
        help="Print a machine-readable summary on stdout.",
    ),
    debug: Debug = False,
) -> None:
    """Read the tables in a PDF or image and write the values most engines agree on.

    Writes [bold]report.csv[/] next to [bold]report.pdf[/]: the agreed values as a grid. Cells
    the engines disagreed on are left blank and listed, with every reading, in
    [bold]report.review.csv[/].
    """
    from ._output import render_summary, summarise, write
    from ._run import EngineProgress, load_recipe, make_plan, run

    with guard(debug, as_json):
        notes = setup_logging(debug)
        check_min_agree(min_agree)
        if fmt is not None and fmt not in recipes.FORMATS:
            raise CliError(
                f"--format {fmt!r} is not one of {', '.join(recipes.FORMATS)}.",
                "Example: --format xlsx",
            )
        if layout is not None and layout not in recipes.LAYOUTS:
            raise CliError(f"--layout {layout!r} is not table or cells.", "Example: --layout cells")
        src = resolve_input(file)
        rec = load_recipe(recipe)
        plan = make_plan(src, rec, output, fmt, pages, engines, ocr, min_agree, layout, force)
        if not (quiet or as_json):
            what = (
                f"{'page' if len(plan.pages) == 1 else 'pages'} {_page_ranges(plan.pages)} of "
                if plan.pages
                else ""
            )
            agree = f"{plan.min_agree} must agree" if plan.min_agree else "a majority must agree"
            err.print(
                f"Reading {what}[bold]{esc(path_text(src))}[/] with "
                f"{plural(len(plan.methods), 'engine')} "
                f"({agree})" + (f", recipe [bold]{esc(path_text(recipe))}[/]" if recipe else "")
            )
        live = err.is_terminal and not as_json
        with EngineProgress(plan.methods, live, quiet or as_json) as prog:
            res, key = run(plan, rec, prog, jobs)
        result = write(plan, res, key)
        summary = summarise(plan, res, prog, result, notes.notes)
        if as_json:
            print_json({"pdfexorcist": __version__, **summary})
        elif not quiet:
            render_summary(summary)
        raise typer.Exit(summary["exit_code"])


def _page_ranges(pages: list[int]) -> str:
    """Compact page numbers into ranges."""
    runs: list[list[int]] = []
    for p in pages:
        if runs and p == runs[-1][1] + 1:
            runs[-1][1] = p
        else:
            runs.append([p, p])
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)
