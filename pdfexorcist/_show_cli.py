"""The show and compare commands."""

import tempfile
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from rich.table import Table

from ._run import EngineProgress, load_recipe, make_plan
from ._ui import CliError, err, esc, path_text, plural, refuse_overwrite, resolve_input


@dataclass(frozen=True)
class ShowOptions:
    file: str
    page: int | None
    recipe: Path | None
    engines: str | None
    ocr: bool
    min_agree: int | None
    jobs: int
    output: Path | None
    png: bool
    open_: bool
    force: bool
    quiet: bool
    start: str  # the view the HTML opens on: "page" (show) or "compare"
    kind: str  # "show" or "compare": names the output


def _paths(src: Path, page: int, o: ShowOptions) -> list[Path]:
    """Files to write: the HTML and/or the PNG."""
    stem = f"{src.stem}.p{page}.{o.kind}"
    out = o.output
    if out is None:
        html = src.with_name(stem + ".html")
    elif out.is_dir() or not out.suffix or str(out).endswith(("/", "\\")):
        html = out / (stem + ".html")
    elif out.suffix.lower() == ".png":
        return [out]
    elif out.suffix.lower() in (".html", ".htm"):
        html = out
    else:
        raise CliError(
            f"-o {out}: show writes .html or .png files.",
            "End the name in .html (the inspector) or .png (a static picture), or give a folder.",
        )
    return [html, html.with_suffix(".png")] if o.png else [html]


def run_show(o: ShowOptions) -> None:
    from .show import inspect_page
    from .show_html import write_html
    from .show_png import write_png

    if o.page is not None and o.page < 1:
        raise CliError("--page must be 1 or more.", "Example: --page 3")
    src = resolve_input(o.file)
    rec = load_recipe(o.recipe)
    with tempfile.TemporaryDirectory() as tmp:  # make_plan's CSV paths are never written
        plan = make_plan(src, rec, Path(tmp), None, None, o.engines, o.ocr, o.min_agree, None, True)
    page = o.page
    notes = list(plan.notes)
    if page is None:
        page = plan.pages[0] if plan.pages else 1
        if plan.n_pages > 1:
            notes.append(f"Showing page {page} of {plan.n_pages}; choose another with --page.")
    if page > plan.n_pages:
        raise CliError(
            f"--page {page}: {src.name} has {plural(plan.n_pages, 'page')}.",
            f"Pick a page from 1 to {plan.n_pages}.",
        )
    outputs = _paths(src, page, o)
    refuse_overwrite(outputs, o.force)
    parse, key = rec.parse_and_key()
    if not o.quiet:
        err.print(
            f"Reading page {page} of [bold]{esc(path_text(src))}[/] with "
            f"{plural(len(plan.methods), 'engine')}"
            + (f", recipe [bold]{esc(path_text(o.recipe))}[/]" if o.recipe else "")
        )
    with EngineProgress(plan.methods, err.is_terminal, o.quiet) as prog:
        try:
            view = inspect_page(
                src,
                page,
                methods=plan.methods,
                parse=parse,
                key=key,
                min_agree=plan.min_agree,
                min_unopposed=rec.min_unopposed,
                families=rec.families,
                normalize=rec.normalizer(),
                checks=rec.check_functions(),
                postprocess=rec.postprocess_function(),
                columns=plan.columns,
                rows=plan.rows,
                on_engine=prog,
                fit_boxes=rec.fit_boxes,
                n_pages=plan.n_pages,
                jobs=o.jobs,
            )
        except RuntimeError as e:
            if "independent readings" not in str(e):
                raise
            raise CliError(
                f"Too few engines read anything from page {page} ({e}).",
                "Check that the page holds a table (pdfexorcist inspect), or add OCR engines with "
                "--ocr.",
                code=1,
            ) from None
    view.notes[:0] = notes
    written = [
        write_png(view, p) if p.suffix.lower() == ".png" else write_html(view, p, o.start)
        for p in outputs
    ]
    if not o.quiet:
        _view_summary(view, written)
    if o.open_:
        webbrowser.open(written[0].resolve().as_uri())


def _view_summary(view, written: list[Path]) -> None:  # type: ignore[no-untyped-def]
    c = view.counts()
    t = Table.grid(padding=(0, 2))
    t.add_column(style="bold")
    t.add_column(justify="right")
    t.add_column()
    t.add_row("Agreed", f"{c['agreed']:,}", "[green]boxed solid[/]")
    t.add_row("Unresolved", f"{c['unresolved']:,}", "[yellow]dashed, dotted fill[/]")
    t.add_row("Failed checks", f"{c['failed']:,}", "[red]thick, hatched[/]")
    t.add_row("Not read as cells", f"{c['skipped']:,}", "[dim]words outlined in grey[/]")
    err.print()
    err.print(t)
    for note in view.notes:
        err.print(f"[yellow]Note:[/] {esc(note)}", soft_wrap=True)
    for p in written:
        err.print(f"Wrote [bold]{esc(path_text(p))}[/]", soft_wrap=True)
    if written[0].suffix.lower() == ".html":
        err.print("[dim]Open it in a browser (or add --open); it works offline.[/]")
