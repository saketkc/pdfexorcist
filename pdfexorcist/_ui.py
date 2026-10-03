"""CLI console, errors and logging."""

import difflib
import json
import logging
import os
import sys
import warnings
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import click
import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from .pages import INPUT_SUFFIXES
from .recipe import RecipeError

out = Console(highlight=False, soft_wrap=False)
err = Console(stderr=True, highlight=False)

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


class CliError(Exception):
    """User-fixable error with guidance and an exit code."""

    def __init__(self, message: str, hint: str = "", code: int = EXIT_USAGE) -> None:
        super().__init__(message)
        self.message, self.hint, self.code = message, hint, code


def refuse_overwrite(paths: Iterable[Path | None], force: bool) -> None:
    """Return an overwrite error for the first existing path unless forced."""
    if force:
        return
    for p in paths:
        if p is not None and p.exists():
            raise CliError(
                f"{path_text(p)} already exists; pdfexorcist never overwrites a file "
                "unless told to.",
                "Add --force to replace it, or choose another name with -o.",
            )


def check_min_agree(n: int | None) -> None:
    """Reject agreement thresholds below one; None selects the default."""
    if n is not None and n < 1:
        raise CliError("--min-agree must be 1 or more.", "Example: --min-agree 3")


def stdin_is_tty() -> bool:
    """Return whether interactive prompts are available."""
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def print_json(data: dict[str, Any]) -> None:
    """Print unformatted JSON to stdout."""
    sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def show_error(message: str, hint: str = "", where: str = "", source: str = "") -> None:
    body = Text()
    if where:
        body.append(where + "\n", style="dim")
    body.append(message)
    if source:
        body.append("\n\n    " + source.strip(), style="yellow")
    if hint:
        body.append("\n\nHow to fix: ", style="bold")
        body.append(hint)
    err.print(
        Panel(
            body,
            title="[bold red]Error[/]",
            title_align="left",
            border_style="red",
            expand=False,
        )
    )


@contextmanager
def guard(debug: bool = False, as_json: bool = False) -> Iterator[None]:
    """Convert exceptions to user messages; show tracebacks only with --debug."""

    def fail(code: int, message: str, hint: str = "", where: str = "", source: str = "") -> None:
        if as_json:
            print_json(
                {
                    "error": message,
                    "hint": hint,
                    "where": where or None,
                    "exit_code": code,
                }
            )
        else:
            show_error(message, hint, where, source)
        raise typer.Exit(code)

    try:
        yield
    except (
        typer.Exit,
        typer.Abort,
        click.exceptions.Exit,
        click.exceptions.Abort,
        click.ClickException,
    ):
        raise
    except CliError as e:
        if debug:
            err.print_exception()
        fail(e.code, e.message, e.hint)
    except RecipeError as e:
        if debug:
            err.print_exception()
        where = f"{e.path}" + (f", line {e.line}" if e.line else "") if e.path else ""
        fail(EXIT_USAGE, e.message, e.hint, where, e.source_line())
    except EOFError:
        fail(
            EXIT_USAGE,
            "The input ended before every question was answered.",
            "Answer the questions in a terminal, or pass --yes and options to run without them.",
        )
    except KeyboardInterrupt:
        err.print("\nStopped.")
        raise typer.Exit(130) from None
    except Exception as e:  # noqa: BLE001 - the last line of defence against tracebacks
        if debug:
            err.print_exception()
        fail(
            EXIT_FAILED,
            f"Unexpected error: {type(e).__name__}: {e}",
            "Run the same command with --debug to see the full details. If it looks like a bug "
            "in pdfexorcist, please report it with that output.",
        )


class NoteCollector(logging.Handler):
    """Collect package warnings for summaries and suppress library chatter."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.notes: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if not record.name.startswith("pdfexorcist"):
            return
        msg = record.getMessage()
        if msg.startswith("skipping "):  # shown in the engines table instead
            return
        if msg not in self.notes:
            self.notes.append(msg)


# libraries whose own handlers log routine work between the progress lines
NOISY = {"paddlex": logging.WARNING, "camelot": logging.ERROR}
# VLM libraries print outside logging; set before they are imported
QUIET_ENV = {
    "TRANSFORMERS_VERBOSITY": "error",
    "TRANSFORMERS_NO_ADVISORY_WARNINGS": "1",
    "HF_HUB_DISABLE_PROGRESS_BARS": "1",
}


class _AtLeast(logging.Filter):
    """Filter records below a level."""

    def __init__(self, level: int) -> None:
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.level


def setup_logging(debug: bool) -> NoteCollector:
    """Quiet third-party output outside debug mode."""
    notes = NoteCollector()
    root = logging.getLogger()
    for h in list(root.handlers):
        if isinstance(h, NoteCollector):
            root.removeHandler(h)
    root.addHandler(notes)
    for name, level in NOISY.items():
        lib = logging.getLogger(name)
        for f in [f for f in lib.filters if isinstance(f, _AtLeast)]:
            lib.removeFilter(f)
        if not debug:
            lib.addFilter(_AtLeast(level))
    if debug:
        from rich.logging import RichHandler

        root.setLevel(logging.INFO)
        root.addHandler(RichHandler(console=err, show_path=False, level=logging.INFO))
    else:
        root.setLevel(logging.WARNING)
        warnings.simplefilter("ignore")
        for key, value in QUIET_ENV.items():
            os.environ.setdefault(key, value)  # a value the user set wins
    return notes


def resolve_input(file: str | Path) -> Path:
    """Resolve a CLI input file or URL."""
    from .fetch import download, is_url

    if is_url(file):
        try:
            file = download(str(file), Path.cwd())
        except (OSError, ValueError) as e:  # URLError and HTTPError are OSErrors
            raise CliError(f"Could not download {file}: {e}", "Check the link in a browser.") from e
        err.print(f"[dim]Reading {path_text(file)} from the link.[/]")
    # Path.expanduser raises on an unknown ~user
    file = Path(os.path.expanduser(file))  # noqa: PTH111
    if file.is_dir():
        found = sorted(p.name for p in file.iterdir() if p.suffix.lower() in INPUT_SUFFIXES)[:5]
        raise CliError(
            f"{file} is a folder, not a file.",
            "Give one file, e.g. "
            + (
                f"pdfexorcist extract {file / found[0]}"
                if found
                else "pdfexorcist extract report.pdf"
            ),
        )
    if not file.exists():
        folder = file.parent if str(file.parent) else Path()
        names = [p.name for p in folder.iterdir()] if folder.is_dir() else []
        near = difflib.get_close_matches(file.name, names, n=3, cutoff=0.6)
        hint = (
            "Did you mean " + " or ".join(str(folder / n) for n in near) + "?"
            if near
            else 'Check the spelling and the folder. Wrap names with spaces in quotes: "my '
            'report.pdf".'
        )
        raise CliError(f"File not found: {file}", hint)
    if file.suffix.lower() not in INPUT_SUFFIXES:
        raise CliError(
            f"{file.name} is not a PDF or an image.",
            "pdfexorcist reads .pdf files and images ("
            + ", ".join(sorted(INPUT_SUFFIXES - {".pdf"}))
            + ").",
        )
    return file


def did_you_mean(word: str, choices: list[str]) -> str:
    near = difflib.get_close_matches(word, choices, n=1)
    return f"Did you mean {near[0]!r}? " if near else ""


def plural(n: int, word: str, many: str | None = None) -> str:
    return f"{n:,} {word if n == 1 else many or word + 's'}"


def path_text(p: Path) -> str:
    """Format paths relative to the current directory when possible."""
    try:
        return str(p.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(p)


def cmd_arg(p: Path) -> str:
    """Quote a path when shell characters or spaces require it."""
    text = path_text(p)
    return f'"{text}"' if any(c in text for c in " '&()[];$!*?<>|#~`") else text


def esc(text: Any) -> str:
    return escape(str(text))
