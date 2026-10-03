"""Recipe wizard."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from rich.panel import Panel
from rich.table import Table

from . import recipe as recipes
from ._run import _page_count
from ._ui import (
    CliError,
    cmd_arg,
    err,
    esc,
    out,
    path_text,
    plural,
    refuse_overwrite,
    resolve_input,
    stdin_is_tty,
)
from ._wizard_ask import Asker, _ask_checks, _check_preview, _clean_changes, _preview, _samples
from ._wizard_toml import CLEAN, Answers, parse_total, render
from .pages import IMAGE_SUFFIXES, page_kinds, parse_pages

__all__ = ["WizardOptions", "new_recipe"]


@dataclass
class WizardOptions:
    """Supplied wizard answers; None prompts or selects the --yes default."""

    sample: str | None = None
    output: Path | None = None
    name: str | None = None
    pages: str | None = None
    page_text: str | None = None
    parser: str | None = None
    min_values: int | None = None
    clean: str | None = None
    totals: list[str] = field(default_factory=list)
    ocr: bool | None = None
    engines: str | None = None
    min_agree: int | None = None
    yes: bool = False
    preview: bool = True
    force: bool = False


def new_recipe(o: WizardOptions) -> None:
    interactive = not o.yes and stdin_is_tty()
    ask = Asker(interactive)
    if not interactive and not o.yes:
        err.print(
            "[dim]Not a terminal, so asking nothing: using the options given and defaults (as "
            "with --yes).[/]"
        )
    if o.sample is None:
        if not interactive:
            raise CliError(
                "Which file is the recipe for? Give a sample PDF or image.",
                "pdfexorcist recipe new report.pdf --yes",
            )
        o.sample = ask.text("Which PDF or image has the table? (path or link)")
    src = resolve_input(o.sample)
    is_image = src.suffix.lower() in IMAGE_SUFFIXES
    n_pages = _page_count(src, is_image)
    if interactive:
        out.print(
            Panel(
                f"New recipe for [bold]{esc(path_text(src))}[/] ({plural(n_pages, 'page')}).\n"
                "Answer a few questions; press Enter to take the suggestion in (brackets).\n"
                "Nothing is saved until the end, and you can edit the file afterwards.",
                border_style="cyan",
            )
        )
    a = Answers(sample=path_text(src))

    if is_image:
        pages = [1]
    else:
        spec = o.pages
        asked: list[int] | None = None
        if spec is None and o.page_text is None:
            spec, asked = _ask_page_range(ask, interactive, src, n_pages)
            if spec is None:
                o.page_text = (
                    ask.text(
                        "Only pages whose text contains... (a word or regex; Enter for every page)",
                        "",
                    )
                    or None
                )
        try:
            pages = asked or (parse_pages(spec, n_pages) if spec else list(range(1, n_pages + 1)))
        except ValueError as e:
            raise CliError(f"--pages: {e}.", f"{src.name} has {plural(n_pages, 'page')}.") from None
        a.select = spec
        if o.page_text:
            from .pages import pages_matching

            try:
                pages = pages_matching(src, match=o.page_text, within=pages)
            except re.error as e:
                raise CliError(f"--page-text is not a valid regular expression: {e}.") from None
            if not pages:
                raise CliError(
                    f"No page's text matches {o.page_text!r}.",
                    f"Look at the pages with: pdfexorcist inspect {cmd_arg(src)}",
                )
            a.match = o.page_text

    kinds = {} if is_image else {k["page"]: k for k in page_kinds(src, pages)}
    scanned = is_image or all(kinds[p]["chars"] < 20 for p in pages)
    a.ocr = (
        True
        if is_image
        else (
            o.ocr
            if o.ocr is not None
            else ask.yes("Is this a scan or a photo (read it with OCR engines)?", scanned)
        )
    )
    a.engines = [e.strip() for e in o.engines.split(",") if e.strip()] if o.engines else None
    a.min_agree = o.min_agree

    lines = [] if (a.ocr or scanned) else _samples(src, pages[0])
    if interactive and lines:
        t = Table(show_edge=False)
        out.print(f"\n[bold]How page {pages[0]} reads[/] (the first lines with numbers):")
        t.add_column("Label")
        t.add_column("Values")
        for label, vals in lines:
            t.add_row(
                esc(label[:40]),
                esc("  ".join(vals[:12]) + (" ..." if len(vals) > 12 else "")),
            )
        out.print(t)

    if o.parser is not None and o.parser not in ("rows", "columns"):
        raise CliError(
            f"--parser {o.parser!r} is not rows or columns.",
            'For your own Python parser, write the recipe and set type = "custom".',
        )
    if o.parser is None and interactive:
        out.print(
            "\n[bold]rows[/]: each line is a label and then its values, in order (most text "
            "PDFs).\n"
            "[bold]columns[/]: each value goes to the column it sits under; best for scans, "
            "photos and "
            "tables with blank cells."
        )
    a.parser = o.parser or ask.choice(
        "How should values be placed?",
        ["rows", "columns"],
        "columns" if a.ocr else "rows",
    )
    a.min_values = o.min_values or ask.number(
        "Skip lines with fewer than how many values? (titles, footnotes)", 2
    )

    found = _clean_changes(lines)
    if o.clean is not None:
        names = [c.strip() for c in o.clean.split(",") if c.strip()]
        bad = [n for n in names if n not in CLEAN]
        if bad:
            raise CliError(f"--clean {bad[0]!r} is not one of {', '.join(CLEAN)}.")
        a.clean = {n: n in names for n in CLEAN}
    else:
        a.clean = {
            n: ask.yes(
                f"Values like {CLEAN[n][1].split(' -> ')[0]} were seen: clean them "
                f"({CLEAN[n][1]})?",
                True,
            )
            if found[n]
            else False
            for n in CLEAN
        }
    a.checks = [parse_total(t) for t in o.totals]

    a.name = o.name or ask.text("A short name for this recipe", src.stem.replace("_", " "))
    output = o.output or Path(f"{src.stem}.recipe.toml")
    if output.suffix.lower() != ".toml":
        output = output.with_name(output.name + ".toml")
    # like a recipe's .py files, the sample is named relative to the recipe
    try:
        a.sample = Path(os.path.relpath(src.resolve(), output.resolve().parent)).as_posix()
    except ValueError:  # Windows: on another drive
        a.sample = src.resolve().as_posix()

    res = None
    if o.preview:
        res = _preview(a, src, pages, output, kinds)
        if res is not None and interactive and not o.totals:
            _ask_checks(a, ask, res)
        if res is not None and a.checks:
            _check_preview(a, res, output)

    replace = (
        o.force
        or not output.exists()
        or (interactive and ask.yes(f"{path_text(output)} exists. Replace it?", False))
    )
    refuse_overwrite([output], replace)
    if interactive and not ask.yes(f"Save the recipe to {path_text(output)}?", True):
        out.print("Not saved.")
        return
    text = render(a, output.name)
    recipes.loads(text, output.resolve())  # never write a recipe that would not load
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    out.print(f"\n[green]Saved[/] [bold]{esc(path_text(output))}[/]. Next:")
    out.print(
        f"  run it:      [cyan]pdfexorcist extract {esc(cmd_arg(src))} --recipe "
        f"{esc(cmd_arg(output))}[/]"
    )
    out.print(f"  read it:     [cyan]pdfexorcist recipe show {esc(cmd_arg(output))}[/]")
    out.print("  edit it in any text editor; every line is commented.")


def _ask_page_range(
    ask: Asker, interactive: bool, src: Path, n_pages: int
) -> tuple[str | None, list[int]]:
    """Prompt until a page range parses."""
    while True:
        spec = ask.text("Which pages hold the table? (e.g. 3-5)", "all")
        if spec.lower() == "all":
            return None, list(range(1, n_pages + 1))
        try:
            return spec, parse_pages(spec, n_pages)
        except ValueError as e:
            if not interactive:
                raise
            out.print(f"[red]{esc(e)}[/] ({src.name} has {plural(n_pages, 'page')})")
