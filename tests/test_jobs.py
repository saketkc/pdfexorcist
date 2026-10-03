"""Parallel reads (jobs)."""

import importlib
import os
from concurrent.futures import Future
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

import pandas as pd
import pytest
from cli_helpers import make_pdf, run

from pdfexorcist import extract, register
from pdfexorcist._registry import EXTRACTORS, IN_PROCESS

vote = importlib.import_module("pdfexorcist.vote")  # the module; pdfexorcist.vote is vote()
CII = Path(__file__).parent / "fixtures" / "cii" / "cii_2021_1A.1_p43.pdf"


@pytest.fixture
def five_pages(tmp_path) -> Path:
    """Five pages, one row each, every value naming its page."""
    rows = [[(f"Row{p}", str(10 * p), str(10 * p + 1), str(10 * p + 2))] for p in range(1, 6)]
    return make_pdf(tmp_path / "five.pdf", rows)


def _one(pdf: Path, jobs: int, **kw) -> pd.DataFrame:
    return extract(pdf, methods=["pdfplumber"], min_agree=1, jobs=jobs, **kw)


@pytest.mark.parametrize("jobs", [2, 3, 8])  # chunks of 3+2, 2+2+1, and more jobs than pages
def test_chunks_one_engine(five_pages, jobs):
    one = _one(five_pages, 1)
    pd.testing.assert_frame_equal(one, _one(five_pages, jobs))
    assert set(one.page) == {1, 2, 3, 4, 5}
    assert one[(one.page == 4) & (one.col == 0)].value.tolist() == ["40"]


def test_chunks_cover_every_page_once(five_pages, tmp_path):
    import pymupdf

    chunks = vote._chunks(five_pages, 5, 3, tmp_path / "c")
    assert list(chunks) == [1, 4]
    assert [pymupdf.open(p).page_count for p in chunks.values()] == [3, 2]


def test_chunk_page_numbers(five_pages):
    _, seq = _one(five_pages, 1, return_readings=True)
    _, par = _one(five_pages, 3, return_readings=True)
    assert [p for p, _ in par.lines["pdfplumber"]] == [p for p, _ in seq.lines["pdfplumber"]]
    assert par.lines["pdfplumber"] == seq.lines["pdfplumber"]


def test_jobs_1_never_starts_a_pool(five_pages, monkeypatch):
    monkeypatch.setattr(vote, "_pool", lambda workers: pytest.fail("a pool was started"))
    assert (_one(five_pages, 1).status == "verified").all()


def test_pool_reuse():
    assert vote._pool(2) is vote._pool(2)


class _BrokenPool:
    """A pool whose workers never start, as when Python runs from stdin."""

    def submit(self, *args, **kwargs) -> Future:
        f: Future = Future()
        f.set_exception(BrokenProcessPool("worker could not start"))
        return f


def test_pool_fallback(five_pages, monkeypatch):
    monkeypatch.setattr(vote, "_pool", lambda workers: _BrokenPool())
    methods = ["pdfplumber", "pymupdf", "pdfium"]
    pd.testing.assert_frame_equal(
        extract(five_pages, methods=methods), extract(five_pages, methods=methods, jobs=3)
    )


def test_local_engine(five_pages):
    seen: list[int] = []

    @register("pid_probe", default=False)
    def pid_probe(pdf):
        seen.append(os.getpid())
        yield from EXTRACTORS["pdfplumber"](pdf)

    try:
        extract(five_pages, methods=["pdfplumber", "pymupdf", "pid_probe"], jobs=3)
    finally:
        EXTRACTORS.pop("pid_probe")
    assert seen == [os.getpid()]  # once, here: not split into chunks, not in a worker


def test_registered_local():
    assert {"chandra", "glmocr"} <= IN_PROCESS and "pdfplumber" not in IN_PROCESS

    @register("gpu_probe", default=False, in_process=True)
    def gpu_probe(pdf):
        yield from ()

    try:
        assert "gpu_probe" in IN_PROCESS
    finally:
        EXTRACTORS.pop("gpu_probe")
        IN_PROCESS.discard("gpu_probe")


@pytest.mark.parametrize("command", ["show", "compare"])
def test_show_and_compare_take_jobs(command, tmp_path):
    for flag in ("-j", "--jobs"):
        out = tmp_path / f"{command}{flag}.png"
        r = run([command, str(CII), flag, "2", "-o", str(out), "-q"])
        assert r.exit_code == 0 and out.exists(), r.output
    assert run([command, str(CII), "-j", "0", "-o", str(tmp_path / "x.png")]).exit_code == 2


@pytest.mark.parametrize("command", ["extract", "show", "compare"])
def test_help_lists_jobs(command):
    out = run([command, "--help"]).output
    assert "--jobs" in out and "-j" in out
