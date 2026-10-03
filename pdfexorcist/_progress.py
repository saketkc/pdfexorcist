"""Live engine progress table."""

import time
from typing import Any

from rich.progress import Progress, ProgressColumn, SpinnerColumn, Task, TextColumn
from rich.text import Text

from ._ui import err, esc, plural


class _Spinner(SpinnerColumn):
    """Spins only for the engine that is reading."""

    def render(self, task: Task) -> Any:
        return Text("  ") if not task.started else super().render(task)


class _Seconds(ProgressColumn):
    def render(self, task: Task) -> Text:
        return Text(
            "" if not task.started or task.elapsed is None else f"{task.elapsed:.1f}s",
            style="dim",
        )


class EngineProgress:
    """on_engine callback: a live spinner per engine on a terminal, plain lines otherwise."""

    def __init__(self, methods: list[str], live: bool, quiet: bool) -> None:
        self.live, self.quiet = live and not quiet, quiet
        self.counts: dict[str, int] = {}
        self.skipped: dict[str, str] = {}
        self.started: dict[str, float] = {}
        self.seconds: dict[str, float] = {}
        width = max(len(m) for m in methods)
        self.width = width
        self.progress = Progress(
            _Spinner(finished_text="  "),
            TextColumn("{task.description}"),
            _Seconds(),
            console=err,
            transient=False,
        )
        self.tasks = {
            m: self.progress.add_task(f"[dim]{m:<{width}}  waiting[/]", start=False, total=1)
            for m in methods
        }

    def __enter__(self) -> "EngineProgress":
        if self.live:
            self.progress.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self.live:
            self.progress.stop()

    def __call__(self, name: str, event: str, detail: Any) -> None:
        t = self.tasks.get(name)
        if event == "start":
            self.started[name] = time.monotonic()
            if t is not None and self.live:
                self.progress.start_task(t)
                self.progress.update(t, description=f"{name:<{self.width}}  reading...")
            return
        self.seconds[name] = time.monotonic() - self.started.get(name, time.monotonic())
        if event == "done":
            self.counts[name] = int(detail)
            msg = f"{name:<{self.width}}  [green]{plural(int(detail), 'reading')}[/]"
        else:
            self.skipped[name] = str(detail)
            msg = f"{name:<{self.width}}  [yellow]skipped[/] ({esc(str(detail)[:80])})"
        if t is not None and self.live:
            self.progress.update(t, description=msg, completed=1)
        elif not self.quiet:
            err.print(f"  {msg}  [dim]{self.seconds[name]:.1f}s[/]")
