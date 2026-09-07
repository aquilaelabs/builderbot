// The notebook's test registry: the hand-written half, the parsed half, and
// the thing that makes them worth keeping together — the drift between them.
//
// What is exercised for real here: the module through `bb tests` (the CLI a
// session drives), the endpoint through the page, and the tab against a run
// log this file writes itself. What is faked: the run log. Nothing here runs
// a suite — a test that ran the suite to test the thing that reads the suite
// would be the slowest test in the suite.
import { launch, newPage, ok, done, ready, nbShown, nbTab, URL, DIR } from './lib.mjs';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const BB = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'bb');
const FILE = `${DIR}/state/tests.json`;
const read = () => existsSync(FILE)
  ? JSON.parse(readFileSync(FILE, 'utf8')).projects.alpha || {} : {};
// The role is forced: this suite runs from a session on a node, where `bb`
// relays the notebook verbs to the real controller. The harness's bb is the
// controller's copy talking to the harness's own state.
const bb = (...a) => execFileSync(BB, ['tests', ...a], { env: { ...process.env,
  BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_STATE: `${DIR}/state`,
  WORKSPACE: `${DIR}/ws`, BB_TESTS_PROJECT: 'alpha' } }).toString();

// A run log in the runner's own shape. Durations are what BB_TEST_TIMING=1
// prints: the seconds since the previous result, which is that test's time.
const runlog = (rows) => {
  const out = [];
  let suite = null;
  for (const [s, name, secs] of rows){
    if (s !== suite){ out.push(`[dashboard-test] == ${s} ==`); suite = s; }
    out.push(`PASS  [+${secs.toFixed(1)}s] ${name}`);
  }
  out.push('12 passed, 0 failed in 40.0s');
  return out.join('\n') + '\n';
};
const LOG = `${DIR}/run-one.log`;

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);

// ---- ingesting ------------------------------------------------------------
writeFileSync(LOG, runlog([
  ['fast.mjs', 'the picker opens', 0.2],
  ['fast.mjs', '...and closes again', 0.1],
  ['slow.mjs', 'a token that is not one is refused', 30.0],
  ['slow.mjs', 'the daemon answers', 4.0],
  ['slow.mjs', '...and says which one', 10.0],
]));
const first = bb('ingest', LOG);
ok(/ingested 5 results from 2 suites/.test(first),
   'ingest reads the runner\'s own output and counts what it found');
ok(/new: 5/.test(first), '...and says every one of them is new, the first time');
const t = read().tests;
ok(t['slow.mjs#1'] && t['slow.mjs#1'].ms[0] === 30000,
   'a duration is stored in milliseconds, off the timing prefix the runner printed');
ok(t['fast.mjs#1'].suite === 'fast.mjs' && t['fast.mjs#1'].ord === 1,
   'a test is keyed on where the runner put it — file and ordinal, not its prose');

// ---- the numbers the header is for ---------------------------------------
const listed = bb('list');
ok(/5 tests · 44s measured/.test(listed),
   'the projection is the sum of what every test last cost');
ok(/2 flagged \(40s waiting\)/.test(listed),
   '...and the flagged ones are counted apart, with what they would give back');
ok(/slow\.mjs\s+3 tests\s+2 flagged/.test(listed),
   'the rollup is per suite: one file dominating is the more useful view');

// ---- the heuristic --------------------------------------------------------
// A fixed wait lands just above its boundary and never below, because the
// boundary IS the wait and everything after it is overhead.
const flagged = bb('flagged');
ok(/30\.0s\s+slow\.mjs#1/.test(flagged) && /10\.0s\s+slow\.mjs#3/.test(flagged),
   'a duration sitting on a round timeout is flagged as waiting, not working');
ok(!/4\.0s/.test(flagged),
   '...and 4.0s is not: it is under the floor, where a round number is a coincidence');

// ---- sequence context -----------------------------------------------------
const shown = bb('show', 'slow.mjs#3');
ok(/follows: the daemon answers/.test(shown),
   'a continuation keeps the test it follows — the names are prose and "..." '
   + 'read alone says nothing');

// ---- the hand-written half ------------------------------------------------
bb('note', 'slow.mjs#1', 'the token store refuses a value it cannot write',
   '--how', 'posts to /api/create; no GitHub, no clone');
const noted = bb('show', 'slow.mjs#1');
ok(/protects: the token store refuses/.test(noted)
   && /exercises: posts to \/api\/create/.test(noted),
   'a test carries what it protects and what it really exercises');

// ---- drift, which is the point --------------------------------------------
// A rename in place keeps the entry: same test, different words.
writeFileSync(LOG, runlog([
  ['fast.mjs', 'the picker opens', 0.2],
  ['fast.mjs', '...and closes again', 0.1],
  ['slow.mjs', 'a token with a space in it is refused', 30.0],
  ['slow.mjs', 'the daemon answers', 4.0],
  ['slow.mjs', '...and says which one', 10.0],
]));
const second = bb('ingest', LOG);
ok(/renamed: 1/.test(second) && /a token that is not one is refused -> a token with a space/.test(second),
   'a reworded test is reported as renamed rather than as one gone and one new');
ok(/protects: the token store refuses/.test(bb('show', 'slow.mjs#1')),
   '...and keeps what somebody wrote about it, which is why the key is not the name');
ok(read().tests['slow.mjs#1'].ms.length === 2,
   '...and its history, which is two runs now rather than one');

// A test inserted above it must not shift anybody's entry onto the wrong row.
writeFileSync(LOG, runlog([
  ['fast.mjs', 'the picker opens', 0.2],
  ['fast.mjs', '...and closes again', 0.1],
  ['slow.mjs', 'a brand new check', 0.3],
  ['slow.mjs', 'a token with a space in it is refused', 30.0],
  ['slow.mjs', 'the daemon answers', 4.0],
  ['slow.mjs', '...and says which one', 10.0],
]));
const third = bb('ingest', LOG);
ok(/new: 1/.test(third) && /a brand new check/.test(third) && !/renamed:/.test(third),
   'a test inserted in the middle is one addition, not a file of renames');
ok(/protects: the token store refuses/.test(bb('show', 'slow.mjs#2')),
   '...and the entries above it moved with their tests');

// ...and a deletion is a deletion.
writeFileSync(LOG, runlog([
  ['fast.mjs', 'the picker opens', 0.2],
  ['fast.mjs', '...and closes again', 0.1],
  ['slow.mjs', 'a brand new check', 0.3],
  ['slow.mjs', 'the daemon answers', 4.0],
  ['slow.mjs', '...and says which one', 10.0],
]));
ok(/gone: 1/.test(bb('ingest', LOG)),
   'a test that stopped being reported is drift, and says so');
ok(/gone\s+slow\.mjs#\d+\s+a token with a space/.test(bb('drift')),
   '...and stays on the drift report, which is where the two halves are compared');

// Ingesting one file's log must not report every other file as deleted.
writeFileSync(`${DIR}/run-part.log`, runlog([['fast.mjs', 'the picker opens', 0.2]]));
const part = bb('ingest', `${DIR}/run-part.log`);
ok(/gone: 1/.test(part) && !/slow\.mjs/.test(part),
   'a partial run reconciles only the suites that ran');
ok(read().tests['slow.mjs#3'] !== undefined,
   '...and leaves the suites it never mentioned alone');

// ---- the tab ---------------------------------------------------------------
await page.click(`#projects .row:has(.name:text-is("alpha")) [data-m]`);
await nbShown(page);
await nbTab(page, 'tests');
await page.waitForSelector('#tstList .tst', { timeout: 15000 });
const hint = await page.$eval('#tstHint', e => e.textContent.replace(/\s+/g, ' '));
ok(/projected/.test(hint) && /flagged/.test(hint),
   `the header carries the projected suite time and what is only waiting (${hint.trim()})`);
const rows = await page.$$eval('#tstList .tst', es => es.map(e => ({
  ms: e.querySelector('.tstms').textContent.trim(),
  name: e.querySelector('.tstname').textContent.trim(),
  flagged: e.classList.contains('flagged'),
  after: e.querySelector('.tstafter')?.textContent.trim() || '' })));
ok(rows.length > 1 && parseFloat(rows[0].ms) >= parseFloat(rows[1].ms),
   'the list is sorted by duration, longest first');
ok(rows.some(r => r.flagged),
   '...with the ones sitting on a timeout marked where the eye runs down');
ok(rows.some(r => r.name.startsWith('...') && /^follows: /.test(r.after)),
   '...and a continuation says what it follows on the row itself, not behind a fold');
ok(await page.$('#tstFolds details[data-sect="tests:suites"]') !== null
   && await page.$('#tstFolds details[data-sect="tests:drift"]') !== null,
   'the suite rollup and the drift report are sections, closed over the list');

// Describing one writes through, like a bug report: there is nothing to stage
// about a sentence describing a thing that already exists.
const box = '#tstList .tst[data-key="slow.mjs#2"]';
await page.click(`${box} > summary`);
await page.waitForFunction(s => document.querySelector(s)?.open, box, { timeout: 10000 });
await page.fill(`${box} .tstP`, 'the daemon address is parsed, not guessed');
await page.click(`${box} .tstSave`);
// The button wears its verb until the repaint replaces it, so waiting for it
// to be a Save again is waiting for the write to have landed and been drawn.
await page.waitForFunction(s => {
  const b = document.querySelector(s + ' .tstSave');
  return b && b.textContent.trim() === 'Save' && !b.disabled;
}, box, { timeout: 15000 });
ok(read().tests['slow.mjs#2'].protects === 'the daemon address is parsed, not guessed',
   'the tab writes a description through, with no Save for the panel to hold');
// The editor is built when a row opens rather than when the list draws —
// 1950 rows would otherwise be 3900 textareas and 28k nodes for a first
// screen of 25. Which means a redraw has to put back both the fold AND what
// was inside it, or saving a description folds away the row you were in.
ok(await page.$eval(box, e => e.open && !!e.querySelector('.tstP')),
   '...and the row it was written in stays open, with its editor still there');
ok(await page.evaluate(() => ({
     rows: document.querySelectorAll('#tstList .tst').length,
     areas: document.querySelectorAll('#tstList textarea').length })
   ).then(d => d.rows > 1 && d.areas <= 2),
   '...while the rows nobody opened carry no editor at all');

// Ingesting is the CLI's and deliberately not an endpoint. It WAS one, and
// it could never have worked: every body this server takes is capped at 64kB
// and a run log is a couple of hundred, so the action existed and answered
// "body too large" for the only input it was ever for.
ok((await page.evaluate(async () => {
     const r = await fetch('/api/tests', { method: 'POST',
       headers: { 'Content-Type': 'application/json' },
       body: JSON.stringify({ project: 'alpha', action: 'ingest', text: 'x' }) });
     return r.status;
   })) === 400,
   'ingesting is not an endpoint — a run log does not fit in a request');
// That refusal is a 400 by design, and the harness's console collector counts
// every one. Cleared here so the check below is about the page.
page.errors = [];

ok(page.errors.length === 0, `zero console errors${
  page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);
await done(browser);
