// Long lists, a page at a time.
//
// Pages, not a list that grows: the same number of rows whichever page is
// open, so the footer never ends up a screen below the head (23 Sep). The
// lists are read in an order that means something (bugs by severity,
// findings by rule, the roadmap by the order the work has to happen in), so
// a page is named by the rows on it and never by a number. What is tested
// here is that the helper is wired to every list, that a short list is left
// whole, and that turning a page never drops rows or their behavior.
import { launch, newPage, ok, done, ready, URL, DIR, nbGo } from './lib.mjs';
import { writeFileSync, readFileSync, readdirSync, existsSync, mkdirSync, rmSync } from 'node:fs';

// alpha's tracker, made long enough to page. Written straight to the state
// file: this is about the list's length, not about how reports get filed.
// The file may not exist yet: nothing in this harness has filed a bug.
const F = `${DIR}/state/bugs.json`;
const d = existsSync(F) ? JSON.parse(readFileSync(F, 'utf8')) : {};
d.projects = d.projects || {};
d.projects.alpha = Array.from({ length: 40 }, (_, i) => ({
  id: i + 1, title: `report number ${i + 1}`, severity: 'medium',
  status: 'open', at: 1750000000 + i, by: 'you',
}));
writeFileSync(F, JSON.stringify(d));

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);
await page.evaluate(n => openNotebook(n), 'alpha');
await page.waitForSelector('#roadmapList, .nb', { timeout: 20000 });
await nbGo(page, 'bugs');
await page.waitForSelector('#bugList .bug', { timeout: 20000 });

const state = () => page.evaluate(() => {
  const l = [...document.querySelectorAll('#bugList')].find(x => x.offsetParent);
  const rows = [...l.querySelectorAll(':scope > .bug')];
  const bar = l.querySelector('.pagemore');
  return { total: rows.length, shown: rows.filter(r => !r.hidden).length,
           bars: l.querySelectorAll('.pagemore').length,
           text: bar ? bar.textContent.replace(/\s+/g, ' ').trim() : '' };
});

let st = await state();
ok(st.total === 40 && st.shown === 25,
   'a list past the threshold shows its first page, not all of it');
ok(/25 of 40 reports/.test(st.text) && st.bars === 1 && /Show more/.test(st.text),
   '...with one quiet foot saying how much of it is on screen, and a Show more');

// More as the reader gets there (the operator, 16 Oct): the foot scrolled
// into view brings the rest under the rows already there, with no press.
const top = await page.$eval('#bugList:visible .bug:nth-of-type(1)', e => e.getBoundingClientRect().top);
await page.$eval('#bugList:visible .pagemore', e => e.scrollIntoView({ block: 'end' }));
await page.waitForFunction(() => { const l = [...document.querySelectorAll('#bugList')].find(x => x.offsetParent);
  return [...l.querySelectorAll(':scope > .bug')].every(r => !r.hidden); }, null, { timeout: 5000 });
st = await state();
ok(st.shown === 40 && st.bars === 0, `scrolled to its foot the rest arrives by itself, and with all of it shown there is no foot (${JSON.stringify(st)})`);
ok(!await page.$eval('#bugList:visible .bug:nth-of-type(1)', e => e.hidden) && Number.isFinite(top),
   '...the rows that were there stay, the list growing under them');

// The rows revealed are real rows, not decoration: a report opened after
// they arrive still opens.
await page.click('#bugList:visible .bug:nth-of-type(30) > summary');
ok(await page.$eval('#bugList:visible .bug:nth-of-type(30)', e => e.open),
   'a row that arrived still behaves like a row');

// Redrawing keeps what was shown rather than cutting back to the first page:
// a list that repaints under a poll must not take the reader's place.
await page.evaluate(() => {
  const l = [...document.querySelectorAll('#bugList')].find(x => x.offsetParent);
  paginate(l, ':scope > .bug', { key: 'bugList', noun: 'reports' });
});
st = await state();
ok(st.shown === 40, 'a redraw keeps what had been shown');

// A short list is left whole: a footer hiding one row is a click for
// nothing, which is why the threshold has slack in it. Waited on the view
// rather than the list: an empty list is a zero-height div, which is never
// ":visible" however correctly it is being shown.
await nbGo(page, 'roadmap');
await page.waitForFunction(() => {
  const v = [...document.querySelectorAll('.nbview[data-view="roadmap"]')]
    .find(x => !x.hidden);
  return !!v;
}, { timeout: 20000 });
ok(await page.evaluate(() => {
  const v = [...document.querySelectorAll('.nbview[data-view="roadmap"]')]
    .find(x => !x.hidden);
  return v && !v.querySelector('.pagemore');
}), 'a short list gets no footer at all');

// Every list is wired, not just the one driven above, and with the row
// selector its own renderer actually produces. A wrong selector fails
// silently (nothing to hide, so no footer), which is worth pinning. Read from
// the file rather than the DOM: exact, instead of a guess about what
// innerHTML happens to contain. The page and every notebook view file, since
// a view's renderer lives in its own nb-*.js now (R60).
const src = ['../index.html', ...readdirSync(new globalThis.URL('..', import.meta.url))
    .filter(f => /^(nb|page|tab)-.*\.js$/.test(f)).map(f => '../' + f)]
  .map(f => readFileSync(new globalThis.URL(f, import.meta.url), 'utf8')).join('\n');
for (const [what, call] of [
  // Less what the list's band leaves out (R254 step 1), so a page holds
  // what is shown.
  ['the roadmap', 'paginate($("roadmapList"), ":scope > .grp:not(.off)"'],
  ['memory', 'paginate($("memList"), ":scope > .mem"'],
  ['bugs', 'paginate(list, ":scope > .bug:not(.off)"'],
  // ...in the Files section's body, since the files are a section (6 Oct).
  ['artifacts', 'paginate(list.querySelector(\'[data-sect="artifacts:files"] > .body\'), ":scope > .artrow"'],
  // .rule, which is what findingsRulesHtml emits. This line said .grp (the
  // other renderer's class), so the check that exists to catch a silently
  // wrong selector was pinning one: analysis drew every rule at once and the
  // test agreed with it.
  ['analysis', 'paginate(list, ":scope > .rule"'],
  ['every history', 'paginate(pane, ":scope > .hist"'],
]) ok(src.includes(call), what + ' is paged, by the rows it really renders');

// ...and the Jobs tab, which lives in its own file. It is the list that grows
// without bound (every compose action, exec and agent update stays on it),
// so it was the one most in need of paging and the one that had none.
{
  const jsrc = readFileSync(new globalThis.URL('../tab-jobs.js', import.meta.url), 'utf8');
  ok(jsrc.includes('paginate(tbl, ":scope > .jbrow"'),
     'jobs are paged, by the rows the tab really renders');
}

// ---- one bucket per notebook, not one for all of them ----------------------
// A notebook is a CLONE of one template, so every id inside it belongs to
// every open notebook at once. The paging state was keyed on those ids, which
// made a single bucket shared by all of them, and the branch that leaves a
// short list whole DELETES its key. So a short artifacts list in one notebook
// wiped a long one's page in another, and the reported symptom was paging
// not working: it turned, then snapped back on the next redraw, a second
// or two later.
{
  mkdirSync(`${DIR}/ws/alpha/dist/pagemany`, { recursive: true });
  for (let i = 1; i <= 34; i++)
    writeFileSync(`${DIR}/ws/alpha/dist/pagemany/f-${i}.bin`, 'x');
  mkdirSync(`${DIR}/ws/beta/dist`, { recursive: true });
  for (let i = 1; i <= 3; i++) writeFileSync(`${DIR}/ws/beta/dist/b-${i}.bin`, 'x');
  await page.evaluate(() => { openNotebook('alpha'); openNotebook('beta'); });
  await page.waitForSelector('.nb[data-project="beta"]', { timeout: 20000 });
  await page.evaluate(() => { for (const p of ['alpha', 'beta']) getNotebook(p)?.view('artifacts'); });
  await page.waitForFunction(() => (document.querySelectorAll(
    '.nb[data-project="alpha"] .nbview[data-view="artifacts"] .artrow') || []).length > 25,
    null, { timeout: 20000 });
  const shown = () => page.evaluate(() => {
    const rows = [...document.querySelectorAll(
      '.nb[data-project="alpha"] .nbview[data-view="artifacts"] .artrow')];
    return rows.filter(r => !r.hidden).length;
  });
  await page.evaluate(() => document.querySelector(
    '.nb[data-project="alpha"] .nbview[data-view="artifacts"] .pagemore .next')?.click());
  const opened = await shown();
  ok(opened === 34, `Show more brings the rest, all 34 files (${opened} rows)`);
  // beta's SHORT list redraws, which is all a poll does on a box where
  // another project's view keeps moving.
  await page.evaluate(() => { const n = getNotebook('beta'); n?.view('bugs'); n?.view('artifacts'); });
  await page.evaluate(() => getNotebook('alpha')?.view('artifacts'));
  await page.waitForTimeout(400);
  ok(await shown() === opened,
     `...and a short list in another notebook does not turn it back (${await shown()} of ${opened})`);
  rmSync(`${DIR}/ws/alpha/dist/pagemany`, { recursive: true, force: true });
  rmSync(`${DIR}/ws/beta/dist`, { recursive: true, force: true });
}

ok((await page.errors).length === 0, 'no console errors from paging');
await done(browser);
