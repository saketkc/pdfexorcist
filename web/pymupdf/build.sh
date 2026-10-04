#!/usr/bin/env bash
# PyMuPDF 1.28.2 for Pyodide 314.0.7 (ABI pyemscripten_2026_0): PyMuPDF's build_pyodide_wheel recipe plus macOS-host patches.
# Needs git, curl and uv.
set -euo pipefail

PYODIDE_VERSION=314.0.7
PYMUPDF_VERSION=1.28.2
MUPDF_SHA256=44075a84e329db55b9bef5f342a70fd26d69e48ad1d33cb89d9664581c641156
WORK=${WORK:-$HOME/.cache/pdfexorcist-web/pymupdf-build}

mkdir -p "$WORK"
cd "$WORK"

# 1. Sources: PyMuPDF at the release tag, MuPDF release tarball.
if [ ! -d pymupdf-src ]; then
  git -c advice.detachedHead=false clone --depth 1 --branch "$PYMUPDF_VERSION" \
    https://github.com/pymupdf/PyMuPDF.git pymupdf-src
fi
if [ ! -d "mupdf-$PYMUPDF_VERSION-source" ]; then
  curl -fsSLO "https://mupdf.com/downloads/archive/mupdf-$PYMUPDF_VERSION-source.tar.gz"
  echo "$MUPDF_SHA256  mupdf-$PYMUPDF_VERSION-source.tar.gz" | shasum -a 256 -c -
  tar xzf "mupdf-$PYMUPDF_VERSION-source.tar.gz"
fi

# 2. Host Python 3.14, pyodide-build, the 314.0.7 cross-build env and its pinned Emscripten (5.0.3).
if [ ! -d venv ]; then
  uv venv -q -p 3.14 venv
  uv pip install -q -p venv/bin/python pyodide-build==0.39.1 pip
fi
# shellcheck disable=SC1091
. venv/bin/activate
export PYODIDE_XBUILDENV_PATH="$WORK/xbuildenv"
if [ ! -d "xbuildenv/$PYODIDE_VERSION" ]; then
  pyodide xbuildenv install "$PYODIDE_VERSION"
fi
if [ ! -x "xbuildenv/$PYODIDE_VERSION/emsdk/upstream/emscripten/emcc" ]; then
  pyodide xbuildenv install-emscripten
fi
# shellcheck disable=SC1091
EMSDK_QUIET=1 . "xbuildenv/$PYODIDE_VERSION/emsdk/emsdk_env.sh"
test "$(pyodide config get emscripten_version)" = 5.0.3
emcc --version | head -1

# 3. macOS: patch pipcl and mupdfwrap onto their Linux branches (emcc rejects the Darwin link); --no-isolation keeps the patches.
uv pip install -q -p venv/bin/python pipcl==13 swig==4.4.1 libclang==18.1.1
python - "$WORK/mupdf-$PYMUPDF_VERSION-source" <<'PY'
import pathlib, sys, pipcl

def patch(path, old, new):
    p = pathlib.Path(path)
    s = p.read_text()
    if new in s:
        return
    assert s.count(old) == 1, (path, old)
    p.write_text(s.replace(old, new))

pyo = "os.environ.get('OS') == 'pyodide'"
patch(pipcl.__file__,
      "    return sys.platform.startswith( 'darwin')",
      f"    return sys.platform.startswith( 'darwin') and not {pyo}")
patch(pipcl.__file__,
      "    return platform.system() == 'Linux'",
      f"    return platform.system() == 'Linux' or {pyo}")
mupdf = sys.argv[1]
# the libclang header parse still needs state.macos; the wasm link must skip it
wrap = f'{mupdf}/scripts/wrap/__main__.py'
patch(wrap, "    if not state.state_.macos:\n        return",
      "    if not state.state_.macos or state.state_.pyodide:\n        return")
patch(wrap, "suffix2 = '.dylib' if state.state_.macos else '.so'",
      "suffix2 = '.dylib' if state.state_.macos and not state.state_.pyodide else '.so'")
patch(wrap, "                        if state.state_.macos:\n                            # We need this",
      "                        if state.state_.macos and not state.state_.pyodide:\n                            # We need this")
patch(f'{mupdf}/scripts/jlib.py',
      "    darwin = (platform.system() == 'Darwin')",
      f"    darwin = (platform.system() == 'Darwin') and not {pyo}")
PY

# 4. Build. Environment as in PyMuPDF's build_pyodide_wheel().
export OS=pyodide
export HAVE_LIBCRYPTO=no
export PYMUPDF_SETUP_FLAVOUR=pb
export PYMUPDF_SETUP_MUPDF_TESSERACT=0
export PYMUPDF_SETUP_MUPDF_BUILD="$WORK/mupdf-$PYMUPDF_VERSION-source"
cd pymupdf-src
pyodide build --no-isolation --exports whole_archive
ls -l dist/
