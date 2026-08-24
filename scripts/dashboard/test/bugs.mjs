// The bug tracker: the notebook's third view, /api/bugs behind it, and the
// `bb bug` CLI a session drives. Write-through, unlike the roadmap — a bug
// report is a form submitted once, not a list curated in place — and nothing
// is ever deleted: a bug closes as fixed or wontfix, each with a note, because
// a closed bug is the record that stops the same report being chased twice.
import { launch, newPage, ok, done, ready, nbShown, URL, DIR } from './lib.mjs';
import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const BB = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'bb');
const bbBug = (...a) => execFileSync(BB, ['bug', ...a],
  { env: { ...process.env, BB_BUG_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } }).toString();
const FILE = `${DIR}/state/bugs.json`;
const read = () => existsSync(FILE)
  ? JSON.parse(readFileSync(FILE, 'utf8')).projects.alpha || [] : [];

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 900 } });
await page.goto(URL);
await ready(page);

// ---- the way in ----------------------------------------------------------
const row = n => `#projects .row:has(.name:text-is("${n}"))`;
await page.click(`${row('alpha')} [data-m]`);
await nbShown(page);
await page.click('.pane .nb .nbtabs [data-v="bugs"]');
await page.waitForFunction(() => /Nothing reported/.test(
  document.getElementById('bugHint')?.textContent || ''), { timeout: 15000 });
ok(true, 'the Bugs tab opens empty, and says where reports end up');

// ---- reporting one from the panel -----------------------------------------
await page.click('#bugAdd .link');
await page.waitForSelector('.bugform', { timeout: 10000 });
ok(await page.evaluate(() => document.activeElement?.tagName !== 'INPUT'),
   'the form opens without a cursor in it, like everything else here');
await page.fill('.bugform .bfTitle', 'the picker loses its selection on rotate');
await page.selectOption('.bugform .bfSev', 'high');
await page.fill('.bugform .bfArea', 'scripts/dashboard/index.html — the picker');
await page.fill('.bugform .bfRepro', '1. open the picker on a phone\n2. rotate');
await page.fill('.bugform .bfExpected', 'the selection survives');
await page.fill('.bugform .bfActual', 'it resets to the first entry');
await page.click('.bugform .bfGo');
await page.waitForSelector('#bugList .bug', { timeout: 10000 });
const b1 = read()[0];
ok(b1 && b1.title === 'the picker loses its selection on rotate'
   && b1.severity === 'high' && b1.status === 'open' && b1.by === 'you'
   && b1.repro === '1. open the picker on a phone\n2. rotate',
   'the report lands on disk with its fields, written through — no Save involved');
ok(await page.$eval('#bugList .bug .sev', el => el.textContent) === 'high',
   '...and the row leads with its severity, the way a memory leads with its type');

// ---- the session's half ----------------------------------------------------
bbBug('add', 'bb lint misses compose files in subdirectories', '--sev', 'low',
      '--area', 'scripts/bb', '--repro', 'put a compose file under tools/ and run bb lint');
ok(read().length === 2 && read()[1].by === 'claude',
   'a session files one through bb bug, marked as its own');
const listed = bbBug();
ok(/\b2\b.*compose files/.test(listed) && /\b1\b.*picker loses/.test(listed),
   'bb bug lists the open ones');
ok(/repro: put a compose file/.test(bbBug('show', '2')),
   'bb bug show gives one in full, fields and all');
bbBug('note', '2', 'the file list is built from names, not from content');
ok(/file list is built from names/.test(read()[1].notes || ''),
   'bb bug note appends what a session learned, dated, without replacing what was there');

const prompt = bbBug('--prompt');
ok(/#1 \[high\] the picker loses/.test(prompt) && /#2 \[low\]/.test(prompt),
   'the prompt block carries the open bugs, severity first');
ok(/bb bug show <n>/.test(prompt) && /bb bug add/.test(prompt),
   '...and tells a session how to read one and how to file one');

// ---- the GUI sees what the CLI wrote ---------------------------------------
await page.evaluate(() => notebooks.get('alpha').reloadBugs());
await page.waitForFunction(() => document.querySelectorAll('#bugList .bug').length === 2,
                           { timeout: 10000 });
ok(true, 'the tab picks up what a session filed');

// ---- closing one, with the note that is the point --------------------------
page.dialogs = [];
await page.evaluate(() => { window.prompt = () => 'the select re-measures on rotate now'; });
await page.click('#bugList .bug[data-id="1"] summary');
await page.click('#bugList .bug[data-id="1"] .bFix');
await page.waitForFunction(() => document.querySelector('#bugList .bug[data-id="1"] .bstat')?.textContent === 'fixed', { timeout: 10000 });
ok(read().find(b => b.id === 1).status === 'fixed'
   && read().find(b => b.id === 1).status_note === 'the select re-measures on rotate now',
   'marking one fixed asks what fixed it, and keeps the answer on the bug');
ok(!/picker loses/.test(bbBug()), '...and it leaves the open list');
ok(/\[fixed\]/.test(bbBug('all')), '...but never the tracker: bb bug all still has it');
ok(!/#1/.test(bbBug('--prompt')),
   '...and the next session is not handed a bug that is already fixed');

// Closed sinks below open, however new it is.
ok(await page.$$eval('#bugList .bug', ds => ds.map(d => d.dataset.id)).then(
     ids => ids[ids.length - 1] === '1'),
   'a closed bug sinks below the open ones');

// Reopen from the CLI — "the fix did not take" is a real answer.
bbBug('reopen', '1');
ok(read().find(b => b.id === 1).status === 'open'
   && !read().find(b => b.id === 1).status_note,
   'reopening clears the fixed note, since it turned out not to be true');
bbBug('fix', '1', 'this time with the resize listener');
ok(read().find(b => b.id === 1).status_note === 'this time with the resize listener',
   '...and closing again writes the new answer');

// ---- editing ---------------------------------------------------------------
bbBug('edit', '2', 'sev', 'medium');
ok(read().find(b => b.id === 2).severity === 'medium',
   'a session can re-grade a bug once it knows more');

// ---- the tracker's log -----------------------------------------------------
// Same bar, same rows as the roadmap's: search, a window, a cap. Filed,
// noted, fixed, reopened — with who and when, which the tracker's present
// tense cannot answer.
await page.click('#bugLog');
await page.waitForFunction(() => document.querySelectorAll('#bugHist .hist').length > 0,
                           { timeout: 10000 });
ok(await page.$eval('#bugList', el => el.hidden),
   'History swaps the list out, the way the roadmap\'s does');
const acts = await page.$$eval('#bugHist .hist .act', as => as.map(a => a.textContent));
ok(acts.includes('filed') && acts.includes('fixed') && acts.includes('noted')
   && acts.includes('reopened'),
   'the log carries the tracker\'s verbs: filed, noted, fixed, reopened');
await page.fill('#bugHistBar input', 'resize listener');
await page.waitForFunction(() => document.querySelectorAll('#bugHist .hist').length === 1,
                           { timeout: 10000 });
ok(await page.$eval('#bugHist .hist .note', n => /resize listener/.test(n.textContent)),
   '...and the search reads the notes, so a fix is findable by what fixed it');
await page.click('#bugLog');
await page.waitForFunction(() => !document.getElementById('bugList').hidden);

// One search across the whole notebook, for a session: roadmap, bugs and the
// memory log merged by time, tagged by source.
const merged = execFileSync(BB, ['history', '--find', 'compose files'],
  { env: { ...process.env, BB_TODO_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } }).toString();
ok(/bugs\s+claude\s+filed/.test(merged),
   'bb history finds a bug by its words, tagged with which log it came from');

// ---- what the server refuses ------------------------------------------------
const post = body => page.evaluate(async b => {
  const r = await fetch('/api/bugs', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json() };
}, body);
for (const [what, body] of [
  ['a project that does not exist', { action: 'add', project: 'nosuch', title: 'x' }],
  ['a project name that is really a path', { action: 'add', project: '../etc', title: 'x' }],
  ['a bug with no title', { action: 'add', project: 'alpha', title: '  ' }],
  ['a severity nobody defined', { action: 'add', project: 'alpha', title: 'x', severity: 'catastrophic' }],
  ['a status nobody defined', { action: 'status', project: 'alpha', id: 1, status: 'maybe' }],
  ['a bug nobody has', { action: 'status', project: 'alpha', id: 999, status: 'fixed' }],
  ['an action nobody offers', { action: 'purge', project: 'alpha' }],
]){
  const r = await post(body);
  ok(r.status === 400 && r.body.error, `refused: ${what}`);
}
page.errors = [];

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
await done(browser);
