import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { loadPyodide } from 'pyodide';

import { boot, pythonProgram } from './core.js';
import { emscriptenProgram, pdfiumBridge } from './engines.js';
import Pdftotext from './vendor/pdftotext.js';

const WEB = dirname(fileURLToPath(import.meta.url));
export const ROOT = join(WEB, '..');

function tree(dir) {
  return readdirSync(dir, { withFileTypes: true, recursive: true })
    .filter((e) => e.isFile() && !e.parentPath.includes('__pycache__'))
    .map((e) => join(e.parentPath, e.name));
}

export async function nodeBoot() {
  // build.py's manifest, so the tests boot what the site ships
  const manifest = JSON.parse(execFileSync('python3', [join(WEB, 'build.py'), '--manifest'], { encoding: 'utf8' }));
  const files = Object.fromEntries(manifest.map(([path, src]) => [path, readFileSync(src)]));
  for (const f of tree(join(ROOT, 'tests'))) files[relative(ROOT, f)] = readFileSync(f);
  const pdfium = createRequire(import.meta.url)('./vendor/pdfium.cjs');
  await new Promise((resolve) => {
    if (pdfium.calledRun) resolve();
    else pdfium.onRuntimeInitialized = resolve;
  });
  globalThis.pdfium = pdfiumBridge(pdfium);
  const module = await WebAssembly.compile(readFileSync(join(WEB, 'vendor/pdftotext.wasm')));
  const opts = { loadPyodide, files };
  // tests only: it holds every boot file while alive
  opts.programs = { pdftotext: emscriptenProgram(Pdftotext, module), python: pythonProgram(opts) };
  return boot(opts);
}
