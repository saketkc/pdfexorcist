"""Sphinx configuration."""

import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # autodoc imports pdfexorcist from this checkout

project = "pdfexorcist"
author = "Saket Choudhary"
copyright = f"2026, {author}"
try:
    release = metadata.version("pdfexorcist")
except metadata.PackageNotFoundError:
    release = ""

extensions = ["myst_parser", "sphinx.ext.autodoc", "sphinx.ext.napoleon", "sphinx_copybutton"]
source_suffix = {".md": "markdown"}
root_doc = "index"
exclude_patterns = ["_build", "requirements.txt"]

myst_enable_extensions = ["colon_fence"]
myst_heading_anchors = 4  # [text](page.md#a-heading) links, as on GitHub

autodoc_member_order = "bysource"
autodoc_typehints = "signature"
autodoc_preserve_defaults = True
napoleon_google_docstring = True
napoleon_numpy_docstring = False
copybutton_prompt_text = r"\$ "
copybutton_prompt_is_regexp = True

html_theme = "furo"
html_title = "pdfexorcist"
html_favicon = "assets/favicon.svg"
html_logo = "assets/logo/logo.svg"
html_static_path = ["_static"]
html_css_files = [
    "https://fonts.googleapis.com/css2?family=Albert+Sans:ital,wght@0,300..800;1,300..800&display=swap",
    "custom.css",
]
_fonts = {
    "font-stack": "'Albert Sans', system-ui, -apple-system, 'Segoe UI', sans-serif",
    "font-stack--headings": "'Albert Sans', system-ui, -apple-system, 'Segoe UI', sans-serif",
}
html_theme_options = {
    "light_css_variables": {
        **_fonts,
        "color-brand-primary": "#1f5f8b",
        "color-brand-content": "#1f5f8b",
    },
    "dark_css_variables": {
        **_fonts,
        "color-brand-primary": "#7cc4f0",
        "color-brand-content": "#7cc4f0",
    },
    "sidebar_hide_name": True,
    "navigation_with_keys": True,
    "top_of_page_buttons": ["view"],
}

_GA_ID = "G-VQKXEP0RRR"


def setup(app):
    """Add the Google Analytics tag (gtag.js) to every page."""
    app.add_js_file(f"https://www.googletagmanager.com/gtag/js?id={_GA_ID}", loading_method="async")
    app.add_js_file(
        None,
        body="window.dataLayer = window.dataLayer || [];"
        "function gtag(){dataLayer.push(arguments);}"
        f"gtag('js', new Date());gtag('config', '{_GA_ID}');",
    )
