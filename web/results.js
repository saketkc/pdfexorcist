import { button, el, fmt, minutes, plural } from './ui.js';

const named = (path) => path.split('/').pop(); // the names the CLI wrote
const quote = (a) => (/^[\w@%+=:,./-]+$/.test(a) ? a : `'${a.replaceAll("'", `'\\''`)}'`);

/** the run as a CLI line; engines are named since the site's defaults differ from the CLI's */
function command(args, more) {
  const line = ['pdfexorcist', ...args].map(quote).join(' ');
  return el('div', { className: 'cli' },
    el('p', { className: 'sub' }, 'Run this on your computer to get the same result:'),
    el('pre', {}, el('code', {}, line)),
    button('button quiet', (e) => navigator.clipboard?.writeText(line).then(() => (e.target.textContent = 'Copied')), 'Copy'),
    el('p', { className: 'sub' }, 'Other options:'),
    el('ul', {}, more.map(([flag, what]) => el('li', {}, el('code', {}, flag), ` ${what}`))));
}

const refused = (s) => [el('p', { className: 'say' }, s.error), s.hint ? el('p', { className: 'sub' }, s.hint) : null];

export function outcome(res, job, seconds, pane, again, openGrid) {
  const s = res.summary;
  if (s.error) return refused(s);
  const c = s.cells;
  const { table, review: reviewCsv } = res;
  const review = reviewCsv && parseCsv(reviewCsv);
  const share = c.total ? Math.round((1000 * c.verified) / c.total) / 10 : 0;
  const failedRules = Object.entries(s.checks ?? {}).filter(([, n]) => n > 0);
  const used = s.engines?.used ?? {};
  const toCheck = review ? reviewPages(review) : [];
  const skipped = s.engines?.skipped ?? {};

  return [
    el('p', { className: 'say' },
      c.unresolved
        ? [el('b', { className: 'ok' }, fmt(c.verified)), ` of ${fmt(c.total)} values agreed (${share}%); `,
            el('b', { className: 'no' }, fmt(c.unresolved)), ' without agreement, listed under Cells to check.']
        : ['All ', el('b', { className: 'ok' }, fmt(c.total)), ' values agreed.']),
    agreement(s.agreement, Object.keys(used).length),
    el('p', { className: 'sub' },
      s.checks_run?.length
        ? c.failed_checks
          ? `Arithmetic checks: ${plural(c.failed_checks, 'value')} failed.`
          : `Arithmetic checks passed.`
        : 'No arithmetic checks.',
      job.pages ? ` Pages ${job.pages},` : '',
      ` ${seconds.toFixed(1)} s.`),
    again
      ? el('div', { className: 'alert calm' },
          'A sample. ',
          button('link', again.read, `Read all ${fmt(job.count)} pages`),
          `: about ${minutes(again.seconds)}, at this sample's speed.`)
      : null,
    toCheck.length
      ? el('div', { className: 'check-pages' },
          el('span', {}, 'Pages to check: '),
          toCheck.map(([page, n]) =>
            Object.assign(button('chip', () => pane.show(page), `${page}`), { title: `${plural(n, 'cell')} to check` })))
      : null,
    failedRules.length
      ? el('div', { className: 'alert' },
          el('b', {}, 'Check failed. '),
          'The engines agree on what is printed, but the printed numbers do not add up:',
          el('ul', {}, failedRules.map(([rule, n]) => el('li', {}, `${rule}: ${plural(n, 'value')}`))))
      : null,
    el('div', { className: 'actions' },
      table ? button('button', () => download(named(s.outputs[0]), table), 'Download CSV') : null,
      review
        ? button('button quiet', () => download(named(s.review), reviewCsv), 'Download cells to check')
        : null),
    gridControl(toCheck[0]?.[0] ?? s.pages?.[0] ?? 1, job.count, openGrid),
    Object.keys(skipped).length
      ? el('p', { className: 'sub' }, Object.entries(skipped).map(([n, why]) => `${n} did not run: ${why}. `))
      : null,
    el('ul', { className: 'voters', ariaLabel: 'Engines' },
      Object.entries(used).map(([n, readings]) => el('li', {}, el('b', {}, n), ` ${fmt(readings)} readings`))),
    command(['extract', job.name, '-o', 'out/', ...res.flags], [
      ['-o tables.xlsx', 'writes Excel; .parquet and .json work too.'],
      ['--layout cells', 'writes one row per cell, with each engine’s reading.'],
      ['--ocr', 'also reads the page images, for scans.'],
      ['-k N', 'sets how many engines must agree on a value.'],
      ['-j N', 'runs up to N engines at the same time.'],
      [`pdfexorcist show ${quote(job.name)} --page N`, 'draws a box on each voted cell of page N.'],
    ]),
    table ? [el('h3', {}, 'Table'), grid(table)] : null,
    review ? [el('h3', {}, 'Cells to check'), reviewGrid(review)] : null,
  ];
}

/** pdfexorcist charts result: values are estimates, so no vote counts */
export function chartsOutcome(res, job, seconds) {
  const s = res.summary;
  if (s.error) return refused(s);
  return [
    el('p', { className: 'say' }, el('b', { className: 'ok' }, fmt(s.points)), ` points from ${plural(s.charts, 'chart')}.`),
    el('p', { className: 'sub' },
      s.status?.estimated ? 'Values of drawn charts are read from where the line is drawn: ± gives how far off each can be. ' : '',
      s.status?.verified || s.status?.unresolved ? 'Values printed in chart pictures are read by OCR engines and voted; a blank cell had no agreement. ' : '',
      job.pages ? ` Pages ${job.pages},` : '', ` ${seconds.toFixed(1)} s.`),
    s.skipped.length
      ? el('div', { className: 'alert' },
          el('b', {}, 'Charts left out. '),
          el('ul', {}, s.skipped.map((k) => el('li', {}, `Page ${k.page}, chart ${k.chart}: ${k.reason}`))))
      : null,
    el('div', { className: 'actions' }, button('button', () => download(named(s.outputs[0]), res.table), 'Download CSV')),
    command(['charts', job.name, '-o', named(s.outputs[0]), ...res.flags], [
      ['-o points.json', 'writes JSON; .parquet works too.'],
      ['--recipe NAME', 'reads chart pictures with the settings in a recipe’s [charts] section.'],
    ]),
    chartTables(res.table),
  ];
}

/** one table per chart, laid out as the chart: a row per series, a column per category */
function chartTables(csv) {
  const [head, ...rows] = parseCsv(csv);
  const points = rows.map((r) => Object.fromEntries(head.map((h, i) => [h, r[i]])));
  return [...Map.groupBy(points, (p) => `${p.page} ${p.chart}`).values()].map((chart) => {
    const pm = Number(chart[0].pm); // NaN for a chart picture: its values are voted
    const digits = pm > 0 ? Math.max(0, Math.min(20, 1 - Math.floor(Math.log10(pm)))) : 20; // as charts._round
    const { format } = new Intl.NumberFormat('en-IN', { maximumFractionDigits: digits });
    const cats = [...new Set(chart.map((p) => p.category))];
    const series = [...Map.groupBy(chart, (p) => p.series)].map(([name, pts]) => [name, new Map(pts.map((p) => [p.category, p.value]))]);
    return [
      el('h3', {}, chart[0].title || 'Untitled chart'),
      el('p', { className: 'sub' }, `Page ${chart[0].page}.`, pm > 0 ? ` Each value ± ${format(pm.toPrecision(2))}.` : ' Voted by OCR engines.'),
      capped(['Series', ...cats], series, ([name, values]) =>
        el('tr', {}, el('td', { className: 'key' }, name),
          cats.map((c) => el('td', {}, values.get(c) ? format(values.get(c)) : null)))), // blank: unresolved
    ];
  });
}

/** custom parsers may have no page column */
function reviewPages([head, ...rows]) {
  const at = head.indexOf('page');
  if (at < 0) return [];
  const n = new Map();
  for (const r of rows) if (/^\d+$/.test(r[at])) n.set(Number(r[at]), (n.get(Number(r[at])) ?? 0) + 1);
  return [...n].sort((a, b) => a[0] - b[0]);
}

/** kept values by how many engines read them identically */
function agreement(counts = {}, engines) {
  const levels = Object.entries(counts).sort((a, b) => b[0] - a[0]); // JS orders numeric keys ascending
  if (!levels.length) return null;
  return el('p', { className: 'sub' },
    'Engines agreeing on each kept value: ',
    levels.map(([n, cells]) => `${n} of ${engines} on ${fmt(cells)}`).join(', '), '.');
}

/** page number and a button: the CLI's show view, every voted cell boxed, in a new tab */
function gridControl(first, count, openGrid) {
  const page = el('input', { type: 'number', min: 1, max: count, value: first, ariaLabel: 'Page' });
  return el('form', { className: 'pick', onsubmit: (e) => (e.preventDefault(), openGrid(Number(page.value))) },
    el('label', {}, 'Grid for page ', page),
    el('button', { className: 'button quiet', type: 'submit' }, 'See the grid'));
}

const SHOWN = 500; // rows drawn at first; thousands would stall the page

function capped(head, rows, row) {
  const body = el('tbody', {}, rows.slice(0, SHOWN).map(row));
  const rest = rows.length - SHOWN;
  const more = rest > 0 && button('button quiet', () => (body.append(...rows.slice(SHOWN).map(row)), more.remove()), `Show all ${fmt(rows.length)} rows`);
  return [
    el('div', { className: 'table', tabIndex: 0 },
      el('table', {}, el('thead', {}, el('tr', {}, head.map((h) => el('th', { scope: 'col' }, h)))), body)),
    more || null,
  ];
}

function grid(csv) {
  const [head, ...rows] = parseCsv(csv);
  const cell = (v, i) => {
    if (v === '') return el('td', { className: 'blank', title: 'The engines disagreed: see Cells to check' });
    return el('td', i === 0 ? { className: 'key' } : {}, v);
  };
  return capped(head, rows, (r) => el('tr', {}, r.map(cell)));
}

function reviewGrid([head, ...rows]) {
  const keys = Array.from({ length: head.indexOf('value') - 1 }, (_, i) => i + 1);
  const [reason, votes, dissent] = ['reason', 'votes', 'dissent'].map((n) => head.indexOf(n));
  return capped([...keys.map((i) => head[i]), 'Why', 'What the engines read'], rows, (r) =>
    el('tr', {},
      keys.map((i) => el('td', { className: 'key' }, r[i])),
      el('td', { className: 'key' }, r[reason]),
      el('td', { className: 'votes' }, r[votes], r[dissent] ? ` (${r[dissent].replaceAll('|', ', ')})` : '')));
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') cell += c, i++;
      else if (c === '"') quoted = false;
      else cell += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') row.push(cell), (cell = '');
    else if (c === '\n') row.push(cell), rows.push(row), (row = []), (cell = '');
    else if (c !== '\r') cell += c;
  }
  if (cell || row.length) row.push(cell), rows.push(row);
  return rows;
}

function download(name, text) {
  const a = el('a', { href: URL.createObjectURL(new Blob([text], { type: 'text/csv' })), download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
