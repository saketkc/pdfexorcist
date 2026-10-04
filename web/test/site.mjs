// node test/site.mjs http://127.0.0.1:8765/ [screenshot dir]; CHROME overrides the path

import { execFile, execFileSync } from 'node:child_process';
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { chromium } from 'playwright-core';

const ROOT = fileURLToPath(new URL('../..', import.meta.url));
const examples = JSON.parse(readFileSync(join(ROOT, 'web/examples.json'), 'utf8'));

async function native(ex) {
  const dir = mkdtempSync(join(tmpdir(), 'site-'));
  try {
    copyFileSync(join(ROOT, ex.pdf), join(dir, 'doc.pdf'));
    let out;
    try {
      const args = ['run', 'pdfexorcist', 'extract', join(dir, 'doc.pdf'), '--recipe', ex.recipe, '--json', '-q'];
      out = (await promisify(execFile)('uv', args, { cwd: ROOT })).stdout;
    } catch (e) {
      out = e.stdout; // exit 1 when a check fails
    }
    const { total, verified, unresolved, failed_checks } = JSON.parse(out).cells;
    return { cells: { verified, total, unresolved, failed_checks }, csv: readFileSync(join(dir, 'doc.csv'), 'utf8') };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

const url = process.argv[2] ?? 'http://127.0.0.1:8765/';
const shots = process.argv[3];
const CHROME = process.env.CHROME ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
if (shots) mkdirSync(shots, { recursive: true });

async function longPdf(page) {
  const dir = mkdtempSync(join(tmpdir(), 'site-'));
  try {
    const pdf = join(dir, 'long.pdf');
    execFileSync('uv', ['run', 'python', '-c', `
import pymupdf
src = pymupdf.open(${JSON.stringify(join(ROOT, examples[0].pdf))})
out = pymupdf.open()
while out.page_count < 99: out.insert_pdf(src)
out.save(${JSON.stringify(pdf)})`], { cwd: ROOT });
    await page.locator('#file').setInputFiles(pdf);
    await page.waitForSelector('text=99 pages.');
    await page.waitForSelector('#pages-view figure'); // the count arrives before pages
    await page.locator('#pages-view figure[data-i="23"]').scrollIntoViewIfNeeded(); // pages render on scroll
    await page.waitForSelector('#pages-view figure[data-i="23"] canvas');
    await page.locator('text=Read pages 1–5').click();
    await page.waitForSelector('.progress li.done', { timeout: 300_000 });
    await page.waitForSelector('#result .say >> text=/values agreed/', { timeout: 300_000 });
    const sub = (await page.locator('#result .sub').allInnerTexts()).join(' ');
    console.log(`long PDF, pages 1-5: ${await page.locator('#result .say').innerText()} ${sub}`);
    if (!sub.includes('Pages 1-5')) failures.push('long PDF: the sample did not read pages 1-5');
    await page.locator('.alert.calm >> text=Read all 99 pages').click();
    await page.waitForSelector('.progress li >> text=/page \\d+ of 99/', { timeout: 300_000 });
    await page.locator('text=Stop').click();
    await page.waitForSelector('#result .say >> text=Stopped.');
    await page.waitForSelector('#dots.ready', { state: 'attached', timeout: 300_000 });
    console.log('long PDF: Stop worked and the engines came back');
    await page.locator('#back').click();
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

const natives = examples.map(native); // runs while Chrome boots the engines
const browser = await chromium.launch({ executablePath: CHROME });
const downloaded = async (page, button) => {
  const [d] = await Promise.all([page.waitForEvent('download'), page.locator(button).click()]);
  return readFileSync(await d.path(), 'utf8');
};
const failures = [];
try {
  const page = await browser.newPage({ colorScheme: 'light', viewport: { width: 1360, height: 900 }, acceptDownloads: true });
  page.on('pageerror', (e) => failures.push(`page error: ${e.message}`));
  page.on('console', (m) => m.type() === 'error' && failures.push(`console: ${m.text()}`));
  await page.goto(url);
  await page.waitForFunction(
    () => document.querySelector('#dots.ready') || /could not start/.test(document.querySelector('#engine-status').textContent),
    null,
    { timeout: 600_000 },
  );
  if (!(await page.locator('#dots.ready').count())) throw new Error(await page.locator('#engine-status').innerText());
  await page.waitForFunction((n) => document.querySelectorAll('.thumb canvas').length === n, examples.length);
  if (shots) await page.screenshot({ path: `${shots}/home-light.png`, fullPage: true });
  for (let i = 0; i < examples.length; i++) {
    await page.locator('.example').nth(i).click();
    await page.waitForSelector('#result .say >> text=/values agreed/', { timeout: 300_000 });
    await page.waitForSelector('#pages-view canvas');
    const say = await page.locator('#result .say').innerText();
    const sub = (await page.locator('#result .sub').allInnerTexts()).join(' ');
    const rows = await page.locator('#result table').first().locator('tbody tr').count();
    const voters = await page.locator('.voters li').count();
    const num = (re, text) => Number((text.match(re)?.[1] ?? '0').replaceAll(',', ''));
    const all = num(/^All ([\d,]+) values agreed/, say);
    const web = {
      verified: all || num(/^([\d,]+) of/, say),
      total: all || num(/of ([\d,]+) values/, say),
      unresolved: num(/([\d,]+) without agreement/, say),
      failed_checks: num(/([\d,]+) values? failed/, sub),
    };
    const want = await natives[i];
    console.log(`${examples[i].title}: ${say} ${sub} | ${rows} table rows | ${voters} engines`);
    const csv = await downloaded(page, 'text=Download CSV');
    console.log(`  browser ${JSON.stringify(web)}\n  native  ${JSON.stringify(want.cells)}`);
    console.log(`  CSV ${csv === want.csv ? 'identical to' : 'DIFFERS from'} the CLI's (${csv.length} bytes)`);
    if (voters !== 5) failures.push(`example ${i}: ${voters} engines ran`);
    if (!rows) failures.push(`example ${i}: the table is empty`);
    if (JSON.stringify(web) !== JSON.stringify(want.cells)) failures.push(`example ${i}: counts differ from the CLI`);
    if (csv !== want.csv) failures.push(`example ${i}: CSV differs from the CLI`);
    if (shots) await page.screenshot({ path: `${shots}/example-${i}.png`, fullPage: true });
    await page.locator('#back').click();
  }
  await longPdf(page);
  if (shots) {
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.screenshot({ path: `${shots}/home-dark.png`, fullPage: true });
  }
} catch (e) {
  failures.push(e.message);
} finally {
  await browser.close();
}
for (const f of failures) console.log('FAIL', f);
process.exit(failures.length ? 1 : 0);
