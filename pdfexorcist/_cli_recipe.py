"""The recipe commands."""

from pathlib import Path

import typer
from rich.panel import Panel
from rich.table import Table

from . import recipe as recipes
from ._cli_app import recipe_app
from ._recipe_text import as_dict, describe
from ._ui import (
    CliError,
    cmd_arg,
    esc,
    guard,
    out,
    path_text,
    print_json,
    setup_logging,
)


@recipe_app.command(
    "new",
    epilog="[bold]Examples[/]\n\n"
    "  pdfexorcist recipe new report.pdf                [dim]# asks a few questions[/]\n\n"
    "  pdfexorcist recipe new report.pdf --yes --pages 3-5 --parser rows "
    '--total "label: All India = rest" -o states.toml',
)
def recipe_new(
    sample: str | None = typer.Argument(
        None,
        metavar="SAMPLE",
        help="A PDF or image with the table, to try the recipe on.",
        show_default=False,
    ),
    pages: str | None = typer.Option(
        None,
        "--pages",
        "-p",
        metavar="PAGES",
        rich_help_panel="Answers (each skips its question)",
        help='Pages with the table, e.g. "3-5". Default: all.',
        show_default=False,
    ),
    page_text: str | None = typer.Option(
        None,
        "--page-text",
        metavar="REGEX",
        rich_help_panel="Answers (each skips its question)",
        help="Use only pages whose text matches this (a regular expression).",
        show_default=False,
    ),
    ocr: bool | None = typer.Option(
        None,
        "--ocr/--no-ocr",
        rich_help_panel="Answers (each skips its question)",
        help="Read with OCR engines (scans, photos). Default: on for scans and images.",
        show_default=False,
    ),
    parser: str | None = typer.Option(
        None,
        "--parser",
        metavar="rows|columns",
        rich_help_panel="Answers (each skips its question)",
        help="rows: values in reading order. columns: values placed by position (scans, blank "
        "cells).",
        show_default=False,
    ),
    min_values: int | None = typer.Option(
        None,
        "--min-values",
        metavar="N",
        rich_help_panel="Answers (each skips its question)",
        help="Skip lines with fewer values (titles, notes). Default: 2.",
        show_default=False,
    ),
    clean: str | None = typer.Option(
        None,
        "--clean",
        metavar="LIST",
        rich_help_panel="Answers (each skips its question)",
        help="Number clean-ups, comma-separated: commas, footnotes, raised-dots, minus. "
        "Default: those seen on the sample page.",
        show_default=False,
    ),
    total: list[str] | None = typer.Option(
        None,
        "--total",
        metavar='"COLUMN: RULE"',
        rich_help_panel="Answers (each skips its question)",
        help='A total that must add up; repeatable. "label: All India = rest" (a total row), '
        '"col: 0 = 1 + 2" (a total column); add "per page,row" to say where it applies.',
        show_default=False,
    ),
    engines: str | None = typer.Option(
        None,
        "--engines",
        "-e",
        metavar="NAMES",
        rich_help_panel="Answers (each skips its question)",
        help="Engines to use, comma-separated. Default: the installed ones.",
        show_default=False,
    ),
    min_agree: int | None = typer.Option(
        None,
        "--min-agree",
        "-k",
        metavar="N",
        rich_help_panel="Answers (each skips its question)",
        help="Engines that must agree. Default: a strict majority.",
        show_default=False,
    ),
    name: str | None = typer.Option(
        None,
        "--name",
        metavar="TEXT",
        rich_help_panel="Answers (each skips its question)",
        help="A short name for the recipe. Default: the sample's name.",
        show_default=False,
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        metavar="FILE",
        rich_help_panel="How to run",
        help="Recipe file to write. Default: <sample>.recipe.toml here.",
        show_default=False,
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        rich_help_panel="How to run",
        help="Ask nothing: use the options given and defaults for the rest.",
    ),
    preview: bool = typer.Option(
        True,
        "--preview/--no-preview",
        rich_help_panel="How to run",
        help="Try the recipe on the sample and show the first rows.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        rich_help_panel="How to run",
        help="Replace an existing recipe file.",
    ),
    debug: bool = typer.Option(
        False, "--debug", rich_help_panel="How to run", help="Show full error details."
    ),
) -> None:
    """Create a recipe by answering a few plain questions (or from options, with --yes)."""
    from ._wizard import WizardOptions, new_recipe

    with guard(debug):
        setup_logging(debug)
        for flag, n in (("--min-values", min_values), ("--min-agree", min_agree)):
            if n is not None and n < 1:
                raise CliError(f"{flag} must be 1 or more.")
        new_recipe(
            WizardOptions(
                sample=sample,
                output=output,
                name=name,
                pages=pages,
                page_text=page_text,
                parser=parser,
                min_values=min_values,
                clean=clean,
                totals=list(total or []),
                ocr=ocr,
                engines=engines,
                min_agree=min_agree,
                yes=yes,
                preview=preview,
                force=force,
            )
        )


@recipe_app.command("check", epilog="[bold]Example[/]\n\n  pdfexorcist recipe check states.toml")
def recipe_check(
    file: Path = typer.Argument(..., metavar="RECIPE", help="The recipe file.", show_default=False),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON."),
    debug: bool = typer.Option(False, "--debug", help="Show full error details."),
) -> None:
    """Check a recipe for mistakes; names the line to fix. Also imports any Python it names."""
    with guard(debug, as_json):
        setup_logging(debug)
        rec = recipes.load(file)
        rec.resolve_all()
        if as_json:
            print_json({"ok": True, "recipe": as_dict(rec)})
            return
        out.print(f"[green]OK[/]: [bold]{esc(path_text(file))}[/] is a valid recipe.")
        out.print(
            f"Use it with: [cyan]pdfexorcist extract YOUR.pdf --recipe {esc(cmd_arg(file))}[/]"
        )


@recipe_app.command("show", epilog="[bold]Example[/]\n\n  pdfexorcist recipe show states.toml")
def recipe_show(
    file: Path = typer.Argument(..., metavar="RECIPE", help="The recipe file.", show_default=False),
    raw: bool = typer.Option(False, "--raw", help="Print the file itself, with colours."),
    as_json: bool = typer.Option(False, "--json", help="Print the settings as JSON."),
    debug: bool = typer.Option(False, "--debug", help="Show full error details."),
) -> None:
    """Explain in plain words what a recipe will do (runs none of its code)."""
    with guard(debug, as_json):
        rec = recipes.load(file)
        if as_json:
            print_json(as_dict(rec))
            return
        if raw:
            from rich.syntax import Syntax

            out.print(
                Syntax(
                    Path(file).read_text(encoding="utf-8"),
                    "toml",
                    line_numbers=True,
                    word_wrap=True,
                )
            )
            return
        t = Table.grid(padding=(0, 2))
        t.add_column(style="bold", no_wrap=True)
        t.add_column()
        for what, setting in describe(rec):
            t.add_row(what, esc(setting))
        out.print(
            Panel(
                t,
                title=f"[bold]{esc(path_text(file))}[/]",
                title_align="left",
                border_style="cyan",
            )
        )
        out.print(f"Run it: [cyan]pdfexorcist extract YOUR.pdf --recipe {esc(cmd_arg(file))}[/]")
