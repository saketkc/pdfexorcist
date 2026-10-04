// in: {open: pdf, name} -> {doc}; {doc, recipe, pages} -> extract(); {show: doc, page} -> {html}; {close: doc}

import { boot, close, extract, open, show } from './core.js';
import { emscriptenProgram } from './engines.js';
import { bytes, get, wasm } from './net.js';
import { serve } from './pdfium.js';
import Pdftotext from './vendor/pdftotext.js';

const PYODIDE = 'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs';
const status = (text) => postMessage({ type: 'status', text });

async function pythonFiles() {
  const manifest = await (await get('files.json')).json();
  return Object.fromEntries(await Promise.all(manifest.map(async ([path, url]) => [path, await bytes(url)])));
}

async function start() {
  status('Downloading the engines');
  const files = pythonFiles(); // not awaited; see core.js interpreter
  const [{ loadPyodide }, module] = await Promise.all([import(PYODIDE), wasm('vendor/pdftotext.wasm'), pdfium]);
  return boot({ loadPyodide, programs: { pdftotext: emscriptenProgram(Pdftotext, module) }, files, log: status });
}

const pdfium = serve(answer, (id) => cancelled.add(id));
const env = start();
env.then(
  () => postMessage({ type: 'ready', jspi: 'Suspending' in WebAssembly }),
  (e) => postMessage({ type: 'failed', message: String(e?.message ?? e) }),
);

const cancelled = new Set(); // queued extractions whose run moved on
let queue = Promise.resolve(); // serialised: one Python interpreter

function answer(msg) {
  if (msg.open) return env.then((e) => [{ doc: open(e, { pdf: msg.open, name: msg.name }) }]);
  if (msg.close) return env.then((e) => [close(e, msg.close)]);
  const job = queue.then(async () => {
    if (cancelled.delete(msg.id)) return [{ cancelled: true }];
    const progress = (engine, page, pages) => postMessage({ type: 'progress', id: msg.id, engine, page, pages });
    if (msg.show) return [await show(await env, { ...msg, doc: msg.show })];
    return [await extract(await env, { ...msg, progress })];
  });
  queue = job.catch(() => {});
  return job;
}
