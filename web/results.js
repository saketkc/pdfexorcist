import { button, el, fmt, minutes, plural } from './ui.js';

export function outcome(res, job, seconds, pane, again, openGrid) {
  const s = res.summary;
  if (s.error) {
    return [
      el('p', { className: 'say' }, s.error),
      s.hint ? el('p', { className: 'sub' }, s.hint) : null,
    ];
  }
  const c = s.cells;
  const named = (path) => path.split('/').pop(); // the names the CLI wrote
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
    table ? [el('h3', {}, 'Table'), grid(table)] : null,
    review ? [el('h3', {}, 'Cells to check'), reviewGrid(review)] : null,
  ];
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
