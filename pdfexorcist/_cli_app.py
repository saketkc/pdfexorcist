"""Typer apps and the welcome screen."""

from importlib.metadata import PackageNotFoundError, version
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ._ui import (
    out,
)

try:
    __version__ = version("pdfexorcist")
except PackageNotFoundError:  # running from a source checkout
    __version__ = "0+unknown"

app = typer.Typer(
    name="pdfexorcist",
    help="Pull tables out of PDFs and photos by majority vote.",
    rich_markup_mode="rich",
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
    pretty_exceptions_enable=False,
)
recipe_app = typer.Typer(
    help="Save the settings for one kind of table in a recipe file, and reuse them.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)
app.add_typer(recipe_app, name="recipe")

COMMANDS = {"extract", "inspect", "engines", "doctor", "recipe", "show", "compare"}
OUT_PANEL, ENG_PANEL, ADV_PANEL = "Output", "Engines and pages", "Advanced"

Force = Annotated[
    bool,
    typer.Option("--force", rich_help_panel=OUT_PANEL, help="Replace existing output files."),
]
Quiet = Annotated[
    bool, typer.Option("--quiet", "-q", rich_help_panel=ADV_PANEL, help="Print only errors.")
]
Debug = Annotated[
    bool,
    typer.Option("--debug", rich_help_panel=ADV_PANEL, help="Show full error details and logs."),
]
Ocr = Annotated[
    bool,
    typer.Option(
        "--ocr",
        rich_help_panel=ENG_PANEL,
        help="Also read the page pixels with the installed OCR engines: the right choice for "
        "scans and photos.",
    ),
]
ShowOcr = Annotated[
    bool,
    typer.Option(
        "--ocr",
        rich_help_panel=ENG_PANEL,
        help="Also read the page pixels with the installed OCR engines (scans, photos).",
    ),
]
Engines = Annotated[
    str | None,
    typer.Option(
        "--engines",
        "-e",
        rich_help_panel=ENG_PANEL,
        show_default=False,
        metavar="NAMES",
        help="Engines to use, comma-separated, e.g. pdfplumber,pymupdf,pdfium. See: pdfexorcist "
        "engines.",
    ),
]
ShowEngines = Annotated[
    str | None,
    typer.Option(
        "--engines",
        "-e",
        rich_help_panel=ENG_PANEL,
        show_default=False,
        metavar="NAMES",
        help="Engines to use, comma-separated. See: pdfexorcist engines.",
    ),
]
MinAgree = Annotated[
    int | None,
    typer.Option(
        "--min-agree",
        "-k",
        rich_help_panel=ENG_PANEL,
        show_default=False,
        metavar="N",
        help="Engines that must read a value identically. Default: a strict majority, at least 3 "
        "(2 when only OCR engines read).",
    ),
]
Jobs = Annotated[
    int,
    typer.Option(
        "--jobs",
        "-j",
        min=1,
        rich_help_panel=ENG_PANEL,
        metavar="N",
        help="Run up to N engines at once, each in its own process. Default: 1 (one after "
        "another).",
    ),
]
ShowMinAgree = Annotated[
    int | None,
    typer.Option(
        "--min-agree",
        "-k",
        rich_help_panel=ENG_PANEL,
        show_default=False,
        metavar="N",
        help="Engines that must read a value identically. Default: a strict majority.",
    ),
]


def _version(value: bool) -> None:
    if value:
        out.print(f"pdfexorcist {__version__}")
        raise typer.Exit()


def welcome() -> None:
    """The screen shown by a bare pdfexorcist."""
    lines = Table.grid(padding=(0, 2))
    lines.add_column(style="bold cyan", no_wrap=True)
    lines.add_column(style="dim")
    for cmd, what in [
        ("pdfexorcist inspect report.pdf", "text or scan? which command to run"),
        ("pdfexorcist extract report.pdf", "write the agreed values to report.csv"),
        ("pdfexorcist extract photo.jpg --ocr", "scans and photos: read the pixels"),
        ("pdfexorcist show report.pdf --page 3", "see on the page what will be extracted"),
        ("pdfexorcist recipe new report.pdf", "save the settings for a tricky table"),
        ("pdfexorcist engines", "installed engines, and how to add more"),
    ]:
        lines.add_row("  " + cmd, what)
    body = Text.assemble(
        ("Pull tables out of PDFs and photos. ", "bold"),
        "Several independent engines read every page, and a value is kept only when most of "
        "them read it identically. Anything they disagree on is left blank for you to review, "
        "never guessed.",
    )
    out.print(
        Panel(
            body,
            title=f"[bold]pdfexorcist {__version__}[/]",
            title_align="left",
            border_style="cyan",
        )
    )
    out.print("[bold]Get started[/]")
    out.print(lines)
    out.print("\n[bold]Help[/]")
    out.print("  pdfexorcist extract --help   [dim]options and examples for one command[/]")
    out.print("  pdfexorcist --help           [dim]every command[/]")


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    show_version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version,
        is_eager=True,
        help="Show the version and exit.",
    ),
) -> None:
    """Pull tables out of PDFs and photos by majority vote."""
    if ctx.invoked_subcommand is None:
        welcome()
