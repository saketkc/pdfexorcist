"""Offline HTML view."""

import base64
import html
import io
import json
from pathlib import Path
from typing import Any

from .show import PageView
from .show_assets import CSS, SCRIPT

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>__CSS__</style>
</head>
<body>
<header>
  <h1>__TITLE__</h1>
  <p class="meta" id="meta"></p>
  <div class="legend" id="legend" role="group" aria-label="Show cells by status"></div>
  <ul class="notes" id="notes"></ul>
</header>
<nav class="tabs" role="tablist" aria-label="Views">
  <button role="tab" id="tab-page" aria-controls="view-page" aria-selected="true">Page</button>
  <button role="tab" id="tab-compare" aria-controls="view-compare" aria-selected="false"
          tabindex="-1">Compare engines</button>
  <button role="tab" id="tab-grid" aria-controls="view-grid" aria-selected="false"
          tabindex="-1">Grid</button>
  <span class="zoom" role="group" aria-label="Zoom">
    <button id="zoom-out" title="Zoom out (-)" aria-label="Zoom out">&minus;</button>
    <output id="zoom-level" aria-live="polite">100%</output>
    <button id="zoom-in" title="Zoom in (+)" aria-label="Zoom in">+</button>
    <button id="zoom-fit" title="Fit the width (0)">Fit</button>
  </span>
</nav>
<main>
  <section id="view-page" role="tabpanel" aria-labelledby="tab-page">
    <div class="pagewrap">
      <div class="scroller" id="page-scroller">
        <div id="page-svg" tabindex="0" role="application"
             aria-label="The page with a box on every cell. Arrow keys move between cells, Enter pins one, U jumps to the next unresolved cell."></div>
      </div>
      <aside id="detail" aria-live="polite"><p class="hint">Hover or click a cell, or focus the
        page and use the arrow keys.</p></aside>
    </div>
  </section>
  <section id="view-compare" role="tabpanel" aria-labelledby="tab-compare" hidden>
    <div class="toolbar" id="engine-toggles" role="group" aria-label="Engines shown"></div>
    <p class="hint">Each panel shows one engine's own readings before the vote. Zoom and scroll
      move all panels together. Thick hatched boxes: this engine read a different value from the
      agreed one (its reading is printed above). Dashed: a position borrowed from the other engines
      (this engine gives none). Dotted grey: a cell this engine did not read.</p>
    <div class="panels" id="panels"></div>
  </section>
  <section id="view-grid" role="tabpanel" aria-labelledby="tab-grid" hidden>
    <div class="toolbar">
      <label>Show <select id="grid-filter">
        <option value="all">every cell</option>
        <option value="disagree">cells an engine disagrees on</option>
        <option value="unresolved">unresolved</option>
        <option value="failed">failed a check</option>
        <option value="agreed">agreed</option>
        <option value="nobox">not on the page</option>
      </select></label>
      <label>Find <input id="grid-search" type="search" placeholder="key, value or label"></label>
      <span id="grid-count" aria-live="polite"></span>
    </div>
    <div class="tablewrap"><table id="grid"><thead></thead><tbody></tbody></table></div>
  </section>
</main>
<script type="application/json" id="data">__DATA__</script>
<script>__SCRIPT__</script>
</body>
</html>
"""  # noqa: E501 - the page aria-label is one attribute value and cannot wrap


def _png_data_uri(img: Any) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def view_data(view: PageView, start: str = "page") -> dict[str, Any]:
    """The JSON the page script reads."""
    return {
        "source": Path(view.source).name,
        "page": view.page,
        "methods": view.methods,
        "min_agree": view.min_agree,
        "key": view.key,
        "counts": view.counts(),
        "notes": view.notes,
        "image": {
            "w": view.image.width,
            "h": view.image.height,
            "src": _png_data_uri(view.image),
        },
        "cells": view.cells,
        "rows": view.rows,
        "cols": view.cols,
        "ignored": view.ignored,
        "engines": view.engines,
        "start": start,
    }


def render_html(view: PageView, start: str = "page") -> str:
    data = json.dumps(view_data(view, start), ensure_ascii=False, default=str)
    data = data.replace("</", "<\\/")  # a value cannot end the script block
    title = html.escape(f"{Path(view.source).name}, page {view.page}: what pdfexorcist extracts")
    return (
        PAGE.replace("__CSS__", CSS)
        .replace("__SCRIPT__", SCRIPT)
        .replace("__TITLE__", title)
        .replace("__DATA__", data)
    )


def write_html(view: PageView, path: Path, start: str = "page") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(view, start), encoding="utf-8")
    return path
