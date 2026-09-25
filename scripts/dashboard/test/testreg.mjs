// The notebook's test registry: the hand-written half, the parsed half, and
// the thing that makes them worth keeping together: the drift between them.
//
// What is exercised for real here: the module through `bb tests` (the CLI a
// session drives), the endpoint through the page, and the tab against a run
// log this file writes itself. What is faked: the run log. Nothing here runs
// a suite: a test that ran the suite to test the thing that reads the suite
// would be the slowest test in the suite.
import { launch, newPage, ok, done, ready, nbShown, nbTab, URL, DIR } from './lib.mjs';
import { readFileSync, writeFileSync, existsSync, mkdirSync, rmSync,
         cpSync } from 'node:fs';
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
   'a test is keyed on where the runner put it: file and ordinal, not its prose');

// ---- the numbers the header is for ---------------------------------------
const listed = bb('list');
ok(/5 tests · 44s measured/.test(listed),
   'the projection is the sum of what every test last cost');
ok(/2 flagged \(40s waiting\)/.test(listed),
   '...and the flagged ones are counted apart, with what they would give back');
ok(/slow\.mjs\s+3 tests\s+2 flagged/.test(listed),
   'the rollup is per suite: one file dominating is the more useful view');

// ---- narrowing ------------------------------------------------------------
// A change touches two files and the whole suite is minutes, so `bb tests
// run` takes the files to run and passes them to the project's test command.
// The projection has to follow it: asked about named suites it is those
// suites' own measured time, and asked about the whole thing it ignores the
// narrowed runs: projecting a full run from a two-file one would call it
// stuck while it was still getting started.
ok(/^projected 44s, what those 3 tests last measured, in 1 of 2 suites;/m
     .test(bb('projection', 'slow')),
   'a projection for named suites is those suites, by the stem a runner is asked for');
ok(/^projected 44s, what those 5 tests last measured, in 2 of 2 suites;/m
     .test(bb('projection', 'fast', 'slow.mjs')),
   '...several of them, named either way, add up');
ok(bb('projection', '--secs', 'slow').trim() === '44',
   '...and --secs is the number alone, which is what times the run');

// ---- the heuristic --------------------------------------------------------
// A fixed wait lands just above its boundary and never below, because the
// boundary IS the wait and everything after it is overhead.
const flagged = bb('flagged');
ok(/30\.0s\s+slow\.mjs#1/.test(flagged) && /10\.0s\s+slow\.mjs#3/.test(flagged),
   'a duration sitting on a round timeout is flagged as waiting, not working');
ok(!/4\.0s/.test(flagged),
   '...and 4.0s is not: it is under the floor, where a round number is a coincidence');

// ---- accepting a wait that is the work ------------------------------------
// A test that has to sit on a round number (a real boot, a timeout being
// proved) is marked so once, with why, and stops bothering anybody. The
// reason stays on the test, because "decided" and "tolerated" look the same
// from the number alone.
ok(/accepted; it will not be flagged/.test(bb('accept', 'slow.mjs#1', 'a real thirty-second boot')),
   'bb tests accept marks a flagged test as taking the time it takes');
const afterAccept = bb('flagged');
ok(!/slow\.mjs#1/.test(afterAccept) && /10\.0s\s+slow\.mjs#3/.test(afterAccept)
   && /1 accepted as the work/.test(afterAccept),
   '...and it leaves the flagged list, which says how many were accepted');
ok(/accepted: sits on 30s, and that is the work: a real thirty-second boot/.test(bb('show', 'slow.mjs#1')),
   '...with the reason kept on the test');
ok(/1 flagged \(10s waiting\)/.test(bb('list')),
   '...and the header counts only what is still flagged');
ok(/no longer accepted/.test(bb('accept', 'slow.mjs#1', '--no')) && /30\.0s\s+slow\.mjs#1/.test(bb('flagged')),
   'and --no takes the mark off, so it is flagged again');

// ---- sequence context -----------------------------------------------------
const shown = bb('show', 'slow.mjs#3');
ok(/follows: the daemon answers/.test(shown),
   'a continuation keeps the test it follows: the names are prose and "..." '
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

// A name that carries a uid or a port changes on every run, so every one of
// them is a rename, and an assertion inserted ABOVE such a name shifts it.
// Pairing the leftovers in list order got that wrong and lost the
// description; they are paired by how much of the wording survived.
{
  const was = [['drift.mjs', 'the picker opens', 0.2],
               ['drift.mjs', 'the owner has a minted id (u_616f379c)', 0.3],
               ['drift.mjs', 'and the last one', 0.4]];
  writeFileSync(`${DIR}/run-shift.log`, runlog(was));
  bb('ingest', `${DIR}/run-shift.log`);
  bb('note', 'drift.mjs#2', 'the owner is minted, not assumed');
  const now = [['drift.mjs', 'the picker opens', 0.2],
               ['drift.mjs', 'a brand new assertion', 0.1],
               ['drift.mjs', 'the owner has a minted id (u_920b520a)', 0.3],
               ['drift.mjs', 'and the last one', 0.4]];
  writeFileSync(`${DIR}/run-shift2.log`, runlog(now));
  const out = bb('ingest', `${DIR}/run-shift2.log`);
  ok(/new: 1/.test(out) && !/renamed:/.test(out) && !/gone:/.test(out),
     'an assertion inserted above a name that changes every run reads as one addition: the bracketed value moving is not a rename');
  const rows = read().tests;
  ok(Object.values(rows).some(t => /u_920b520a/.test(t.name || '')
       && t.protects === 'the owner is minted, not assumed'),
     '...and the description stays on the row whose words survived');
}

// Bug B121: THREE assertions inserted above a run of such names, with two
// neighbours of similar wording among them. Pairing by likeness within two
// ordinals could not reach a test moved by three, and gave the description
// to the neighbour whose words were closest instead.
{
  const was = [['b121.mjs', 'the picker opens', 0.2],
               ['b121.mjs', 'docker work is stamped with the node id (n_5659a7c)', 0.3],
               ['b121.mjs', 'hyperv renders its own kind (h_1a2b3c)', 0.1],
               ['b121.mjs', 'vmware renders its own kind (v_4d5e6f)', 0.1],
               ['b121.mjs', 'and the last one', 0.4]];
  writeFileSync(`${DIR}/run-b121.log`, runlog(was));
  bb('ingest', `${DIR}/run-b121.log`);
  bb('note', 'b121.mjs#2', 'the node id is the one on the record');
  bb('note', 'b121.mjs#3', 'hyperv, not vmware');
  const now = [['b121.mjs', 'the picker opens', 0.2],
               ['b121.mjs', 'one inserted', 0.1],
               ['b121.mjs', 'two inserted', 0.1],
               ['b121.mjs', 'three inserted', 0.1],
               ['b121.mjs', 'docker work is stamped with the node id (n_8f8f8f8)', 0.3],
               ['b121.mjs', 'hyperv renders its own kind (h_9a9a9a)', 0.1],
               ['b121.mjs', 'vmware renders its own kind (v_0b0b0b)', 0.1],
               ['b121.mjs', 'and the last one', 0.4]];
  writeFileSync(`${DIR}/run-b121b.log`, runlog(now));
  const out = bb('ingest', `${DIR}/run-b121b.log`);
  ok(/new: 3/.test(out) && !/renamed:/.test(out) && !/gone:/.test(out),
     'three assertions inserted above names carrying minted values read as three additions, nothing gone, nothing renamed');
  const rows = read().tests;
  ok(rows['b121.mjs#5']?.protects === 'the node id is the one on the record'
     && rows['b121.mjs#6']?.protects === 'hyperv, not vmware'
     && !rows['b121.mjs#7']?.protects,
     '...and each description followed its own test three ordinals down, not the neighbour with the closest words');
}

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
ok(/in tests/.test(hint) && /flagged/.test(hint),
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
// The drift fold counts what drifted, not how many rows it can show. The
// lists are capped at 200 and a first ingest is every test in the project,
// so a heading of "200" would be reporting where the list stops.
{
  const many = Array.from({ length: 260 }, (_, i) =>
    ['wide.mjs', `an assertion number ${i}`, 0.01]);
  writeFileSync(`${DIR}/run-wide.log`, runlog(many));
  const w = bb('ingest', `${DIR}/run-wide.log`);
  ok(/new: 260/.test(w), 'a run with more drift than the report holds counts all of it');
  await page.evaluate(() => notebooks.get('alpha').reloadTests());
  await page.waitForFunction(() => /260/.test(document.querySelector(
    '#tstFolds details[data-sect="tests:drift"] summary')?.textContent || ''),
    { timeout: 15000 });
  ok(true, '...and the fold is headed with that number, not with the 200 it lists');
  ok(/and 60 more/.test(await page.$eval(
       '#tstFolds details[data-sect="tests:drift"]', e => e.textContent)),
     '...saying how many it did not list');
  const rep = bb('drift');
  ok(/260 differences/.test(rep) && /and 60 more/.test(rep),
     '...and the report on the terminal counts the same way');
}

// Describing one writes through, like a bug report: there is nothing to stage
// about a sentence describing a thing that already exists.
const box = '#tstList .tst[data-key="slow.mjs#2"]';
await page.click(`${box} > summary`);
await page.waitForFunction(s => document.querySelector(s)?.open, box, { timeout: 10000 });
// Read first, like a bug report: an undescribed test says so, and Edit is
// what brings the two fields. Cancel puts them away and drops the typing.
await page.waitForSelector(`${box} .tstEdit`);
ok(!await page.$(`${box} textarea`) && /Not described yet/.test(await page.$eval(box, e => e.textContent)),
   'a row opens to read, saying it is not described yet, with no fields');
await page.click(`${box} .tstEdit`);
await page.waitForSelector(`${box} .tstP`);
await page.fill(`${box} .tstP`, 'a sentence that goes nowhere');
await page.click(`${box} .tstCancel`);
await page.waitForFunction(s => !document.querySelector(s + ' .tstP'), box, { timeout: 10000 });
ok(/Not described yet/.test(await page.$eval(box, e => e.textContent))
   && read().tests['slow.mjs#2'].protects === '',
   'Cancel puts the fields away with nothing written');
await page.click(`${box} .tstEdit`);
await page.waitForSelector(`${box} .tstP`);
await page.fill(`${box} .tstP`, 'the daemon address is parsed, not guessed');
await page.click(`${box} .tstSave`);
// Written, the row reads again: waiting for the fields to go is waiting for
// the write to have landed and been drawn.
await page.waitForFunction(s => !document.querySelector(s + ' .tstP'), box, { timeout: 15000 });
ok(read().tests['slow.mjs#2'].protects === 'the daemon address is parsed, not guessed',
   'the tab writes a description through, with no Save for the panel to hold');
// The editor is built when a row opens rather than when the list draws:
// 1950 rows would otherwise be 3900 textareas and 28k nodes for a first
// screen of 25. Which means a redraw has to put back the fold, or saving a
// description folds away the row you were in.
ok(await page.$eval(box, e => e.open && /parsed, not guessed/.test(e.querySelector('.bval')?.textContent || '')),
   '...and the row it was written in stays open, reading what was saved');
await page.click(`${box} .tstEdit`);
await page.waitForSelector(`${box} .tstN`);
ok(await page.evaluate(() => ({
     rows: document.querySelectorAll('#tstList .tst').length,
     areas: document.querySelectorAll('#tstList textarea').length })
   ).then(d => d.rows > 1 && d.areas <= 2),
   '...while the rows nobody opened carry no editor at all');
// A redraw is not always this panel's own: an ingest under an open tab draws
// one on the next poll, and it used to take unsaved typing with it.
await page.fill(`${box} .tstN`, 'half a sentence, not saved yet');
await page.evaluate(() => notebooks.get('alpha').reloadTests());
await page.waitForFunction(s => document.querySelector(s + ' .tstN'), box, { timeout: 10000 });
ok(await page.$eval(`${box} .tstN`, e => e.value) === 'half a sentence, not saved yet',
   'a redraw under an open editor gives back what was being typed into it');
ok(await page.$eval(`${box} .tstP`, e => e.value)
     === 'the daemon address is parsed, not guessed',
   '...and the field beside it, which was saved, still reads what was stored');

// The same mark from the row: the checkbox is offered only on a test that
// sits on a boundary, and saving with it ticked writes the reason and turns
// the warning pill into a quiet one.
{
  // A fresh flagged row, ingested now: the earlier rows have been through
  // renames and re-timings by this point, and this one sorts to the top.
  writeFileSync(LOG, runlog([['wait.mjs', 'a boot that really takes thirty seconds', 30.0]]));
  bb('ingest', LOG);
  const row = '#tstList .tst[data-key="wait.mjs#1"]';
  // Through the poll, which keeps testsRev in step: a direct reloadTests()
  // leaves the rev behind, and the next poll redraws the list a second
  // time, in the middle of the ticking below (B79).
  await page.evaluate(() => refresh());
  try { await page.waitForSelector(row, { timeout: 10000 }); }
  catch (e) {
    // B201: what the page held when the row did not show. Whether it is in
    // the DOM and not visible, or not there at all, is the one fact that
    // separates every theory tried so far, and nothing recorded it.
    console.log('B201 probe: ' + JSON.stringify(await page.evaluate(sel => ({
      hidden: document.hidden, inDom: !!document.querySelector(sel),
      token: revs['tests:alpha'], alphaKeys: Object.keys(revs).filter(k => /alpha/.test(k)),
      view: document.querySelector('.pane .nb .nbview:not([hidden])')?.dataset.view || null,
      nbInPane: !!document.querySelector('.pane .nb'), nbAnywhere: document.querySelectorAll('.nb').length,
      rows: document.querySelectorAll('#tstList .tst').length,
      keys: [...document.querySelectorAll('#tstList .tst')].slice(0, 4).map(x => x.dataset.key) }), row)));
    throw e;
  }
  ok(await page.$eval(row, e => /wait\?/.test(e.querySelector('.pill.warn')?.textContent || '')),
     'a flagged row wears the warning pill');
  await page.click(`${row} > summary`);
  await page.waitForSelector(`${row} .tstEdit`, { timeout: 10000 });
  await page.click(`${row} .tstEdit`);
  await page.waitForSelector(`${row} .tstAccept`, { timeout: 10000 });
  ok(await page.$eval(`${row} .tstWhy`, e => e.hidden), 'the reason field waits behind the checkbox');
  await page.click(`${row} .tstAccept`);
  await page.fill(`${row} .tstWhy`, 'the boot really takes this long');
  await page.click(`${row} .tstSave`);
  await page.waitForFunction(s => [...(document.querySelector(s)?.querySelectorAll('.pill') || [])]
                                    .some(p => /accepted/.test(p.textContent)),
                             row, { timeout: 15000 });
  ok(read().tests['wait.mjs#1'].accepted === 'the boot really takes this long',
     'ticking it on the row writes the reason to the registry');
  ok(await page.$eval(row, e => /The wait is the work/.test(e.textContent) && /the boot really takes this long/.test(e.textContent)),
     '...and the row reads it back under its own label');
  await page.click('#tstFlagged');
  await page.waitForFunction(s => !document.querySelector(s), row, { timeout: 10000 });
  ok(true, '...and "flagged only" no longer lists it');
  await page.click('#tstFlagged');
}

// ---- filling in a registry that already has a suite in it -----------------
// The per-test verb takes the file lock and rewrites the store on every call,
// which is right for a sentence somebody just typed and wrong for two
// thousand. The bulk form is one load and one save, and it refuses to invent
// a row for a key that names no test, because a descriptions file that has
// drifted from the roster is the same failure the drift report is for.
writeFileSync(`${DIR}/desc.json`, JSON.stringify({
  'slow.mjs#1': { protects: 'the token store refuses what it cannot write',
                  notes: 'posts to /api/create; no GitHub, no clone' },
  'slow.mjs#3': { protects: 'the daemon answers, and says which one' },
  'gone.mjs#9': { protects: 'a test that is not here any more' },
}));
const bulk = bb('describe', '--from', `${DIR}/desc.json`);
ok(/described 2 tests/.test(bulk),
   'a descriptions file fills many at once, in one write');
ok(/1 keys named no test here/.test(bulk) && /gone\.mjs#9/.test(bulk),
   '...and a key naming no test is reported rather than invented');
const after = read().tests;
ok(after['slow.mjs#1'].protects === 'the token store refuses what it cannot write'
   && after['slow.mjs#1'].notes === 'posts to /api/create; no GitHub, no clone',
   '...both fields land');
ok(after['slow.mjs#3'].protects === 'the daemon answers, and says which one'
   && after['slow.mjs#3'].notes === '',
   '...and a row that names only one field leaves the other alone');

// The tab re-reads when the poll says the registry moved, and what the poll
// compares is a count. Counting the run history was wrong: that list is capped
// at KEEP_RUNS, so from the twentieth ingest onward the number never changed
// again and an open tab stopped noticing runs entirely.
{
  const st = JSON.parse(readFileSync(FILE, 'utf8'));
  const p = st.projects.alpha;
  while (p.runs.length < 20) p.runs.push({ ...p.runs[0] });
  const revWas = p.rev;
  writeFileSync(FILE, JSON.stringify(st));
  writeFileSync(`${DIR}/run-again.log`, runlog([['fast.mjs', 'the picker opens', 9.9]]));
  bb('ingest', `${DIR}/run-again.log`);
  const now = read();
  ok(now.runs.length === 20 && now.rev === revWas + 1,
     'the tab\'s re-read token keeps counting past the run history that caps it');
  await page.evaluate(() => refresh());
  await page.waitForFunction(() => /9\.9/.test(document.querySelector(
    '#tstList .tst[data-key="fast.mjs#1"] .tstms')?.textContent || ''), { timeout: 15000 });
  ok(true, '...so a run ingested under an open tab is drawn on the next poll');
  // Same for a bulk fill from the CLI: hundreds of rows land in one write,
  // and a tab that is already open has nothing else to notice them by.
  const before = read().rev;
  writeFileSync(`${DIR}/desc2.json`, JSON.stringify({
    'fast.mjs#1': { protects: 'the picker opens on the first paint' } }));
  bb('describe', '--from', `${DIR}/desc2.json`);
  ok(read().rev > before, 'a bulk fill moves it too, having changed what the tab draws');
}

// The run's output is the shell's, not a box on a row. `bb tests log`
// prints what the last run wrote beside the project, and the Tests view's
// button sends `bb tests log -f` into the project's shell (the macro the
// server holds under that name).
{
  writeFileSync(`${DIR}/ws/alpha/.bb-test-run.log`, 'PASS  [+0.1s] a line the run wrote\n3 passed, 0 failed in 1.0s\n');
  const shown = bb('log');
  ok(/a line the run wrote/.test(shown) && /3 passed/.test(shown), 'bb tests log prints the last run\'s output whole');
  ok(await page.$eval('.pane .nb [data-view="tests"] #tstOut', b => !b.hidden && /run's output/.test(b.textContent)),
     'the Tests view carries Open the run\'s output beside its summary');
}

// B201: a write that lands WHILE the panel's read is out is not marked as
// seen. The panel used to record the page's token as of when its answer
// arrived; a poll in between had already moved that token for the write, so
// the panel recorded "seen" against an answer from before it, and the row
// the write made never showed until something else moved the token. Forced
// here: the answer is fetched BEFORE the ingest and handed to the panel after
// the token has moved, which is what a slow answer under a fast poll is.
{
  const staged = await page.evaluate(async () => {
    const f = window.fetch;
    const early = await f('/api/tests?project=alpha');
    const body = await early.text();
    window.__restore = () => { window.fetch = f; };
    // Served ONCE: the read after it is the panel noticing it was behind,
    // and that one has to reach the real server.
    let served = false;
    window.fetch = (...a) => String(a[0]).startsWith('/api/tests?') && !served
      ? (served = true, Promise.resolve(new Response(body, { status: 200, headers: { 'Content-Type': 'application/json' } })))
      : f(...a);
    return body.length > 0;
  });
  ok(staged, 'an answer of the Tests view is read before a write');
  writeFileSync(LOG, runlog([['race.mjs', 'a row written under an open read', 1.0]]));
  bb('ingest', LOG);
  await page.evaluate(() => pollRevs());              // the token moves
  await page.evaluate(() => notebooks.get('alpha').reloadTests());   // ...and the old answer lands
  await page.evaluate(() => window.__restore());
  // The page's ordinary poll: the panel must notice its answer predates
  // the write and read again, from the real server now.
  await page.evaluate(() => pollRevs());
  let shown = false;
  try { await page.waitForSelector('#tstList .tst[data-key="race.mjs#1"]', { timeout: 10000 }); shown = true; }
  catch (e) {}
  ok(shown, 'a run ingested while the panel was reading shows on the next poll, not never');
}

// `bb tests run` is the loop this file's subject was missing: run the
// project's own test command, time it, record it, so the registry stops
// going stale because somebody forgot the second step.
//
// What is asserted here is the part that is this file's: a run that never
// happened is not recorded, and says so once rather than twice. The run
// itself is `bb test`, which the job suites already drive, and pointing this
// one at a real suite would be a suite inside a suite.
{
  let out = '';
  try {
    out = execFileSync(BB, ['tests', 'run'], { env: { ...process.env,
    BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_STATE: `${DIR}/state`,
    WORKSPACE: `${DIR}/ws`, BB_TESTS_PROJECT: 'alpha',
      DASHBOARD_PORT: new globalThis.URL(URL).port, DASHBOARD_AUTH: 'test:test' },
      stdio: ['ignore', 'pipe', 'pipe'] }).toString();
  } catch (e) { out = String(e.stdout || '') + String(e.stderr || ''); }
  // Before anything runs it says when the run should finish, from the wall
  // time the last WHOLE run reported, so a run is waited for rather than
  // guessed at, and one well past it is read as stuck. The last whole one,
  // because a run narrowed to two files takes a fraction of the time and
  // projecting the next full one from it would call it stuck while it was
  // still getting started.
  ok(/^projected 40s, what the last whole run took over \d+ tests in \d+ suites; one past 80s is stuck, not slow$/m.test(out),
     `bb tests run says first when it should finish, from the last whole run's wall time (${out.split('\n')[0]})`);
  ok(/nothing timed, so nothing recorded/.test(out),
     'a run that could not start records nothing, and says so');
  ok(!/looks like a test run/.test(out),
     '...once: the ingest is not asked to explain a log that was never written');
}

// The bundle a node gets carries bb and its library and none of the
// dashboard's python, because every tests verb but one is relayed to the
// controller. The exception is `run`: it RUNS the suite, which belongs where
// the toolchain and the tree are, and relays only the ingest afterwards. The
// module check sat above that branch, so the one verb that has to work on a
// node was the one verb that could not.
{
  const B = `${DIR}/bundleish`;
  rmSync(B, { recursive: true, force: true });
  mkdirSync(`${B}/scripts`, { recursive: true });
  cpSync(BB, `${B}/scripts/bb`);
  cpSync(join(dirname(BB), 'lib'), `${B}/scripts/lib`, { recursive: true });
  ok(!existsSync(`${B}/scripts/dashboard/testreg.py`),
     'the bundle shape: bb and its library, no dashboard python beside it');
  let out = '';
  try {
    out = execFileSync(`${B}/scripts/bb`, ['tests', 'run'], { env: { ...process.env,
      BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', DASHBOARD_STATE: `${DIR}/state`,
      WORKSPACE: `${DIR}/ws`, BB_TESTS_PROJECT: 'alpha',
      DASHBOARD_PORT: new globalThis.URL(URL).port, DASHBOARD_AUTH: 'test:test' },
      stdio: ['ignore', 'pipe', 'pipe'] }).toString();
  } catch (e) { out = String(e.stdout || '') + String(e.stderr || ''); }
  ok(!/testreg\.py is missing/.test(out),
     `bb tests run works with no testreg.py beside it, which is every node (${
       out.trim().split('\n')[0] || 'no output'})`);
  ok(/nothing timed, so nothing recorded/.test(out),
     '...reaching the same place a controller run reaches');
}

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
   'ingesting is not an endpoint: a run log does not fit in a request');
// That refusal is a 400 by design, and the harness's console collector counts
// every one. Cleared here so the check below is about the page.
page.errors = [];

ok(page.errors.length === 0, `zero console errors${
  page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);
await done(browser);
