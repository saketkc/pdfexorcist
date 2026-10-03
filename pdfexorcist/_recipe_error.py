"""Recipe errors."""

from pathlib import Path


class RecipeError(ValueError):
    """A recipe problem, with the line it is on and how to fix it."""

    def __init__(
        self,
        message: str,
        path: Path | None = None,
        line: int | None = None,
        hint: str = "",
    ) -> None:
        super().__init__(message)
        self.message, self.path, self.line, self.hint = message, path, line, hint

    def source_line(self) -> str:
        """The offending line of the recipe file ("" when unknown)."""
        if not (self.path and self.line):
            return ""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ""
        return lines[self.line - 1] if 0 < self.line <= len(lines) else ""
