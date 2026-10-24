"""Suggest a shipped recipe for a PDF: by words, by layout, then by a trial run."""

import hashlib
import json
import logging
import math
import re
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import recipe as recipes
from ._prepare import as_pdf
from ._shipped import recipe_name, shipped_dir, shipped_recipes
from .rows import is_value

logger = logging.getLogger(__name__)

INDEX = Path(__file__).parent / "_recipe_index.json"
MAX_PAGES = 20  # pages read from the PDF, and from each recipe's sample
TOP_WORDS = 300  # words kept per sample in the index
INDEX_KEYS = ("words", "shapes", "xs", "ocr")
TEXT_ENGINE = "pymupdf"  # reads the layout, and a text PDF's trial runs
SHORTLIST = 3  # recipes taken from each ranking for a trial run
BINS = 20  # column starts, as a fraction of page width
COVERAGE = 0.2  # a fit reads at least this share of the values printed on its pages
MISPRINTS = 0.02  # a fit may fail its checks on this share of cells (a report's own errors)
WORD = re.compile(r"[a-z][a-z'-]{2,}")
KINDS = [  # value kinds, tried in order; any other value is "-"
    ("A", re.compile(r"^\d{1,2}[-/.]\d{1,2}[-/.](\d{2,4})?$")),
    ("R", re.compile(r"^\d+/\d+$")),  # stations 3/4
    ("P", re.compile(r"^\(?[+-]?[\d,]*\.?\d+%\)?$")),
    ("D", re.compile(r"^\(?[+-]?[\d,]*\.\d+\)?$")),
    ("I", re.compile(r"^\(?[+-]?\d[\d,]*\)?$")),
]


def _kind(cell: str) -> str:
    """One letter for a cell: T for text, else the kind of value it holds."""
    toks = cell.split()
    if not toks or not all(is_value(t) for t in toks):
        return "T"
    return next((k for k, rx in KINDS if rx.match(toks[0])), "-")


def fingerprint(
    pdf: Path, pages: list[int] | None = None, texts: Sequence[str] | None = None
) -> dict[str, Any]:
    """Words, line shapes and column starts of up to MAX_PAGES pages of a PDF; texts are its
    pages' text when already read. Tesseract, when installed, reads scanned pages: "ocr_text"
    and "values" hold its text and number count by page; "ocr" says whether it ran."""
    import pymupdf

    from .extractors import EXTRACTORS
    from .pages import is_scan, page_kinds
    from .vote import _pages

    with pymupdf.open(pdf) as doc:
        n_pages = doc.page_count
        pages = (pages or list(range(1, n_pages + 1)))[:MAX_PAGES]
        widths = {k: doc[p - 1].rect.width for k, p in enumerate(pages, start=1)}
        text = [texts[p - 1] if texts else doc[p - 1].get_text() for p in pages]
    words = Counter(w for t in text for w in WORD.findall(t.lower()))
    kinds = page_kinds(pdf, pages)
    scanned = [k for k, kind in enumerate(kinds, start=1) if is_scan([kind])]
    ocr = bool(scanned) and shutil.which("tesseract") is not None
    ocr_text: dict[int, str] = {}
    values: dict[int, int] = {}
    shapes: Counter[str] = Counter()
    xs = [0.0] * BINS
    with tempfile.TemporaryDirectory() as tmp:
        part = _pages(pdf, pages, Path(tmp))
        read = dict(EXTRACTORS[TEXT_ENGINE](part))
        if ocr:
            for i, lines in EXTRACTORS["tesseract"](_pages(part, scanned, Path(tmp))):
                k = scanned[i - 1]
                read[k] = lines
                ocr_text[pages[k - 1]] = "\n".join(" ".join(t for _, t in c) for c in lines)
                values[pages[k - 1]] = sum(is_value(w) for w in ocr_text[pages[k - 1]].split())
                words.update(WORD.findall(ocr_text[pages[k - 1]].lower()))
        for page_no, lines in read.items():
            for cells in lines:
                if len(cells) >= 2:
                    shapes["".join(_kind(t) for _, t in cells)[:16]] += 1
                if len(cells) >= 3:
                    for x, _ in cells:
                        xs[min(BINS - 1, int(BINS * x / widths[page_no]))] += 1
    return {
        "words": dict(words),
        "shapes": dict(shapes),
        "xs": xs,
        "ocr": ocr,
        "scan": is_scan(kinds),
        "ocr_text": ocr_text,
        "values": values,
        "n_pages": n_pages,
    }


def read(pdf: Path) -> tuple[dict[str, Any], list[str]]:
    """pdf's fingerprint and page texts. A page OCR'd for the fingerprint adds that text; any
    other page without a usable text layer adds tesseract's reading of its top strip."""
    from .pages import page_texts

    fp = fingerprint(pdf)
    rest = [p for p in range(1, fp["n_pages"] + 1) if p not in fp["ocr_text"]]
    texts = page_texts(pdf, ocr_fallback=bool(rest), within=rest)
    for p, t in fp["ocr_text"].items():
        texts[p - 1] += "\n" + t
    return fp, texts


def _cosine(a: Mapping[Any, float], b: Mapping[Any, float]) -> float:
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return dot / norm if norm else 0.0


def layout_score(a: dict[str, Any], b: dict[str, Any]) -> float:
    """How alike two fingerprints' line shapes and column starts are, 0 to 1."""
    xs = _cosine(dict(enumerate(a["xs"])), dict(enumerate(b["xs"])))
    return 0.6 * _cosine(a["shapes"], b["shapes"]) + 0.4 * xs


def word_score(words: Mapping[str, int], entry: dict[str, Any], idf: Mapping[str, float]) -> float:
    """The share of a sample's words, weighted by rarity across samples, found in the PDF."""
    total = sum(idf[w] for w in entry["words"])
    return sum(idf[w] for w in entry["words"] if w in words) / total if total else 0.0


def file_sha(path: Path, text: bool = False) -> str:
    """The first 16 hex digits of a file's SHA-256; text with LF line ends, as Windows has CRLF."""
    data = path.read_bytes()
    return hashlib.sha256(data.replace(b"\r\n", b"\n") if text else data).hexdigest()[:16]


def recipe_sample(rec: Any) -> Path | None:
    """A recipe's sample file, a PDF or an image, when there is one."""
    sample = (rec.base_dir / rec.sample).resolve() if rec.sample else None
    return sample if sample and sample.is_file() else None


def build_index(root: Path | None = None) -> dict[str, Any]:
    """Fingerprint each recipe's sample in root (default: the shipped ones); needs the repo's
    test fixtures."""
    import pymupdf

    root = root or shipped_dir()
    entries, seen = [], {}
    with tempfile.TemporaryDirectory() as tmp:
        for path in shipped_recipes(root):
            rec = recipes.load(path)
            sample = recipe_sample(rec)
            if sample is None:
                continue
            sha = file_sha(sample)
            pdf = as_pdf(sample, Path(tmp))
            with pymupdf.open(pdf) as doc:
                pages = recipes.page_list(rec, pdf, doc.page_count)
            key = sha, tuple(pages or ())
            if key not in seen:
                fp = fingerprint(pdf, pages)
                top = Counter(fp["words"]).most_common(TOP_WORDS)
                seen[key] = {k: fp[k] for k in INDEX_KEYS} | {"words": sorted(w for w, _ in top)}
            rel = path.relative_to(root).as_posix()
            entry = {
                "path": rel,
                "recipe_sha": file_sha(path, text=True),
                "sample_sha": sha,
                "pages": pages,
            }
            entries.append({**entry, **seen[key]})
    return {"entries": entries}


def load_index() -> list[dict[str, Any]]:
    """The fingerprints shipped with the package."""
    return json.loads(INDEX.read_text(encoding="utf-8"))["entries"]


@dataclass
class Candidate:
    """One recipe's scores for a PDF, and its trial run."""

    recipe: str
    path: Path
    title: str
    words: float
    layout: float
    page_match: bool | None  # None: the recipe picks no pages by their text
    pages: list[int] | None = None  # the recipe's pages of this PDF; None: all
    area: tuple | None = None  # the recipe's crop
    fit_boxes: bool = True
    cells: int | None = None
    coverage: float = 0.0  # numbers read / numbers printed on the pages tried
    failed: list[str] = field(default_factory=list)
    failed_share: float = 0.0  # of the cells read
    error: str = ""
    engines: tuple[str, ...] | None = None  # the recipe's engines; None: the defaults
    engine: str = TEXT_ENGINE  # the trial run's engine
    needs: list[str] = field(default_factory=list)  # its OCR engines, none installed

    @property
    def fits(self) -> bool:
        return self.coverage >= COVERAGE and self.failed_share <= MISPRINTS and not self.error

    @property
    def score(self) -> float:
        return (self.words + self.layout) / 2 + (0.2 if self.page_match else 0.0)


def rank(
    pdf: Path, fp: dict[str, Any], texts: list[str], index: list[dict[str, Any]] | None = None
) -> list[Candidate]:
    """Every indexed recipe scored for pdf (its fingerprint and page texts, from read) by words,
    layout and page text, best first."""
    index = load_index() if index is None else index
    samples = {tuple(e["words"]) for e in index}  # recipes sharing a sample count once
    df = Counter(w for words in samples for w in words)
    idf = {w: math.log((1 + len(samples)) / (1 + c)) + 1 for w, c in df.items()}
    out = []
    for e in index:
        path = shipped_dir() / e["path"]
        rec = recipes.load(path)
        try:
            pages = recipes.page_list(rec, pdf, len(texts), texts=texts)
        except ValueError:  # its select names pages this PDF lacks
            pages = None
        out.append(
            Candidate(
                recipe=recipe_name(path),
                path=path,
                title=rec.name or recipe_name(path),
                words=word_score(fp["words"], e, idf),
                layout=layout_score(fp, e),
                page_match=bool(pages) if rec.has_page_text else None,
                pages=pages,
                area=rec.area,
                fit_boxes=rec.fit_boxes,
                engines=rec.engines,
                # pdfexorcist charts reads its values; extract reads none
                cells=0 if rec.charts is not None else None,
            )
        )
    return sorted(out, key=lambda c: -c.score)


def shortlist(ranked: list[Candidate]) -> list[Candidate]:
    """The top recipes by words, by layout and by page text, without repeats."""
    picks = [
        *sorted(ranked, key=lambda c: -c.words)[:SHORTLIST],
        *sorted(ranked, key=lambda c: -c.layout)[:SHORTLIST],
        *[c for c in ranked if c.page_match][:SHORTLIST],
    ]
    return sorted({c.recipe: c for c in picks}.values(), key=lambda c: -c.score)


@contextmanager
def _quiet_checks() -> Iterator[None]:
    """Checks warn of labels a wrong recipe cannot find; a trial expects that. Restores the
    level, so a later extract in the same process still warns."""
    log = logging.getLogger("pdfexorcist._recipe_model")
    level = log.level
    log.setLevel(logging.ERROR)
    try:
        yield
    finally:
        log.setLevel(level)


def trial(c: Candidate, src: Path, printed: int) -> Candidate:
    """Run the recipe as extract does, with one engine, on src: its pages of the PDF through
    _clean.prepare; printed counts the numbers on those pages."""
    from ._run import Plan, load_recipe, run
    from ._ui import CliError
    from .vote import TooFewReadings

    plan = Plan(src=src, is_image=False, n_pages=0, pages=None, methods=[c.engine], min_agree=1)
    try:
        with _quiet_checks():
            res, _ = run(plan, load_recipe(c.path), lambda *_: None, prepared=True)
    except CliError as e:
        if isinstance(e.__cause__, TooFewReadings):
            c.cells = 0  # the recipe read nothing here
        else:
            c.error = _first_line(e)
        return c
    except Exception as e:  # a recipe's own code may raise anything
        logger.debug("trial of %s failed", c.recipe, exc_info=True)
        c.error = _first_line(e)
        return c
    ok = res[res.status == "verified"]
    c.cells = len(ok)
    c.coverage = sum(map(is_value, ok.value.astype(str))) / printed if printed else 0.0
    c.failed = sorted({f for f in ok.failed if f})
    c.failed_share = float((ok.failed.fillna("") != "").mean()) if len(ok) else 0.0
    return c


def _first_line(e: Exception) -> str:
    return (str(e).splitlines() or [type(e).__name__])[0][:120]


def _prepared(
    pdf: Path, c: Candidate, tmp: Path, done: dict, values: Mapping[int, int]
) -> tuple[Path, int] | None:
    """The candidate's pages of pdf through _clean.prepare, once per page set, crop and boxes,
    with the count of numbers printed on them (values: tesseract's count on a scanned page);
    None with c.error set when that fails."""
    import pymupdf

    from ._clean import prepare

    with pymupdf.open(pdf) as doc:
        pages = (c.pages or list(range(1, doc.page_count + 1)))[:MAX_PAGES]
        key = tuple(pages), c.area, c.fit_boxes
        if key not in done:
            words = (w[4] for p in pages for w in doc[p - 1].get_text("words"))
            printed = sum(map(is_value, words)) or sum(values.get(p, 0) for p in pages)
            out = tmp / str(len(done))
            out.mkdir()
            try:
                done[key] = (prepare(pdf, pages, c.area, out, c.fit_boxes), printed), ""
            except Exception as e:  # a PDF the cleaning steps cannot read
                logger.debug("preparing pages for %s failed", c.recipe, exc_info=True)
                done[key] = None, _first_line(e)
    ready, c.error = done[key]
    return ready


def _trial_engines(picked: list[Candidate]) -> None:
    """For a scan or a photo: try each recipe with an installed OCR engine it names (any, when
    it names none), cheapest first; with none installed, the recipe needs one."""
    from .doctor import OCR_ENGINES, installed_ocr

    here = installed_ocr()  # in registry order, tesseract first
    for c in picked:
        wanted = [e for e in c.engines or OCR_ENGINES if e in OCR_ENGINES]
        engine = next((e for e in here if e in wanted), None)
        if engine:
            c.engine = engine
        else:
            c.needs, c.cells = wanted, 0


def suggest(pdf: Path, jobs: int = 1) -> tuple[list[Candidate], bool]:
    """The shortlisted recipes, run on pdf (or an image) in jobs worker processes, recipes that
    fit first; and whether pdf is a scan."""
    from functools import partial

    from .doctor import OCR_ENGINES
    from .vote import _pool, or_here

    with tempfile.TemporaryDirectory() as tmp:
        pdf = as_pdf(pdf, Path(tmp))
        fp, texts = read(pdf)
        picked = shortlist(rank(pdf, fp, texts))
        if fp["scan"]:
            _trial_engines(picked)
        for c in picked:
            if c.page_match is False:
                c.cells = 0  # its page text is not in this PDF
        done: dict = {}
        tasks = [
            (c, *ready)
            for c in picked
            if c.cells is None and (ready := _prepared(pdf, c, Path(tmp), done, fp["values"]))
        ]
        pool = _pool(jobs) if jobs > 1 and len(tasks) > 1 else None
        if pool is None:
            for c, src, printed in tasks:
                trial(c, src, printed)  # fills c in
        else:
            futures = [pool.submit(trial, *task) for task in tasks]
            for fut, (c, src, printed) in zip(futures, tasks, strict=True):
                got = or_here(fut, jobs, partial(trial, c, src, printed))
                if isinstance(got, Exception):  # it could not travel back from the worker
                    c.error = _first_line(got)
                else:
                    vars(c).update(vars(got))  # a worker returns a filled-in copy

    def ocr_only(c: Candidate) -> bool:  # on a text PDF it comes after the text recipes
        engines = set(c.engines or ())
        return bool(engines) and engines <= set(OCR_ENGINES) and not fp["scan"]

    return sorted(picked, key=lambda c: (not c.fits, ocr_only(c), -c.score)), fp["scan"]


if __name__ == "__main__":  # rebuilds the index from the fixtures
    if not shutil.which("tesseract"):
        raise SystemExit("rebuilding the index needs tesseract, to read the photo and scan samples")
    INDEX.write_text(json.dumps(build_index(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
