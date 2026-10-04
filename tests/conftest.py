"""Test setup."""

import os
import sys
from pathlib import Path

# plain text in tests; read on import, and typer forces colour under GITHUB_ACTIONS
os.environ.pop("FORCE_COLOR", None)
os.environ["_TYPER_FORCE_DISABLE_TERMINAL"] = "1"

import pytest
from cli_helpers import STATES, make_pdf

import pdfexorcist._ui as ui

# the example parsers, imported by name; appended so none shadows the standard library
EXAMPLES = Path(__file__).parent.parent / "examples"
sys.path += [str(d) for d in sorted(EXAMPLES.iterdir()) if d.is_dir()]


@pytest.fixture
def wide_console():
    """Wide consoles, so messages are not wrapped mid-word in assertions."""
    before = ui.out.width, ui.err.width
    ui.out.width = ui.err.width = 250
    yield
    ui.out.width, ui.err.width = before


@pytest.fixture
def states_pdf(tmp_path, monkeypatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return make_pdf(tmp_path / "states.pdf", [STATES])
