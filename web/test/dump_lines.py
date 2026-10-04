"""Every text engine's lines on every fixture, as JSON; parity.mjs compares native and Pyodide."""

import json
import sys
from pathlib import Path

from pdfexorcist.extractors import EXTRACTORS
from pdfexorcist.vote import TEXT_ENGINES


def main(root: Path) -> None:
    out = {}
    for pdf in sorted((root / "tests" / "fixtures").rglob("*.pdf")):
        name = str(pdf.relative_to(root))
        for engine in TEXT_ENGINES:
            try:
                pages = [
                    [p, [[[round(x, 3), t] for x, t in ln] for ln in lines]]
                    for p, lines in EXTRACTORS[engine](pdf)
                ]
            except Exception as e:  # noqa: BLE001 - compared like any output
                pages = f"{type(e).__name__}: {e}"
            out[f"{engine} {name}"] = pages
    json.dump(out, sys.stdout, sort_keys=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
