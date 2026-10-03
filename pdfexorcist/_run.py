"""Plan and run an extraction."""

import importlib.util
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from . import doctor
from . import recipe as recipes
from ._progress import EngineProgress as EngineProgress  # used via _run by callers
from ._ui import EXIT_FAILED, CliError, cmd_arg, plural, refuse_overwrite
from .checks import validate
from .extractors import DEFAULTS, EXTRACTORS
from .pages import IMAGE_SUFFIXES, ocr_layer, page_kinds
from .recipe import Recipe, page_list
from .vote import _pages, extract

EXT = {"csv": ".csv", "xlsx": ".xlsx", "parquet": ".parquet", "json": ".json"}
FORMAT_DEPS = {"xlsx": [("openpyxl",)], "parquet": [("pyarrow",), ("fastparquet",)]}


@dataclass
class Plan:
    """Resolved extraction settings before engines start."""

    src: Path
    is_image: bool
    n_pages: int
    pages: list[int] | None
    methods: list[str]
    min_agree: int | None
    fmt: str
    layout: str
    columns: str
    rows: list[str] | None
    output: Path
    review: Path | None
    notes: list[str] = field(default_factory=list)
    not_installed: dict[str, str] = field(default_factory=dict)


def load_recipe(path: Path | None) -> Recipe:
    """Load the selected recipe before extraction."""
    if path is None:
        return Recipe()
    rec = recipes.load(path)
    rec.resolve_all()
    return rec


def _page_count(src: Path, is_image: bool) -> int:
    if is_image:
        return 1
    import pymupdf

    try:
        with pymupdf.open(src) as doc:
            if doc.needs_pass:
                raise CliError(
                    f"{src.name} is password-protected.",
                    "Open it in a PDF viewer and save an unprotected copy, then run on that copy.",
                )
            return doc.page_count
    except CliError:
        raise
    except Exception as e:  # pymupdf raises its own error types for broken files
        raise CliError(
            f"Could not open {src.name} as a PDF: {e}",
            "Check that the file is a complete, valid PDF.",
        ) from e


def _engines(text: str | None) -> list[str] | None:
    if not text:
        return None
    names = [n.strip() for n in text.replace(" ", ",").split(",") if n.strip()]
    for n in names:
        if n not in EXTRACTORS:
            from ._ui import did_you_mean

            raise CliError(
                f"Unknown engine {n!r}.",
                did_you_mean(n, list(EXTRACTORS))
                + "Engines: "
                + ", ".join(EXTRACTORS)
                + " (see: pdfexorcist engines)",
            )
    return names


def _paths(
    src: Path, output: Path | None, fmt: str | None, layout: str
) -> tuple[Path, str, Path | None]:
    """Return main output, format, and optional review path."""
    folder: Path | None = None
    if output is not None:
        suffix = output.suffix.lower().lstrip(".")
        if output.is_dir() or not suffix or str(output).endswith(("/", "\\")):
            folder = output
        elif suffix not in EXT:
            raise CliError(
                f"-o {output}: pdfexorcist cannot write .{suffix} files.",
                "End the name in .csv, .xlsx, .parquet or .json, or give a folder.",
            )
        elif fmt and fmt != suffix:
            raise CliError(
                f"-o {output} ends in .{suffix} but --format is {fmt}.",
                f"Use -o {output.with_suffix(EXT[fmt])} or drop --format.",
            )
        else:
            fmt = suffix
    fmt = fmt or "csv"
    if output is None:
        main = src.with_suffix(EXT[fmt])
    elif folder is not None:
        main = folder / (src.stem + EXT[fmt])
    else:
        main = output
    review = (
        main.with_name(main.stem + ".review" + main.suffix)
        if layout == "table" and fmt != "xlsx"
        else None
    )
    return main, fmt, review


def make_plan(
    file: Path,
    rec: Recipe,
    output: Path | None,
    fmt: str | None,
    pages_opt: str | None,
    engines_opt: str | None,
    ocr_opt: bool,
    min_agree_opt: int | None,
    layout_opt: str | None,
    force: bool,
    *,
    kinds: dict[int, dict] | None = None,
) -> Plan:
    """Resolve a run plan; kinds maps known page metadata by page."""
    src = file
    is_image = src.suffix.lower() in IMAGE_SUFFIXES
    n_pages = _page_count(src, is_image)
    notes: list[str] = []

    if is_image and pages_opt and pages_opt.strip() not in ("1", "1-1"):
        raise CliError("An image has only one page.", "Leave out --pages for images.")
    try:
        pages = None if is_image else page_list(rec, src, n_pages, pages_opt)
    except ValueError as e:
        raise CliError(
            f"--pages: {e}.",
            f'Pages are numbers like 3, 1-5 or "2,4,10-"; {src.name} has '
            f"{plural(n_pages, 'page')}.",
        ) from None
    if pages == []:
        raise CliError(
            "No page matched the recipe's page text.",
            f"The recipe looks for start={rec.start!r} match={rec.match!r}. Check the patterns "
            "with "
            f"pdfexorcist inspect {src.name}, or pick pages with --pages.",
            code=EXIT_FAILED,
        )
    if pages == list(range(1, n_pages + 1)):
        pages = None

    explicit = _engines(engines_opt) or (list(rec.engines) if rec.engines else None)
    ocr = ocr_opt or rec.ocr
    status = {n: doctor.status(n) for n in EXTRACTORS}
    ocr_ok = doctor.installed_ocr()
    scanned = False
    if not is_image:
        read = list(pages or range(1, n_pages + 1))
        if kinds is None or any(p not in kinds for p in read):
            kinds = {k["page"]: k for k in page_kinds(src, read)}
        chosen = [kinds[p] for p in read]
        scanned = all(k["chars"] < 20 for k in chosen) and any(k["scan"] for k in chosen)
        if not ocr and not explicit and not rec.families and ocr_layer(src):
            raise CliError(
                "This PDF's text layer was made by OCR (ocrmypdf), so the text engines all repeat "
                "that "
                "one reading and count as a single vote.",
                f"Add independent OCR engines: pdfexorcist extract {cmd_arg(src)} --ocr",
            )

    ocr_only = False
    if explicit:
        # a named list is used as is; only the --ocr flag adds the OCR engines to it
        methods = explicit + ([m for m in ocr_ok if m not in explicit] if ocr_opt else [])
    elif is_image or scanned:
        if not ocr:
            if scanned:
                raise CliError(
                    "These pages are scanned images without a text layer, so the text engines "
                    "would find nothing.",
                    f"Read them with OCR engines: pdfexorcist extract {cmd_arg(src)} --ocr",
                )
            notes.append("An image can only be read by OCR engines, so --ocr is on.")
        methods, ocr_only = list(ocr_ok), True
    else:
        methods = [m for m in DEFAULTS if status[m].installed] + (ocr_ok if ocr else [])
    if (ocr_only or ocr) and not ocr_ok:
        raise CliError(
            "No OCR engine is installed, and "
            + ("images" if is_image else "scanned pages")
            + " need one."
            if (is_image or scanned)
            else "--ocr was given, but no OCR engine is installed.",
            "See which ones you can install, with the exact command: pdfexorcist engines",
            code=EXIT_FAILED,
        )
    not_installed = {
        m: status[m].fix
        for m in (explicit or (DEFAULTS if not ocr_only else []))
        if not status[m].installed
    }
    runnable = [m for m in methods if status[m].installed]
    ocr_only = bool(runnable) and all(m in doctor.OCR_ENGINES for m in runnable)

    min_agree = min_agree_opt or rec.min_agree
    if min_agree is None and ocr_only:
        if len(runnable) < 2:
            raise CliError(
                f"Only one OCR engine ({runnable[0]}) can run here; a vote needs at least two "
                "independent readings.",
                "Install another OCR engine; pdfexorcist engines shows how.",
                code=EXIT_FAILED,
            )
        min_agree = max(2, len(runnable) // 2 + 1)
    need = min_agree or (2 if rec.families else 3)
    if len(runnable) < need:
        raise CliError(
            f"Only {plural(len(runnable), 'engine')} can run here "
            f"({', '.join(runnable) or 'none'}), "
            f"but a value needs {need} agreeing readings.",
            "Install more engines (pdfexorcist engines shows how), or choose them with --engines.",
            code=EXIT_FAILED,
        )
    if min_agree is not None and min_agree < 2:
        notes.append(
            "--min-agree 1 keeps values that a single engine read: nothing is cross-checked."
        )

    layout = layout_opt or rec.layout or "table"
    main, fmt_final, review = _paths(src, output, fmt or (None if output else rec.format), layout)
    for mod_sets in FORMAT_DEPS.get(fmt_final, []):
        if all(importlib.util.find_spec(m) for m in mod_sets):
            break
    else:
        if fmt_final in FORMAT_DEPS:
            need_mod = FORMAT_DEPS[fmt_final][0][0]
            raise CliError(
                f"Writing {fmt_final} needs the {need_mod} package.",
                f"pip install {need_mod}   (or use --format csv)",
            )
    refuse_overwrite((main, review), force)
    return Plan(
        src,
        is_image,
        n_pages,
        pages,
        runnable,
        min_agree,
        fmt_final,
        layout,
        rec.columns or "col",
        list(rec.rows) if rec.rows else None,
        main,
        review,
        notes,
        not_installed,
    )


def run(
    plan: Plan, rec: Recipe, progress: Callable[[str, str, Any], None], jobs: int = 1
) -> tuple[pd.DataFrame, list[str]]:
    """Vote, post-process, and check; return cells and key columns."""
    parse, key = rec.parse_and_key()
    normalize = rec.normalizer()
    checks = rec.check_functions()
    post = rec.postprocess_function()
    with tempfile.TemporaryDirectory() as tmp:
        pdf = _pages(plan.src, plan.pages, Path(tmp)) if plan.pages else plan.src
        try:
            res = extract(
                pdf,
                plan.methods,
                parse=parse,
                key=key,
                min_agree=plan.min_agree,
                min_unopposed=rec.min_unopposed,
                families=rec.families,
                normalize=normalize,
                on_engine=progress,
                fit_boxes=rec.fit_boxes,
                jobs=jobs,
            )
        except RuntimeError as e:
            if "independent readings" not in str(e):
                raise
            raise CliError(
                f"Too few engines read anything from these pages ({e}).",
                "Check that the pages hold a table (pdfexorcist inspect), pick pages with --pages, "
                "or add OCR engines with --ocr for scans.",
                code=EXIT_FAILED,
            ) from None
        if post is not None:
            res = post(res, pdf)
            if not isinstance(res, pd.DataFrame):
                raise CliError(
                    f"The postprocess function {rec.postprocess} must return a DataFrame, not "
                    f"{type(res).__name__}.",
                    code=EXIT_FAILED,
                )
    if checks:
        ok = res.status == "verified"
        res["failed"] = validate(res[ok], checks)["failed"].reindex(res.index, fill_value="")
    res.attrs["checks_run"] = [c.__name__ for c in checks]
    if plan.pages and "page" in res.columns:
        orig = dict(enumerate(plan.pages, start=1))
        res["page"] = [orig.get(int(p), p) if str(p).isdigit() else p for p in res.page]
    return res, key
