"""Wasm programs and python as subprocesses, for Pyodide.

run_sync waits for them, so enter Python with callPromising or runPythonAsync.
"""

import contextlib
import functools
import io
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from js import runProgram  # type: ignore[import-not-found]  # set by core.js
from pyodide.ffi import can_run_sync, run_sync, to_js  # type: ignore[import-not-found]

from pdfexorcist import cli
from pdfexorcist.extractors import EXTRACTORS

PROGRAMS = ("pdftotext",)
SHARE_CWD = ("python",)  # also gets cwd, as a process on the same disk would
BIN = Path("/usr/local/bin")


def _pause(promise: Any) -> Any:
    if not can_run_sync():
        raise RuntimeError("this browser cannot pause Python for JavaScript (it lacks JSPI)")
    return run_sync(promise)


def _install_programs() -> None:
    """Marker files on PATH, for shutil.which."""
    BIN.mkdir(parents=True, exist_ok=True)
    for name in PROGRAMS:
        (BIN / name).write_text("# runs as wasm through subprocess.run; see browser.py\n")
        (BIN / name).chmod(0o755)
    path = os.environ.get("PATH", "")
    if str(BIN) not in path.split(os.pathsep):
        os.environ["PATH"] = os.pathsep.join(filter(None, [str(BIN), path]))


_subprocess_run = subprocess.run


def _run_program(
    args: Any,
    *,
    capture_output: bool = False,
    stdout: Any = None,
    stderr: Any = None,
    encoding: str | None = None,
    errors: str | None = None,
    text: bool | None = None,
    check: bool = False,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    """subprocess.run for a wasm program or python; other options unsupported."""
    name = _program(args)
    paths = [Path(a) for a in args[1:] if Path(a).is_file()]
    if name in SHARE_CWD:
        paths += [p for p in Path.cwd().rglob("*") if p.is_file()]
    files = {str(p.resolve()): p.read_bytes() for p in paths}
    env = dict(os.environ if env is None else env)
    code, out, err, after = _pause(
        runProgram(
            name, to_js(list(args[1:])), to_js(list(files.items())), str(Path.cwd()), to_js(env)
        )
    ).to_py()
    for path, data in after:
        if files.get(path) != bytes(data):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(bytes(data))
    out, err = bytes(out), bytes(err)
    if encoding or errors or text:
        out = out.decode(encoding or "utf-8", errors or "strict")
        err = err.decode(encoding or "utf-8", errors or "strict")
    piped = subprocess.PIPE
    res = subprocess.CompletedProcess(
        args,
        code,
        out if capture_output or stdout == piped else None,
        err if capture_output or stderr == piped else None,
    )
    if check:
        res.check_returncode()
    return res


def _program(args: Any) -> str | None:
    if not isinstance(args, (list, tuple)) or not args:
        return None
    if str(args[0]) == sys.executable:
        return "python"
    name = Path(args[0]).name
    return name if name in PROGRAMS else None


def _run(args: Any, *a: Any, **kw: Any) -> Any:
    if _program(args):
        return _run_program(args, *a, **kw)
    return _subprocess_run(args, *a, **kw)


subprocess.run = _run  # type: ignore[assignment]
_install_programs()


def _reporting(name: str, read: Callable, report: Callable, pages: Callable) -> Callable:
    """read, calling report(name, pages read, pages) per page."""

    @functools.wraps(read)  # extract() schedules by the engine's module
    def engine(pdf: Path) -> Iterator:
        total = pages(pdf)
        report(name, 0, total)
        for i, page in enumerate(read(pdf), start=1):
            report(name, i, total)
            yield page

    return engine


def exit_code(e: SystemExit) -> int:
    """Exit status as a process gives it; a string code goes to stderr."""
    if e.code is None or isinstance(e.code, int):
        return e.code or 0
    print(e.code, file=sys.stderr)
    return 1


def run(argv: list[str], report: Callable | None = None) -> tuple[int, str]:
    """(exit code, stdout) of one CLI call; report(engine, page, pages) for progress."""
    saved = dict(EXTRACTORS)
    if report:  # restored in finally
        from pdfexorcist._run import _page_count  # here: importing pandas at boot breaks pyarrow

        pages = functools.cache(lambda pdf: _page_count(pdf, False))  # once for all engines
        EXTRACTORS.update({n: _reporting(n, f, report, pages) for n, f in saved.items()})
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            try:
                cli.main(argv)
                code = 0
            except SystemExit as e:
                code = exit_code(e)
    finally:
        EXTRACTORS.update(saved)
    return code, buf.getvalue()
