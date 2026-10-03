"""Read, vote and check."""

import logging
import tempfile
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any, Literal, overload

import pandas as pd

from ._registry import IN_PROCESS
from .checks import Check, validate
from .extractors import DEFAULTS, EXTRACTORS
from .pages import IMAGE_SUFFIXES, ocr_layer
from .readings import Readings
from .rows import KEY, Page, parse_rows

logger = logging.getLogger(__name__)

Parser = Callable[[Iterable[Page]], Iterator[dict]]


def _family(families: dict[str, list[str]]) -> Callable[[str], str]:
    """Map each engine to its family or itself."""
    family = {m: f for f, ms in families.items() for m in ms}
    return lambda m: family.get(m, m)


def _family_vote(df: pd.DataFrame, key: list[str], families: dict[str, list[str]]) -> pd.DataFrame:
    """Replace each family with its unambiguous vote."""
    df = df.assign(method=df.method.map(_family(families)))
    n = df.groupby([*key, "method", "value"], sort=False).size().rename("n").reset_index()
    top = n[n.n == n.groupby([*key, "method"]).n.transform("max")]
    top = top[top.groupby([*key, "method"]).value.transform("size") == 1]
    first = df.drop_duplicates([*key, "method", "value"])
    return top[[*key, "method", "value"]].merge(first, on=[*key, "method", "value"])


def vote(
    readings: pd.DataFrame,
    key: Sequence[str] = KEY,
    min_agree: int | None = None,
    min_unopposed: int | None = None,
    families: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """One row per key from one row per (method, key..., value) reading.

    A value wins when at least min_agree methods read it and no other value ties
    it. A method that reads two values for one cell loses its vote there; extra
    columns take their most common reading.

    Args:
        readings: One row per reading, with a method column.
        key: Columns that name a cell.
        min_agree: Methods that must agree; default a strict majority, at least 3.
        min_unopposed: Also accept a value this many methods read when none read another.
        families: Methods that are not independent; each family settles on its own
            majority, then votes once (min_agree then defaults to a majority of
            families, at least 2).
    """
    key = list(key)
    df = readings.astype({"value": str}).drop_duplicates([*key, "method", "value"])
    ambiguous = df.duplicated([*key, "method"], keep=False)
    if ambiguous.any():
        logger.warning("%d self-contradicting readings dropped", ambiguous.sum())
    df = df[~ambiguous]
    if families:
        df = _family_vote(df, key, families)
    methods = sorted(df["method"].unique())
    if min_agree is None:
        min_agree = max(2 if families else 3, len(methods) // 2 + 1)
    extra = [c for c in df.columns if c not in (*key, "method", "value")]
    rows = []
    for k, g in df.groupby(key, sort=False):
        votes = Counter(g["value"])
        best, n = votes.most_common(1)[0]
        ok = (n >= min_agree and list(votes.values()).count(n) == 1) or (
            min_unopposed is not None and n >= min_unopposed and len(votes) == 1
        )
        by_method = dict(zip(g["method"], g["value"], strict=True))
        rows.append(
            {
                **dict(zip(key, k, strict=True)),
                **{c: _mode(g[c]) for c in extra},
                "value": best if ok else "",
                "n_agree": n,
                "votes": " | ".join(f"{v}×{c}" for v, c in votes.most_common()),
                "sources": "|".join(m for m in methods if by_method.get(m) == best),
                "dissent": "|".join(
                    f"{m}={by_method.get(m, '<missing>')}"
                    for m in methods
                    if by_method.get(m) != best
                ),
                "status": "verified" if ok else "unresolved",
            }
        )
    return pd.DataFrame(rows)


def _mode(s: pd.Series) -> Any:
    """Return the most common non-empty value."""
    m = s.mode()
    return m.iat[0] if len(m) else None


def fit_page_boxes(pdf: Path, out_dir: Path) -> Path:
    """Copy of pdf whose page boxes cover all their text, or pdf itself.

    Poppler and MuPDF clip text drawn outside a page box; pdfminer and PDFium read
    it, so without this the engines would read different tables.
    """
    import pymupdf

    with pymupdf.open(pdf) as doc:  # closed on exit: Windows cannot delete an open file
        return _fit_boxes(doc, pdf, out_dir)


def _fit_boxes(doc: Any, pdf: Path, out_dir: Path) -> Path:
    import pymupdf

    grown = 0
    for page in doc:
        big = pymupdf.Rect(-1e4, -1e4, 1e4, 1e4)
        words = page.get_textpage(clip=big).extractWORDS()
        if not words:
            continue
        # words are in page space (y down, origin top-left); boxes are set in PDF space (y up)
        box = pymupdf.Rect(page.cropbox)
        for w in words:
            box |= pymupdf.Rect(w[:4]) * page.derotation_matrix
        if box != page.cropbox:
            # set_mediabox also resets the CropBox (which MuPDF clips to) to the new MediaBox
            page.set_mediabox(box * ~page.transformation_matrix)
            grown += 1
    if not grown:
        return Path(pdf)
    logger.info("%d pages had text outside their box; boxes grown", grown)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out = Path(out_dir) / Path(pdf).name
    doc.save(out, no_new_id=True)  # stable bytes: older OCR caches are keyed on them
    return out


TEXT_ENGINES = ["pdftotext", "pdfplumber", "pymupdf", "pdfium", "camelot"]


def _pages(pdf: Path, pages: Sequence[int], out_dir: Path) -> Path:
    """Copy selected pages into a new PDF."""
    import pymupdf

    path = Path(out_dir) / f"pages_{Path(pdf).name}"
    with pymupdf.open(pdf) as src, pymupdf.open() as out:
        for p in pages:
            out.insert_pdf(src, from_page=p - 1, to_page=p - 1)
        out.save(path, no_new_id=True)  # stable bytes: older OCR caches are keyed on them
    return path


def _photo_pdf(img: Path, out_dir: Path) -> Path:
    """Wrap an image in a one-page PDF."""
    import pymupdf

    path = Path(out_dir) / f"{Path(img).stem}.pdf"
    with pymupdf.open(img) as doc:
        path.write_bytes(doc.convert_to_pdf())
    return path


_POOLS: dict[int, Any] = {}  # spawned workers import pdfexorcist once per session, not per call


def _pool(workers: int) -> Any:
    """Return a process pool retained until exit."""
    if workers not in _POOLS:
        import atexit
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor

        ctx = multiprocessing.get_context("spawn")  # fork is unsafe with threads and GPU state
        _POOLS[workers] = ProcessPoolExecutor(max_workers=workers, mp_context=ctx)
        atexit.register(_POOLS[workers].shutdown)
    return _POOLS[workers]


def _read_all(
    names: list[str],
    pdf: Path,
    workers: int,
    report: Callable[[str, str, object], None],
    tmp: Path,
) -> dict[str, list | Exception]:
    """Read every engine; retain failures as exception values."""
    import pymupdf

    known = [n for n in names if n in EXTRACTORS]
    pooled = [
        n
        for n in known
        if n not in IN_PROCESS and EXTRACTORS[n].__module__.startswith("pdfexorcist.")
    ]
    with pymupdf.open(pdf) as doc:
        n_pages = doc.page_count
    size = -(-n_pages // max(1, min(workers, n_pages)))  # pages per chunk, rounded up
    chunks = {1: pdf} if size >= n_pages else _chunks(pdf, n_pages, size, tmp)
    tasks = [(n, first) for n in pooled for first in chunks]
    here = [n for n in known if n not in pooled]
    local = [tasks.pop()] if tasks and not here else []  # this process reads one rather than wait
    for n in known:
        report(n, "start", None)
    parts = _read_tasks(tasks, chunks, workers)
    parts |= {(n, first): _read_local(n, chunks[first]) for n, first in local}
    out: dict[str, list | Exception] = {n: _read_local(n, pdf) for n in here}
    for n in pooled:
        got = [parts[(n, first)] for first in chunks]
        failed = next((g for g in got if isinstance(g, Exception)), None)
        out[n] = failed or [
            (first + page - 1, lines)  # back to the page numbers of the whole file
            for first, pages in zip(chunks, got, strict=True)
            for page, lines in pages  # type: ignore[union-attr]
        ]
    return out


def _chunks(pdf: Path, n_pages: int, size: int, tmp: Path) -> dict[int, Path]:
    """Split a PDF into numbered page chunks."""
    out = {}
    for first in range(1, n_pages + 1, size):
        folder = tmp / f"chunk{first}"
        folder.mkdir(parents=True, exist_ok=True)
        out[first] = _pages(pdf, range(first, min(first + size, n_pages + 1)), folder)
    return out


def _read_tasks(
    tasks: list[tuple[str, int]], chunks: dict[int, Path], workers: int
) -> dict[tuple[str, int], list | Exception]:
    """Read engine chunks in the process pool."""
    from concurrent.futures import as_completed
    from concurrent.futures.process import BrokenProcessPool

    # absolute: a pool's workers keep the directory they started in
    futures = {_pool(workers).submit(_read, n, chunks[f].resolve()): (n, f) for n, f in tasks}
    out: dict[tuple[str, int], list | Exception] = {}
    for fut in as_completed(futures):
        n, f = futures[fut]
        e = fut.exception()
        if isinstance(e, BrokenProcessPool):  # a worker could not start or died: read here
            if _POOLS.pop(workers, None):
                logger.warning("worker processes failed (%s); reading in this process", e)
            out[(n, f)] = _read_local(n, chunks[f])
        else:
            out[(n, f)] = e if isinstance(e, Exception) else fut.result()
    return out


def _read_local(name: str, pdf: Path) -> list | Exception:
    """Return one engine's pages or its exception."""
    try:
        return _read(name, pdf)
    except Exception as e:  # noqa: BLE001 - reported with the other engines
        return e


def _read(name: str, pdf: Path) -> list:
    """Read one engine's pages."""
    return list(EXTRACTORS[name](pdf))


@overload
def extract(
    pdf: Path | str,
    methods: list[str] | None = ...,
    parse: Parser = ...,
    key: Sequence[str] = ...,
    min_agree: int | None = ...,
    checks: Sequence[Check] = ...,
    min_unopposed: int | None = ...,
    families: dict[str, list[str]] | None = ...,
    normalize: Callable[[str], str | None] | None = ...,
    pages: Sequence[int] | None = ...,
    on_engine: Callable[[str, str, object], None] | None = ...,
    fit_boxes: bool = ...,
    return_readings: Literal[False] = ...,
    jobs: int = ...,
) -> pd.DataFrame: ...


@overload
def extract(
    pdf: Path | str,
    methods: list[str] | None = ...,
    parse: Parser = ...,
    key: Sequence[str] = ...,
    min_agree: int | None = ...,
    checks: Sequence[Check] = ...,
    min_unopposed: int | None = ...,
    families: dict[str, list[str]] | None = ...,
    normalize: Callable[[str], str | None] | None = ...,
    pages: Sequence[int] | None = ...,
    on_engine: Callable[[str, str, object], None] | None = ...,
    fit_boxes: bool = ...,
    *,
    return_readings: Literal[True],
    jobs: int = ...,
) -> tuple[pd.DataFrame, Readings]: ...


def extract(
    pdf: Path | str,
    methods: list[str] | None = None,
    parse: Parser = parse_rows,
    key: Sequence[str] = KEY,
    min_agree: int | None = None,
    checks: Sequence[Check] = (),
    min_unopposed: int | None = None,
    families: dict[str, list[str]] | None = None,
    normalize: Callable[[str], str | None] | None = None,
    pages: Sequence[int] | None = None,
    on_engine: Callable[[str, str, object], None] | None = None,
    fit_boxes: bool = True,
    return_readings: bool = False,
    jobs: int = 1,
) -> pd.DataFrame | tuple[pd.DataFrame, Readings]:
    """Read pdf with each engine, parse, vote and check.

    Args:
        pdf: A PDF, an image (.png, .jpg, ...; name OCR engines in methods), or an
            http(s) URL, downloaded into $PDFEXORCIST_CACHE.
        methods: Engines to run; default the text-layer engines.
        parse: Turns (page_no, lines) into dicts carrying key and "value";
            parse_by_columns places values by x.
        key: Columns that name a cell.
        min_agree: Engines that must agree; default a strict majority, at least 3.
            Missing or crashing engines do not lower it.
        checks: Run on verified cells; they fill the failed column.
        min_unopposed: Also accept a value this many engines read when none read another.
        families: Engines that are not independent vote once per family. A text
            layer made by ocrmypdf makes the text engines one family.
        normalize: Rewrites each value before the vote; None drops it.
        pages: 1-based pages to read; result pages are renumbered 1..len(pages).
        on_engine: Called as (name, event, detail) with "start", "done" (readings)
            or "skipped" (reason).
        fit_boxes: Grow page boxes over text drawn outside them; False when that
            text belongs to another page.
        return_readings: Also return Readings: each engine's readings, lines and
            boxes, and the PDF it read.
        jobs: Worker processes; each built-in engine reads up to jobs chunks of
            pages. Chandra, GLM-OCR and your own engines read in this process.
            Same result as 1.

    Returns:
        One row per key with its value, status and failed checks; with
        return_readings, (result, Readings).
    """
    from .fetch import download, is_url

    if is_url(pdf):
        pdf = download(str(pdf))
    report = on_engine or (lambda name, event, detail: None)
    readings = []
    kept = Readings()
    with tempfile.TemporaryDirectory() as tmp:
        if Path(pdf).suffix.lower() in IMAGE_SUFFIXES:
            pdf = _photo_pdf(Path(pdf), Path(tmp))
        pdf = _pages(Path(pdf), pages, Path(tmp)) if pages else Path(pdf)
        if fit_boxes:
            pdf = fit_page_boxes(pdf, Path(tmp) / "fit")
        if return_readings:
            kept.pdf = pdf.read_bytes()
        if not families and ocr_layer(pdf):
            families = {"text layer": TEXT_ENGINES}
            logger.warning("text layer made by ocrmypdf: text engines vote once, as 'text layer'")
        names = list(methods or DEFAULTS)
        read = _read_all(names, pdf, jobs, report, Path(tmp)) if jobs > 1 else {}
        for name in names:
            try:
                lines: Iterable[Page]
                if name in read:
                    got = read[name]
                    if isinstance(got, Exception):
                        raise got
                    lines = got
                else:
                    report(name, "start", None)
                    lines = EXTRACTORS[name](pdf)
                if return_readings:
                    lines = kept.lines[name] = list(lines)
                rows = list(parse(iter(lines)))
            except Exception as e:  # noqa: BLE001 - one engine must not sink the others
                logger.warning("skipping %s: %s: %s", name, type(e).__name__, e)
                report(name, "skipped", f"{type(e).__name__}: {e}")
                continue
            if normalize:
                rows = [
                    {**r, "value": v} for r in rows if (v := normalize(str(r["value"]))) is not None
                ]
            logger.info("%s: %d readings", name, len(rows))
            report(name, "done", len(rows))
            if rows:
                df = pd.DataFrame(rows).assign(method=name)
                if return_readings:
                    kept.frames.append(df)
                readings.append(df.drop(columns="box", errors="ignore"))
    voters = {m for r in readings for m in r.method.unique()}
    if families:
        voters = set(map(_family(families), voters))
    need = min_agree or (2 if families else 3)
    if len(voters) < need:
        raise RuntimeError(f"{len(voters)} independent readings produced output; need >= {need}")
    res = vote(pd.concat(readings, ignore_index=True), key, min_agree, min_unopposed, families)
    ok = res.status == "verified"
    res["failed"] = validate(res[ok], checks)["failed"].reindex(res.index, fill_value="")
    return (res, kept) if return_readings else res
