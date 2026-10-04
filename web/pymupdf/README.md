# PyMuPDF for Pyodide 314

`pymupdf-1.28.2-cp314-abi3-pyemscripten_2026_0_wasm32.whl`, built by `build.sh`
(sha256 `2b532c237f17b7b6605791a68e5d64522972a85e84d57fd6527f7ce7999e8fc5`).
Pyodide 314.0.7 ships no PyMuPDF, and PyPI's wasm wheel targets Pyodide 0.28.
Toolchain: pyodide-build 0.39.1, emsdk 5.0.3, swig 4.4.1, libclang 18.1.1, pipcl 13.

Install in Pyodide:

```python
await micropip.install("emfs:/tmp/pymupdf-1.28.2-cp314-abi3-pyemscripten_2026_0_wasm32.whl")
```

Install with `deps=False`: the metadata lists pytest and pipcl, unused at runtime.

## Checks (Node 26, `pyodide@314.0.7`)

- On the fixtures, text, block counts, page boxes and `find_tables()` match native
  PyMuPDF 1.28.2.
- Word coordinates and rendered pixels can differ in the last float32 bit: native
  arm64 fuses multiply-adds.
- MuPDF errors raise the same Python exceptions, and broken PDFs are repaired.
