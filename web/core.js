// callers set globalThis.pdfium (engines.js pdfiumBridge) before boot

import { canPause, ls, programRunner } from './engines.js';

// hash-checked by Pyodide's lock; every other package is a pinned wheel in files
const PACKAGES = [
  'micropip',
  'pandas',
  'pillow',
  'cryptography',
  'charset-normalizer',
  'pygments',
  'annotated-doc',
];

// Engines that are not in the first download. add() installs an engine when a run selects it.
export const LATER = {
  camelot: { wheels: ['wheel/camelot_py-', 'wheel/playa_pdf-'], packages: ['opencv-python'] },
};
/** Returns the LATER engine that a file is part of, or undefined. */
export const laterEngine = (path) => Object.keys(LATER).find((n) => LATER[n].wheels.some((w) => path.startsWith(w)));
const laterIn = (files) => new Set(Object.keys(files).map(laterEngine).filter(Boolean));

/**
 * files (or a promise of them): boot copies "site/..." to site-packages, installs "wheel/...",
 * and puts the other files under /repo.
 * If files contains the wheels of a LATER engine, boot installs that engine. The Node tests send all the wheels.
 * programs: {name: program} for engines.js programRunner.
 */
export async function boot(opts) {
  globalThis.runProgram ??= programRunner(opts.programs);
  globalThis.canPause = canPause;
  const py = await interpreter(opts);
  return { py, glue: py.pyimport('browser'), added: laterIn(await opts.files) };
}

/** Installs each LATER engine in names that is not installed. fetch(path) returns the bytes of one file of the engine. */
export async function add(ctx, names, paths, fetch, downloading) {
  for (const name of names.filter((n) => LATER[n] && !ctx.added.has(n))) {
    downloading(name);
    const mine = paths.filter((p) => laterEngine(p) === name);
    const [files] = await Promise.all([
      Promise.all(mine.map(async (p) => [p, await fetch(p)])).then(Object.fromEntries),
      ctx.py.loadPackage(LATER[name].packages, { messageCallback: () => {} }),
    ]);
    await install(ctx.py, files);
    ctx.added.add(name);
  }
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
  files = await files; // awaited late: downloads alongside Pyodide's packages
  const later = [...laterIn(files)];
  await py.loadPackage(later.flatMap((n) => LATER[n].packages), { messageCallback: () => {} });
  log('Installing the engines');
  await install(py, files);
  py.FS.mkdirTree('/work/out');
  return py;
}

/** Writes files to the locations that the boot doc gives. Installs the wheels in files. */
async function install(py, files) {
  const site = py.runPython('import site; site.getsitepackages()[0]');
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
  await py.runPythonAsync(`
import micropip
await micropip.install(${JSON.stringify(wheels)}, deps=False)
`);
  for (const w of wheels) py.FS.unlink(w.slice('emfs:'.length)); // installed; frees the memory
  py.runPython('import importlib; importlib.invalidate_caches()'); // so that find_spec finds an engine that add() installed
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
async function cli({ py, glue }, cmd, doc, argv, progress) {
  const path = documents.get(doc);
  if (!path) throw new Error('This PDF is no longer open; choose it again.');
  const args = py.toPy([cmd, path, ...argv]);
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

/** engines: names to run, or undefined for the defaults */
const only = (engines) => (engines ? ['--engines', engines.join(',')] : []);
const pagesArg = (pages) => (pages ? ['--pages', pages] : []);
const recipeArg = (recipe) => (recipe ? ['--recipe', recipe] : []);

/** the CLI's show view of one page: every voted cell boxed, as self-contained HTML */
export async function show(ctx, { doc, page, recipe, engines }) {
  const out = '/work/grid.html';
  const [code, stdout] = await cli(ctx, 'show', doc, ['--page', String(page), '-o', out, '--force', '-q', ...only(engines), ...recipeArg(recipe)]);
  if (code) throw new Error(stdout.trim() || `pdfexorcist show stopped with exit code ${code}`);
  return { html: ctx.py.FS.readFile(out, { encoding: 'utf8' }) };
}

/** pdfexorcist charts; returns the summary and the CSV text */
export async function charts(ctx, { doc, pages }) {
  const out = '/work/out/charts.csv';
  const flags = pagesArg(pages);
  const [, stdout] = await cli(ctx, 'charts', doc, ['-o', out, '--json', '--force', ...flags]);
  const summary = JSON.parse(stdout);
  return { summary, table: summary.outputs && ctx.py.FS.readFile(out, { encoding: 'utf8' }), flags };
}

/** recipe: a shipped recipe's short name; returns the summary, and the table and review as text */
export async function extract(ctx, { doc, recipe, pages, engines, progress }) {
  const { py } = ctx;
  for (const f of ls(py.FS, '/work/out')) py.FS.unlink(`/work/out/${f}`);
  const flags = [...pagesArg(pages), ...only(engines), ...recipeArg(recipe)];
  const argv = ['-o', '/work/out/', '--json', '-q', '--force', ...flags];
  const [, stdout] = await cli(ctx, 'extract', doc, argv, progress);
  const summary = JSON.parse(stdout);
  const text = (path) => path && py.FS.readFile(path, { encoding: 'utf8' });
  return { summary, table: text(summary.outputs?.[0]), review: text(summary.review), flags };
}
