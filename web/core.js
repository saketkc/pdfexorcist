// callers set globalThis.pdfium (engines.js pdfiumBridge) before boot

import { ls, programRunner } from './engines.js';

// hash-checked by Pyodide's lock; every other package is a pinned wheel in files
const PACKAGES = [
  'micropip',
  'pandas',
  'opencv-python',
  'pillow',
  'cryptography',
  'charset-normalizer',
  'pygments',
  'annotated-doc',
];

/** files (or a promise of them): "site/..." to site-packages, "wheel/..." installed, the rest under /repo */
/** programs: {name: program} for engines.js programRunner */
export async function boot(opts) {
  globalThis.runProgram ??= programRunner(opts.programs);
  const py = await interpreter(opts);
  return { py, glue: py.pyimport('browser') };
}

/** python as a subprocess: a fresh interpreter, dropped after; Pyodide cannot free one */
export function pythonProgram(opts) {
  return async ({ args, env, stage }) => {
    const py = await interpreter(opts);
    const out = [];
    const err = [];
    const sink = (to) => ({
      write: (buf) => {
        to.push(buf.slice()); // buf is reused
        return buf.length;
      },
    });
    py.setStdout(sink(out));
    py.setStderr(sink(err));
    const argv = py.toPy(args);
    const environ = py.toPy(env);
    try {
      stage(py.FS);
      py.globals.set('ARGV', argv);
      py.globals.set('ENV', environ);
      const code = await py.runPythonAsync(PYTHON_MAIN);
      return [code, joined(out), joined(err), py.FS];
    } finally {
      argv.destroy();
      environ.destroy();
      py.setStdout();
      py.setStderr();
    }
  };
}

function joined(chunks) {
  const all = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
  chunks.reduce((at, c) => (all.set(c, at), at + c.length), 0);
  return all;
}

// python [-m module | -c code | script] args...
const PYTHON_MAIN = `
import os, runpy, sys, traceback
import browser  # the platform: wasm programs on PATH
os.environ.clear()
os.environ.update(ENV)
code = 0
try:
    if ARGV[:1] == ['-m']:
        sys.argv = [ARGV[1], *ARGV[2:]]
        runpy.run_module(ARGV[1], run_name='__main__', alter_sys=True)
    elif ARGV[:1] == ['-c']:
        sys.argv = ['-c', *ARGV[2:]]
        exec(ARGV[1], {'__name__': '__main__'})
    else:
        sys.argv = list(ARGV)
        runpy.run_path(ARGV[0], run_name='__main__')
except SystemExit as e:
    code = browser.exit_code(e)
except BaseException:
    traceback.print_exc()
    code = 1
sys.stdout.flush()
sys.stderr.flush()
code
`;

async function interpreter({ loadPyodide, files, log = () => {} }) {
  log('Starting Python');
  const py = await loadPyodide();
  log('Loading Python packages');
  await py.loadPackage(PACKAGES, { messageCallback: () => {} });
  const site = py.runPython('import site; site.getsitepackages()[0]');
  files = await files; // awaited late: downloads alongside Pyodide's packages
  for (const [path, data] of Object.entries(files)) {
    const dest = path.startsWith('site/')
      ? `${site}/${path.slice(5)}`
      : path.startsWith('wheel/')
        ? `/tmp/${path}`
        : `/repo/${path}`;
    py.FS.mkdirTree(dest.slice(0, dest.lastIndexOf('/')));
    py.FS.writeFile(dest, data);
  }
  const wheels = Object.keys(files)
    .filter((p) => p.startsWith('wheel/'))
    .map((p) => `emfs:/tmp/${p}`);
  log('Installing the engines');
  await py.runPythonAsync(`
import micropip
await micropip.install(${JSON.stringify(wheels)}, deps=False)
`);
  for (const w of wheels) py.FS.unlink(w.slice('emfs:'.length)); // installed; frees the memory
  py.FS.mkdirTree('/work/out');
  return py;
}

const documents = new Map(); // handle -> path of an opened PDF
let next = 0;

/** writes the PDF once; extract and close take the handle */
export function open({ py }, { pdf, name }) {
  const doc = ++next;
  const dir = `/work/${doc}`;
  py.FS.mkdirTree(dir);
  const path = `${dir}/${name.replace(/[^\w.-]/g, '_')}`;
  documents.set(doc, path);
  py.FS.writeFile(path, pdf);
  return doc;
}

export function close({ py }, doc) {
  const path = documents.get(doc);
  if (!path) return;
  py.FS.unlink(path);
  documents.delete(doc);
}

/** one CLI call on the doc's PDF; returns [code, stdout] */
async function cli({ py, glue }, cmd, doc, argv, recipe, progress) {
  const path = documents.get(doc);
  if (!path) throw new Error('This PDF is no longer open; choose it again.');
  const args = py.toPy([cmd, path, ...argv, ...(recipe ? ['--recipe', `/repo/${recipe}`] : [])]);
  try {
    const res = await glue.run.callPromising(args, progress); // callPromising: run_sync waits on wasm programs
    try {
      return res.toJs();
    } finally {
      res.destroy();
    }
  } finally {
    args.destroy();
  }
}

/** the CLI's show view of one page: every voted cell boxed, as self-contained HTML */
export async function show(ctx, { doc, page, recipe }) {
  const out = '/work/grid.html';
  const [code, stdout] = await cli(ctx, 'show', doc, ['--page', String(page), '-o', out, '--force', '-q'], recipe);
  if (code) throw new Error(stdout.trim() || `pdfexorcist show stopped with exit code ${code}`);
  return { html: ctx.py.FS.readFile(out, { encoding: 'utf8' }) };
}

/** recipe: a path under /repo; returns the summary, and the table and review as text */
export async function extract(ctx, { doc, recipe, pages, progress }) {
  const { py } = ctx;
  for (const f of ls(py.FS, '/work/out')) py.FS.unlink(`/work/out/${f}`);
  const argv = ['-o', '/work/out/', '--json', '-q', '--force', ...(pages ? ['--pages', pages] : [])];
  const [, stdout] = await cli(ctx, 'extract', doc, argv, recipe, progress);
  const summary = JSON.parse(stdout);
  const text = (path) => path && py.FS.readFile(path, { encoding: 'utf8' });
  return { summary, table: text(summary.outputs?.[0]), review: text(summary.review) };
}
