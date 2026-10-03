"""The engines and inspect commands."""

from typing import Any

from rich.table import Table

from . import doctor
from ._ui import (
    CliError,
    cmd_arg,
    esc,
    out,
    path_text,
    plural,
    print_json,
    resolve_input,
)


def show_engines(as_json: bool) -> None:
    """The engines table: installed or not, and the exact install commands."""
    rows = doctor.all_status()
    if as_json:
        print_json({"engines": [r.__dict__ for r in rows]})
        return
    t = Table(title="Engines", title_justify="left", header_style="bold")
    t.add_column("Engine", style="bold", no_wrap=True)
    t.add_column("Installed", no_wrap=True)
    t.add_column("Used", no_wrap=True)
    t.add_column("Reads", no_wrap=True)
    t.add_column("What it is")
    for r in rows:
        used = "default" if r.default else "--ocr" if r.reads.startswith("pixels") else "--engines"
        t.add_row(
            r.name,
            "[green]yes[/]" if r.installed else "[red]no[/]",
            used,
            r.reads,
            esc(r.about)
            + (
                f" [dim]({esc(r.fix.removeprefix('not available: '))})[/]"
                if r.fix.startswith("not available: ")
                else ""
            ),
        )
    out.print(t)
    out.print(
        "[dim]Used: default = always; --ocr = with extract --ocr; --engines = when named, "
        "e.g. --engines pdfplumber,tabula.[/]"
    )
    missing = [r for r in rows if not r.installed and not r.fix.startswith("not available")]
    if missing:
        out.print("\n[bold]To install the missing engines[/] (copy and paste):")
        for r in missing:
            out.print(f"  [dim]{r.name}:[/] [cyan]{esc(r.fix)}[/]", soft_wrap=True)
    n_text = sum(r.installed and r.default for r in rows)
    n_ocr = len(doctor.installed_ocr())
    out.print(
        f"\n{plural(n_text, 'default engine')} ready: text PDFs need at least 3. "
        f"{plural(n_ocr, 'OCR engine')} ready: scans and photos need at least 2."
    )


def _paper_size(w: float, h: float) -> str:
    sizes = {
        "A4": (595, 842),
        "Letter": (612, 792),
        "Legal": (612, 1008),
        "A3": (842, 1191),
    }
    for name, (a, b) in sizes.items():
        if abs(min(w, h) - a) < 6 and abs(max(w, h) - b) < 6:
            return f"{name} {'landscape' if w > h else 'portrait'}"
    return f"{w / 72 * 25.4:.0f} x {h / 72 * 25.4:.0f} mm"


def _page_kind(k: dict[str, Any]) -> str:
    if k["chars"] >= 20:
        return "scan + text layer" if k["scan"] else "text"
    return "scan, no text" if k["scan"] else "blank or drawing"


def show_inspect(file: str, as_json: bool) -> None:
    """The inspect report: per page text or scan, size, and the command to run."""
    from .pages import IMAGE_SUFFIXES, ocr_layer, page_kinds

    src = resolve_input(file)
    name = path_text(src)
    if src.suffix.lower() in IMAGE_SUFFIXES:
        import pymupdf

        try:
            pix = pymupdf.Pixmap(str(src))
        except Exception as e:  # unreadable image
            raise CliError(f"Could not open {src.name} as an image: {e}") from e
        advice = f"pdfexorcist extract {cmd_arg(src)} --ocr"
        if as_json:
            print_json(
                {
                    "file": str(src),
                    "kind": "image",
                    "width_px": pix.width,
                    "height_px": pix.height,
                    "suggested": advice,
                }
            )
            return
        out.print(f"[bold]{esc(name)}[/]: an image, {pix.width} x {pix.height} pixels.")
        out.print("Only OCR engines can read it.\n")
        out.print(f"Run: [bold cyan]{esc(advice)}[/]", soft_wrap=True)
        return
    from ._run import _page_count

    _page_count(src, False)  # friendly error for broken or protected files
    kinds = page_kinds(src)
    made_by_ocr = ocr_layer(src)
    text = sum(_page_kind(k) == "text" for k in kinds)
    scans = sum(k["scan"] for k in kinds)
    if made_by_ocr or (scans and scans >= len(kinds) / 2):
        advice, why = (
            f"pdfexorcist extract {cmd_arg(src)} --ocr",
            (
                "Its text layer came from OCR, so the text engines would all repeat one OCR's "
                "misreads."
                if made_by_ocr or any(_page_kind(k) == "scan + text layer" for k in kinds)
                else "The pages are scanned images: only OCR engines can read them."
            ),
        )
    elif text:
        advice, why = (
            f"pdfexorcist extract {cmd_arg(src)}",
            "It has a text layer, which the default engines read fast and exactly.",
        )
    else:
        advice, why = (
            "",
            "No page has text or a scanned image; there may be no table to read.",
        )
    if as_json:
        print_json(
            {
                "file": str(src),
                "pages": kinds,
                "ocr_layer": made_by_ocr,
                "suggested": advice or None,
            }
        )
        return
    t = Table(header_style="bold", show_edge=False)
    t.add_column("Pages")
    t.add_column("Content")
    t.add_column("Characters", justify="right")
    t.add_column("Size")
    groups: list[list[Any]] = []
    for k in kinds:
        sig = (_page_kind(k), _paper_size(k["width"], k["height"]))
        if groups and groups[-1][0] == sig and groups[-1][2] == k["page"] - 1:
            groups[-1][2] = k["page"]
            groups[-1][3] += k["chars"]
        else:
            groups.append([sig, k["page"], k["page"], k["chars"]])
    for (kind, size), a, b, chars in groups:
        t.add_row(str(a) if a == b else f"{a}-{b}", kind, f"{chars:,}", size)
    out.print(
        f"[bold]{esc(name)}[/]: {plural(len(kinds), 'page')}"
        + (", text layer made by ocrmypdf" if made_by_ocr else "")
    )
    out.print(t)
    out.print(f"\n{why}")
    if advice:
        out.print(f"Run: [bold cyan]{esc(advice)}[/]", soft_wrap=True)
        if len(kinds) > 1:
            out.print(
                "[dim]Add --pages (e.g. --pages 3-5) to read only the pages with your table.[/]"
            )
