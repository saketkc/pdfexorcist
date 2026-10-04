// previews run in their own worker so they never wait behind an extraction

import { Client } from './client.js';
import { bytes, get, wasm } from './net.js';
import { outcome } from './results.js';
import { button, draw, el, failure, fill, fmt, minutes, plural } from './ui.js';

const $ = (id) => document.getElementById(id);
const MAX_BYTES = 200e6; // Pyodide copies the PDF several times within 4 GB
const LONG = 20; // pages; past this, offer a sample first
const SECONDS_PER_PAGE = 1.8; // all five engines, measured on a fact sheet

// ---- the workers

const INITIAL = { ready: false, failed: null, jspi: true, status: 'Loading the engines…' };
let engines = INITIAL;
const pdfium = wasm('vendor/pdfium.wasm'); // compiled once, shared by both workers
const init = () => pdfium.then((m) => ({ pdfium: m }));

const worker = new Client('./worker.js', {
  init,
  onStatus: (data) => {
    if (data.type === 'restart') engines = INITIAL;
    else if (data.type === 'status') engines = { ...engines, status: `${data.text}…` };
    else if (data.type === 'ready') engines = { ...engines, ready: true, jspi: data.jspi };
    else if (data.type === 'failed') engines = { ...engines, failed: `The engines could not start: ${data.message}` };
    showEngines();
  },
});
const previewer = new Client('./preview.js', { init });

function showEngines() {
  const dots = $('dots');
  dots.className = `dots ${engines.ready ? 'ready' : engines.failed ? '' : 'busy'}`;
  $('engine-status').textContent = engines.failed
    ? engines.failed
    : engines.ready && !engines.jspi
      ? 'Ready, without pdftotext: it needs Chrome 137, Safari 27 or Firefox 153.'
      : engines.ready
        ? 'Ready: pdftotext, pdfplumber, PyMuPDF, PDFium, Camelot.'
        : `${engines.status} 60 MB on the first visit, cached after.`;
}
showEngines();

// ---- home

async function firstPage(pdf, width) {
  const { doc } = await previewer.ask({ open: pdf });
  try {
    const { pages } = await previewer.ask({ doc, first: 0, max: 1, width });
    return draw(pages[0]);
  } finally {
    previewer.ask({ close: doc });
  }
}

function addExample(ex) {
  const name = ex.pdf.split('/').pop();
  const pdf = bytes(`samples/${name}`);
  const thumb = el('span', { className: 'thumb' });
  const open = async () => run({ kicker: ex.kicker, title: ex.title, pdf: await pdf, name, recipe: ex.recipe });
  $('examples').append(el('li', {}, button('example', open,
    thumb,
    el('span', {},
      el('span', { className: 'kicker' }, ex.kicker),
      el('span', { className: 'title' }, ex.title),
      el('span', { className: 'blurb' }, ex.blurb)),
    el('span', { className: 'go', ariaHidden: 'true' }, '→'))));
  pdf.then((p) => firstPage(p, 224)).then((canvas) => thumb.append(canvas)).catch(() => {});
}

get('examples.json')
  .then((r) => r.json())
  .then((list) => list.forEach(addExample));

get('files.json')
  .then((r) => r.json())
  .then((files) => {
    for (const [path] of files) {
      if (path.startsWith('examples/') && path.endsWith('.toml')) {
        $('recipe').append(el('option', { value: path }, path.slice('examples/'.length)));
      }
    }
  });

const file = $('file');
file.onchange = () => file.files[0] && openFile(file.files[0]);
const drop = $('drop');
drop.ondragover = (e) => {
  e.preventDefault();
  drop.classList.add('over');
};
drop.ondragleave = () => drop.classList.remove('over');
drop.ondrop = (e) => {
  e.preventDefault();
  drop.classList.remove('over');
  const f = [...e.dataTransfer.files].find((f) => /\.pdf$/i.test(f.name) || f.type === 'application/pdf');
  if (f) openFile(f);
};

async function openFile(f) {
  if (f.size > MAX_BYTES) {
    $('engine-status').textContent = `${f.name} is ${Math.round(f.size / 1e6)} MB. The limit here is ${MAX_BYTES / 1e6} MB; the command-line tool has none.`;
    return;
  }
  const pdf = new Uint8Array(await f.arrayBuffer());
  run({
    kicker: 'Your PDF',
    title: f.name,
    pdf,
    name: f.name,
    recipe: $('recipe').value || undefined,
    pages: $('pages').value.trim() || undefined,
  });
  file.value = '';
}

// ---- views

function show(view) {
  $('home').hidden = view !== 'home';
  $('work').hidden = view !== 'work';
  $(view).classList.remove('fade');
  void $(view).offsetWidth;
  $(view).classList.add('fade');
  window.scrollTo({ top: 0 });
}
$('back').onclick = () => {
  history.pushState(null, '', './');
  show('home');
};
window.onpopstate = () => show('home');

let active = null; // the run on screen; a new one aborts it

async function run(job) {
  active?.abort();
  const { signal } = (active = new AbortController());
  history.pushState(null, '', '#result');
  show('work');
  $('doc-kicker').textContent = job.kicker;
  $('doc-title').textContent = job.title;
  fill($('result')); // else the previous result shows under the new title
  const pane = pagesPane(job.pdf, signal);
  let count;
  try {
    count = await pane.ready;
  } catch (e) {
    if (!signal.aborted) fill($('result'), failure('This file could not be opened as a PDF.', e.message));
    return;
  }
  if (signal.aborted) return;
  job = { ...job, count, doc: workerCopy(job, signal) };
  pane.pick = (page) => read({ ...job, pages: String(page), sample: false }, pane, signal);
  if (job.pages || count <= LONG) return read(job, pane, signal);
  const pick = (pages) => read({ ...job, pages, sample: Boolean(pages) }, pane, signal);
  const own = el('input', { placeholder: 'e.g. 12-15', ariaLabel: 'Pages to read', inputMode: 'numeric' });
  fill($('result'),
    el('p', { className: 'say' }, `${fmt(count)} pages.`),
    el('p', { className: 'sub' },
      `All of them take about ${minutes(count * SECONDS_PER_PAGE)} here. Try five first. For many long PDFs, the `,
      el('a', { href: 'cli/' }, 'command-line tool'), ' is faster.'),
    el('div', { className: 'actions' },
      button('button', () => pick('1-5'), 'Read pages 1–5'),
      button('button quiet', () => pick(undefined), `Read all ${fmt(count)} pages`)),
    el('form', { className: 'pick', onsubmit: (e) => (e.preventDefault(), own.value.trim() && pick(own.value.trim())) },
      el('label', {}, 'Other pages ', own),
      el('button', { className: 'button quiet', type: 'submit' }, 'Read')));
}

/** opened once per engine worker; closed when the run ends */
function workerCopy(job, signal) {
  let held = null; // {generation, doc}
  signal.addEventListener('abort', () => {
    if (held?.generation === worker.generation) held.doc.then((doc) => worker.ask({ close: doc })).catch(() => {});
  });
  return () => {
    if (held?.generation !== worker.generation) {
      held = { generation: worker.generation, doc: worker.ask({ open: job.pdf, name: job.name }).then((r) => r.doc) };
    }
    return held.doc;
  };
}

async function read(job, pane, signal) {
  const result = $('result');
  const stop = new AbortController();
  const view = progressView(() => {
    stop.abort();
    worker.restart(new Error('stopped'));
  });
  fill(result, view.node);
  const started = performance.now();
  let first; // the first page read; the estimate leaves out the engines' start-up
  const progress = (data) => {
    first ??= performance.now();
    view.update(data);
  };
  try {
    const doc = await job.doc();
    const res = await worker.ask({ doc, recipe: job.recipe, pages: job.pages }, { signal: AbortSignal.any([signal, stop.signal]), progress });
    if (res.cancelled) return;
    const pagesRead = res.summary.pages?.length || job.count;
    const again = job.sample
      ? { read: () => read({ ...job, pages: undefined, sample: false }, pane, signal),
          seconds: ((performance.now() - (first ?? started)) / 1000 / pagesRead) * job.count }
      : null;
    fill(result, outcome(res, job, (performance.now() - started) / 1000, pane, again, (page) => openGrid(job, page)));
  } catch (e) {
    if (signal.aborted) return;
    fill(result, stop.signal.aborted ? failure('Stopped.', 'The engines are restarting.') : failure('Something went wrong.', e.message));
  } finally {
    view.done();
  }
}

/** a tab opened now, inside the click, so pop-up blockers allow it; filled when ready */
async function openGrid(job, page) {
  const tab = window.open('', '_blank');
  if (!tab) return;
  tab.document.title = `Page ${page}`;
  tab.document.body.textContent = `Drawing the grid for page ${page}…`;
  try {
    const { html } = await worker.ask({ show: await job.doc(), page, recipe: job.recipe });
    tab.location = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
  } catch (e) {
    tab.document.body.textContent = e.message;
  }
}

/** ready resolves to the page count; pages render as they scroll into view */
function pagesPane(pdf, signal) {
  const pane = $('pages-view');
  fill(pane, el('p', { className: 'more' }, 'Opening the PDF…'));
  const opened = previewer.ask({ open: pdf });
  const figures = [];
  let queue = Promise.resolve(); // serialised: one PDFium document
  const render = (i) => {
    const f = figures[i];
    if (f.rendered) return f.rendered;
    f.rendered = queue = queue
      .then(async () => {
        const { doc } = await opened;
        const { pages } = await previewer.ask({ doc, first: i, max: 1, width: 900 }, { signal });
        f.firstChild.replaceWith(draw(pages[0]));
      })
      .catch(() => {});
    return f.rendered;
  };
  const observer = new IntersectionObserver(
    (entries) => entries.forEach((e) => e.isIntersecting && render(Number(e.target.dataset.i))),
    { root: pane, rootMargin: '1200px 0px' },
  );
  signal.addEventListener('abort', () => {
    observer.disconnect();
    opened.then(({ doc }) => previewer.ask({ close: doc })).catch(() => {});
  });
  const ready = opened.then(({ count }) => {
    for (let i = 0; i < count; i++) {
      const caption = el('figcaption', {}, `Page ${i + 1}`, button('link', () => api.pick?.(i + 1), 'Read this page'));
      const f = el('figure', {}, el('div', { className: 'slot' }), caption);
      f.dataset.i = i;
      figures.push(f);
    }
    fill(pane, figures);
    figures.forEach((f) => observer.observe(f));
    return count;
  });
  ready.catch(() => !signal.aborted && fill(pane, el('p', { className: 'more' }, 'No preview.')));
  const api = {
    pick: null, // set once the run can read; reads one page
    ready,
    async show(n) {
      const f = figures[n - 1];
      if (!f) return;
      f.scrollIntoView({ behavior: 'smooth', block: 'start' });
      await render(n - 1);
      f.classList.add('flash');
      setTimeout(() => f.classList.remove('flash'), 1600);
    },
  };
  return api;
}

/** 0.4 s, 12 s, 2:05 */
function took(ms) {
  const s = ms / 1000;
  if (s < 10) return `${s.toFixed(1)} s`;
  const whole = Math.round(s);
  return whole < 60 ? `${whole} s` : mmss(whole);
}

const mmss = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

function progressView(onStop) {
  const rows = new Map(); // a row appears as each engine starts
  const list = el('ul', { className: 'progress' });
  const status = el('p', { className: 'sub' });
  const clock = el('span', {});
  const started = performance.now();
  const tick = () => {
    const s = Math.round((performance.now() - started) / 1000);
    clock.textContent = mmss(s);
    status.textContent = engines.ready ? '' : `${engines.status} Reading starts when they are ready.`;
  };
  tick();
  const timer = setInterval(tick, 1000);
  const stop = button('button quiet', onStop, 'Stop');
  return {
    node: el('div', { className: 'running' },
      el('p', { className: 'say' }, 'Reading… ', clock),
      status,
      list,
      el('div', { className: 'actions' }, stop)),
    update({ engine, page, pages }) {
      let row = rows.get(engine);
      if (!row) {
        row = el('li', {}, el('b', {}, engine), el('span', {}), el('i', { className: 'meter' }));
        row.started = performance.now();
        rows.set(engine, row);
        list.append(row);
      }
      const time = took(performance.now() - row.started);
      row.children[1].textContent = page >= pages
        ? `${plural(pages, 'page')}, done in ${time}`
        : `page ${fmt(page + 1)} of ${fmt(pages)}, ${time}`;
      row.children[2].style.setProperty('--done', pages ? page / pages : 1);
      row.classList.toggle('done', page >= pages);
    },
    done: () => clearInterval(timer),
  };
}

// ---- theme

$('theme').onclick = () => {
  const root = document.documentElement;
  const dark = root.dataset.theme
    ? root.dataset.theme === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  root.dataset.theme = dark ? 'light' : 'dark';
  try {
    localStorage.setItem('theme', root.dataset.theme);
  } catch {}
};
