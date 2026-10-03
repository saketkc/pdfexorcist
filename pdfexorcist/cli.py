"""Command-line entry point."""

import contextlib
import re
import sys
from pathlib import Path

import typer

from . import (  # noqa: F401  # register extract (listed before show) and recipe
    _cli_extract,
    _cli_recipe,
)
from ._cli_app import (
    COMMANDS,
    OUT_PANEL,
    Debug,
    Force,
    Jobs,
    Quiet,
    ShowEngines,
    ShowMinAgree,
    ShowOcr,
    app,
)
from ._ui import check_min_agree, guard, setup_logging

__all__ = ["app", "main"]


def _show_command(start: str, kind: str):  # type: ignore[no-untyped-def]
    """Build the shared show and compare command."""

    def command(
        file: str = typer.Argument(
            ...,
            metavar="FILE",
            help="The PDF or image (.png, .jpg, ...) to look at, or a link to one.",
            show_default=False,
        ),
        page: int | None = typer.Option(
            None,
            "--page",
            "-p",
            metavar="N",
            show_default=False,
            help="The page to show. Default: the recipe's first page, or page 1.",
        ),
        recipe: Path | None = typer.Option(
            None,
            "--recipe",
            "-r",
            metavar="RECIPE",
            show_default=False,
            help="Settings saved with [cyan]pdfexorcist recipe new[/] (parser, checks, engines).",
        ),
        output: Path | None = typer.Option(
            None,
            "--output",
            "-o",
            metavar="PATH",
            rich_help_panel=OUT_PANEL,
            show_default=False,
            help="File to write (.html, or .png for a static picture) or a folder. "
            f"Default: <name>.p<page>.{kind}.html next to the input.",
        ),
        png: bool = typer.Option(
            False,
            "--png",
            rich_help_panel=OUT_PANEL,
            help="Also write a static annotated PNG next to the HTML.",
        ),
        open_: bool = typer.Option(
            False,
            "--open",
            rich_help_panel=OUT_PANEL,
            help="Open the result in the default browser.",
        ),
        force: Force = False,
        ocr: ShowOcr = False,
        engines: ShowEngines = None,
        min_agree: ShowMinAgree = None,
        jobs: Jobs = 1,
        quiet: Quiet = False,
        debug: Debug = False,
    ) -> None:
        from ._show_cli import ShowOptions, run_show

        with guard(debug):
            setup_logging(debug)
            check_min_agree(min_agree)
            run_show(
                ShowOptions(
                    file=file,
                    page=page,
                    recipe=recipe,
                    engines=engines,
                    ocr=ocr,
                    min_agree=min_agree,
                    jobs=jobs,
                    output=output,
                    png=png,
                    open_=open_,
                    force=force,
                    quiet=quiet,
                    start=start,
                    kind=kind,
                )
            )

    return command


app.command(
    "show",
    help="Draw one page with a box on every cell the vote produced: agreed, unresolved, or "
    "failing a check, plus the text left out. Writes one offline HTML file with three views: "
    "the page, the engines side by side, and a grid of every engine's reading.",
    epilog="[bold]Examples[/]\n\n"
    "  pdfexorcist show report.pdf --page 3            [dim]# writes report.p3.show.html[/]\n\n"
    "  pdfexorcist show report.pdf -p 3 --recipe mccd.toml --open\n\n"
    "  pdfexorcist show photo.jpg --ocr --png          [dim]# also a static PNG[/]\n\n"
    "  pdfexorcist show report.pdf -p 3 -o page3.png   [dim]# only the PNG[/]",
)(_show_command("page", "show"))
app.command(
    "compare",
    help="Compare what each engine reads on one page, side by side: the same file as "
    "[cyan]show[/], opened on its Compare engines view.",
    epilog="[bold]Examples[/]\n\n"
    "  pdfexorcist compare report.pdf --page 3          [dim]# writes report.p3.compare.html[/]\n\n"
    "  pdfexorcist compare scan.pdf -p 2 --ocr --open",
)(_show_command("compare", "compare"))


@app.command(epilog="[bold]Example[/]\n\n  pdfexorcist engines")
def engines(
    as_json: bool = typer.Option(False, "--json", help="Print the table as JSON."),
) -> None:
    """List every engine: installed or not, what it reads, and the exact command to install it."""
    with guard(False, as_json):
        from ._info import show_engines

        show_engines(as_json)


app.command("doctor", hidden=True, help="Same as `pdfexorcist engines`.")(engines)


@app.command(epilog="[bold]Example[/]\n\n  pdfexorcist inspect report.pdf")
def inspect(
    file: str = typer.Argument(
        ...,
        metavar="FILE",
        help="The PDF or image to look at, or a link to one.",
        show_default=False,
    ),
    as_json: bool = typer.Option(False, "--json", help="Print per-page details as JSON."),
    debug: bool = typer.Option(False, "--debug", help="Show full error details."),
) -> None:
    """Look at a file without extracting: text layer or scan, page sizes, and the command to run."""
    from ._info import show_inspect

    with guard(debug, as_json):
        setup_logging(debug)
        show_inspect(file, as_json)


def main(argv: list[str] | None = None, prog_name: str = "pdfexorcist") -> None:
    """Console-script entry point."""
    args = list(sys.argv[1:] if argv is None else argv)
    if (
        args
        and args[0] not in COMMANDS
        and not args[0].startswith("-")
        and (Path(args[0]).suffix or re.match(r"https?://", args[0], re.I))
    ):
        args.insert(0, "extract")
    for stream in (
        sys.stdout,
        sys.stderr,
    ):  # Windows consoles: never crash on a non-ASCII name
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):
                reconfigure(errors="replace")
    app(args=args, prog_name=prog_name)


if __name__ == "__main__":
    main()
