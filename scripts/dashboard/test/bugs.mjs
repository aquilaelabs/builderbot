// The bug tracker: the notebook's third view, /api/bugs behind it, and the
// `bb bug` CLI a session drives. Write-through, unlike the roadmap (a bug
// report is a form submitted once, not a list curated in place), and nothing
// is ever deleted: a bug closes as fixed or wontfix, each with a note, because
// a closed bug is the record that stops the same report being chased twice.
import { launch, newPage, ok, done, ready, nbShown, tmuxCapture, URL, DIR, openFold, closeFold } from './lib.mjs';
import { readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const BB = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'bb');
const bbBug = (...a) => execFileSync(BB, ['bug', ...a],
  { env: { ...process.env, BB_BUG_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } }).toString();
const bbRoadmapBatch = (...a) => execFileSync(BB, ['roadmap', ...a],
  { env: { ...process.env, BB_ROADMAP_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
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
await page.click('#bugAdd button');
await page.waitForSelector('.bugform', { timeout: 10000 });
ok(await page.evaluate(() => document.activeElement?.tagName !== 'INPUT'),
   'the form opens without a cursor in it, like everything else here');
await page.fill('.bugform .bfTitle', 'the picker loses its selection on rotate');
await page.selectOption('.bugform .bfSev', 'high');
await page.fill('.bugform .bfArea', 'scripts/dashboard/index.html (the picker)');
await page.fill('.bugform .bfRepro', '1. open the picker on a phone\n2. rotate');
await page.fill('.bugform .bfExpected', 'the selection survives');
await page.fill('.bugform .bfActual', 'it resets to the first entry');
await page.click('.bugform .bfGo');
await page.waitForSelector('#bugList .bug', { timeout: 10000 });
const b1 = read()[0];
ok(b1 && b1.title === 'the picker loses its selection on rotate'
   && b1.severity === 'high' && b1.status === 'open' && b1.by === 'you'
   && b1.repro === '1. open the picker on a phone\n2. rotate',
   'the report lands on disk with its fields, written through, with no Save involved');
ok(await page.$eval('#bugList .bug .sev', el => el.textContent) === 'high',
   '...and the row leads with its severity, the way a memory leads with its type');

// ---- the session's half ----------------------------------------------------
// --here: the title names a bb verb, which bb bug add now asks about on a
// project other than BuilderBot (reports.mjs holds that); this one is alpha's own.
bbBug('add', 'bb lint misses compose files in subdirectories', '--here', '--sev', 'low',
      '--area', 'scripts/bb', '--repro', 'put a compose file under tools/ and run bb lint');
ok(read().length === 2 && read()[1].by === 'claude',
   'a session files one through bb bug, marked as its own');
const listed = bbBug();
ok(/\bB2\b.*compose files/.test(listed) && /\bB1\b.*picker loses/.test(listed),
   'bb bug lists the open ones');
ok(/repro: put a compose file/.test(bbBug('show', '2')),
   'bb bug show gives one in full, fields and all');
// ---- the letter (roadmap #28) ------------------------------------------------
// A bug is B2, everywhere it is printed; the bare number and the lower-case
// letter are accepted on the way in; the ROADMAP's letter is refused with a
// sentence naming both: the letter is a check, not decoration.
ok(/\bB2\b.*compose files/.test(listed) && /filed\s+B2\s/.test(bbBug('history', '--find', 'compose files')),
   'a bug is printed as B2 in the listing and the log');
ok(/repro: put a compose file/.test(bbBug('show', 'b2'))
   && /repro: put a compose file/.test(bbBug('show', '#2')),
   '...and b2 or #2 name the same bug on the way in');
ok(/R2 is a roadmap item; a bug is B2/.test((() => {
     try { return bbBug('show', 'R2'); } catch (e) { return e.stderr.toString(); } })()),
   '...while the roadmap\'s letter is refused, naming both tabs');
bbBug('note', '2', 'the file list is built from names, not from content');
ok(/file list is built from names/.test(read()[1].notes || ''),
   'bb bug note appends what a session learned, dated, without replacing what was there');

const prompt = bbBug('--prompt');
ok(/B1 \[high\] the picker loses/.test(prompt) && /B2 \[low\]/.test(prompt),
   'the prompt block carries the open bugs, severity first');
ok(/bb bug show B7/.test(prompt) && /bb bug add/.test(prompt),
   '...and tells a session how to read one and how to file one');

// ---- the GUI sees what the CLI wrote ---------------------------------------
await page.evaluate(() => notebooks.get('alpha').reloadBugs());
await page.waitForFunction(() => document.querySelectorAll('#bugList .bug').length === 2,
                           { timeout: 10000 });
ok(true, 'the tab picks up what a session filed');

// ---- closing one, with the note that is the point --------------------------
page.dialogs = [];
await page.evaluate(() => { window.prompt = () => 'the select re-measures on rotate now'; });
await openFold(page, '#bugList .bug[data-id="1"]');
await page.click('#bugList .bug[data-id="1"] .bFix');
await page.waitForFunction(() => document.querySelector('#bugList .bug[data-id="1"] .bstat')?.textContent === 'fixed', { timeout: 10000 });
ok(read().find(b => b.id === 1).status === 'fixed'
   && read().find(b => b.id === 1).status_note === 'the select re-measures on rotate now',
   'marking one fixed asks what fixed it, and keeps the answer on the bug');
ok(!/picker loses/.test(bbBug()), '...and it leaves the open list');
// The row's verbs are an action bar: who reported it on a line of its own,
// the buttons under it, and the one that cannot be undone last. It was six
// buttons in a plain div with Delete third, where the thumb goes.
{
  const bar = await page.$eval('#bugList .bug[data-id="1"] .macts', el => ({
    bar: el.classList.contains('actbar'),
    state: el.querySelector('.state')?.textContent || '',
    last: el.querySelector('button:last-of-type')?.className || '' }));
  ok(bar.bar && /reported by/.test(bar.state),
     'a report\'s verbs are an action bar, with who filed it as its status line');
  ok(/bRm/.test(bar.last),
     '...and Delete is last, being the one that cannot be undone');
}
ok(/\[fixed\]/.test(bbBug('all')), '...but never the tracker: bb bug all still has it');
ok(!/B1 /.test(bbBug('--prompt')),
   '...and the next session is not handed a bug that is already fixed');

// Closed sinks below open, however new it is.
ok(await page.$$eval('#bugList .bug', ds => ds.map(d => d.dataset.id)).then(
     ids => ids[ids.length - 1] === '1'),
   'a closed bug sinks below the open ones');

// Reopen from the CLI: "the fix did not take" is a real answer.
bbBug('reopen', '1');
ok(read().find(b => b.id === 1).status === 'open'
   && !read().find(b => b.id === 1).status_note,
   'reopening clears the fixed note, since it turned out not to be true');
bbBug('fix', '1', 'this time with the resize listener');
ok(read().find(b => b.id === 1).status_note === 'this time with the resize listener',
   '...and closing again writes the new answer');
// ...but not closing a closed one (bug #70): that overwrote the note that is
// the whole point of closing, and left no line in the log saying so.
{
  let said = '';
  try { bbBug('wontfix', '1', 'never mind'); } catch (e) { said = String(e.stderr || ''); }
  ok(/already fixed/.test(said) && /reopen it first/.test(said)
     && read().find(b => b.id === 1).status_note === 'this time with the resize listener',
     'closing a bug that is already closed is refused, and its note survives');
}

// ---- the version it was seen in, and closed in (roadmap #6) ---------------
// A tree with no commits has nothing honest to say about its version, and
// nothing is said: a blank, never a made-up number. Its own project rather
// than alpha, which another file commits in (B144). A project with a commit
// gets the same identity `bb version` prints, on filing and again on closing.
{
  const N = `${DIR}/ws/eta`;
  execFileSync('git', ['init', '-q', N]);
  execFileSync(BB, ['bug', 'add', 'filed before any commit', '--sev', 'low'],
    { env: { ...process.env, BB_BUG_PROJECT: 'eta', DASHBOARD_STATE: `${DIR}/state`,
             WORKSPACE: `${DIR}/ws` } });
  const e = (JSON.parse(readFileSync(FILE, 'utf8')).projects.eta || [])[0];
  ok(e && !('seen_in' in e),
     'a report on a tree with no commits carries no version: a blank rather than a guess');
  execFileSync('rm', ['-rf', N]);
}
{
  const Z = `${DIR}/ws/zeta`;
  const genv = { ...process.env, GIT_AUTHOR_NAME: 't', GIT_AUTHOR_EMAIL: 't@x',
                 GIT_COMMITTER_NAME: 't', GIT_COMMITTER_EMAIL: 't@x' };
  execFileSync('git', ['init', '-q', Z], { env: genv });
  execFileSync('git', ['-C', Z, 'commit', '-q', '--allow-empty', '-m', 'one'], { env: genv });
  const bbZ = (...a) => execFileSync(BB, ['bug', ...a],
    { env: { ...process.env, BB_BUG_PROJECT: 'zeta', DASHBOARD_STATE: `${DIR}/state`,
             WORKSPACE: `${DIR}/ws` } }).toString();
  const zread = () => JSON.parse(readFileSync(FILE, 'utf8')).projects.zeta || [];
  bbZ('add', 'stamped on arrival', '--sev', 'low');
  const z = zread()[0];
  ok(typeof z.seen_in === 'string' && z.seen_in.length > 0,
     `a report is stamped with the project's version when it is filed (${z.seen_in})`);
  ok(new RegExp(`seen in: ${z.seen_in.replace(/[.+]/g, '\\$&')}`).test(bbZ('show', '1')),
     '...and bb bug show prints it');
  execFileSync('git', ['-C', Z, 'commit', '-q', '--allow-empty', '-m', 'two'], { env: genv });
  bbZ('fix', '1', 'done');
  const zc = zread()[0];
  ok(typeof zc.fixed_in === 'string' && zc.fixed_in !== z.seen_in,
     `...and with the version it was closed in, which is a later one (${zc.fixed_in})`);
  bbZ('reopen', '1');
  ok(!('fixed_in' in zread()[0]),
     'reopening takes the closed-in stamp with the note, since it turned out not to be true');
  execFileSync('rm', ['-rf', Z]);
}

// ---- editing ---------------------------------------------------------------
bbBug('edit', '2', 'sev', 'medium');
ok(read().find(b => b.id === 2).severity === 'medium',
   'a session can re-grade a bug once it knows more');

// ---- sorting ---------------------------------------------------------------
// Open before closed is not one of the choices (a tracker is read to find
// what is left), so every order below is an order within that.
bbBug('add', 'a third, filed last and graded critical', '--sev', 'critical');
await page.evaluate(() => notebooks.get('alpha').reloadBugs());
await page.waitForFunction(() => document.querySelectorAll('#bugList .bug').length === 3,
                           { timeout: 10000 });
const ids = () => page.$$eval('#bugList .bug', ds => ds.map(d => d.dataset.id));
ok((await ids())[0] === '3',
   'severity is the default, so the critical leads');
await page.selectOption('#bugSort', 'oldest');
await page.waitForFunction(() => document.querySelector('#bugList .bug').dataset.id === '2',
                           { timeout: 10000 });
ok(true, 'oldest first puts the earliest open report at the top');
await page.selectOption('#bugSort', 'newest');
await page.waitForFunction(() => document.querySelector('#bugList .bug').dataset.id === '3',
                           { timeout: 10000 });
ok((await ids()).at(-1) === '1',
   'newest first reverses it, and the closed one stays at the bottom either way');
await page.selectOption('#bugSort', 'title');
ok((await ids()).slice(0, 2).join() === '3,2',
   'title A–Z orders by the words, open ones still first');
await page.selectOption('#bugSort', 'severity');

// Severity is the one sort that means nothing once a bug is closed: "how bad
// is it" is a question about work outstanding, and a critical fixed months ago
// above a medium fixed yesterday answers nothing anybody asked. So the closed
// half falls back to most recently closed, the only thing that half is read
// for, while the open half is still worst-first.
bbBug('add', 'an old low one, closed first', '--sev', 'low');
bbBug('add', 'a newer critical, closed after it', '--sev', 'critical');
bbBug('fix', '4', 'closed this one first');
// updated has one-second resolution, and the point of the assertion below is
// that the LATER close leads, so the two have to land in different seconds.
await new Promise(r => setTimeout(r, 1100));
bbBug('fix', '5', 'and this one second');
await page.evaluate(() => notebooks.get('alpha').reloadBugs());
await page.waitForFunction(() => document.querySelectorAll('#bugList .bug').length === 5,
                           { timeout: 10000 });
const order = await ids();
const shut = order.slice(order.indexOf('5'));
ok(shut[0] === '5' && shut.includes('4'),
   'sorted by severity, the closed ones run most-recently-closed first: a low '
   + 'closed after a critical is above it');
ok(order.indexOf('5') > order.indexOf('2'),
   '...and every closed one is still below every open one, whatever its severity');
// The pills carry the same three colours the bell uses for the same three
// meanings, so a severity and a notification are not two things to learn.
const pill = sev => page.$eval(`#bugList .bug .sev.${sev}`,
                               e => getComputedStyle(e).color);
ok(await pill('low') !== await pill('medium')
   && await pill('medium') !== await pill('high'),
   'low, medium and high are three different colours rather than three words');
// Put the fixture back to three: the tests below count rows.
bbBug('rm', '4', 'a fixture for the sort above');
bbBug('rm', '5', 'a fixture for the sort above');
await page.evaluate(() => notebooks.get('alpha').reloadBugs());
await page.waitForFunction(() => document.querySelectorAll('#bugList .bug').length === 3,
                           { timeout: 10000 });

// ---- deleting a report that should not exist -------------------------------
// Not the same act as closing one: fixed and wontfix keep the bug, because a
// closed bug stops the same report being chased twice. This is for the report
// that should never have been filed, and it says so in the log.
await openFold(page, '#bugList .bug[data-id="3"]');
await page.click('#bugList .bug[data-id="3"] .bRm');
await page.waitForSelector('.bug .dropbox textarea', { timeout: 10000 });
ok(read().some(b => b.id === 3),
   'the bin asks in place, and nothing has gone while it is asking');
// Bug #42: the box is imperative DOM appended after the render, so a repaint
// used to take it and whatever was typed into it. Type something, force the
// redraw the poll would have done, and both must survive.
await page.fill('.bug .dropbox textarea', 'half a reason, still being written');
await page.evaluate(p => notebooks.get(p).reloadBugs(), 'alpha');
const kept = await page.$eval('.bug .dropbox textarea', e => e.value).catch(() => null);
ok(kept === 'half a reason, still being written',
   `a repaint under an open delete box leaves it, and what was typed (${JSON.stringify(kept)})`);
await page.click('.bug .dropbox .stop');
// Waited for, not asserted on the next line: the row repaints whenever the
// tracker's revision moves, and a click that lands as the row is replaced
// leaves the box on screen for another frame. Nothing is wrong with the page
// when that happens; what must be true is that it closes and that nothing
// was deleted, and both survive a repaint (bug #13).
await page.waitForFunction(() => !document.querySelector('.bug .dropbox'),
                           null, { timeout: 10000 });
ok(read().some(b => b.id === 3), 'Cancel closes it and deletes nothing');
await page.click('#bugList .bug[data-id="3"] .bRm');
await page.waitForSelector('.bug .dropbox textarea', { timeout: 10000 });
await page.fill('.bug .dropbox textarea', 'filed against the wrong project');
await page.click('.bug .dropbox .danger');
await page.waitForFunction(() => document.querySelectorAll('#bugList .bug').length === 2,
                           { timeout: 10000 });
ok(!read().some(b => b.id === 3), 'Delete it takes the row for good');
ok(/wrong project/.test(bbBug('history', '--find', 'wrong project')),
   '...leaving the reason in the log, which is all that is left of it');

// A session can do the same, for the case that prompted it: a mis-filed report.
bbBug('add', 'filed by a session in error');
const oops = String(read().at(-1).id);
bbBug('rm', oops, 'a mis-file: the session meant the other project');
ok(!read().some(b => String(b.id) === oops),
   'bb bug rm deletes one, for the mis-file that closing would lie about');

// ---- not applicable --------------------------------------------------------
// The third way a bug leaves the open list: it was real, and it stopped
// applying: the feature it was about went away. Calling that fixed credits
// a fix nobody made; calling it wontfix claims a decision nobody took.
bbBug('add', 'the picker drops focus on rotate', '--sev', 'medium');
const naId = String(read().at(-1).id);
await page.evaluate(() => notebooks.get('alpha').reloadBugs());
await page.waitForFunction(n => !!document.querySelector(`#bugList .bug[data-id="${n}"]`),
                           naId, { timeout: 10000 });
await page.evaluate(() => { window.prompt = () => 'the picker was removed entirely'; });
await openFold(page, `#bugList .bug[data-id="${naId}"]`);
await page.click(`#bugList .bug[data-id="${naId}"] .bNa`);
await page.waitForFunction(n => document.querySelector(
  `#bugList .bug[data-id="${n}"] .bstat`)?.textContent === 'n/a', naId,
  { timeout: 10000 });
const naBug = read().find(b => String(b.id) === naId);
ok(naBug.status === 'na' && naBug.status_note === 'the picker was removed entirely',
   'Not applicable closes it with what stopped it applying');
ok(!/picker drops focus/.test(bbBug('--prompt')),
   '...and it leaves the block a session starts with, like any other closure');
ok(/\[na\]/.test(bbBug('all')), '...but stays in the tracker, as its own kind of closed');
bbBug('reopen', naId);
bbBug('na', naId, 'removed again in the CLI');
ok(read().find(b => String(b.id) === naId).status === 'na',
   'bb bug na does the same from a session');

// ---- a session writing while the tab is open ------------------------------
// The tracker is write-through on both sides, so there is nothing local to
// lose and nothing to ask about: the view catches up on the poll. It used to
// sit there showing what a session had already changed until the tab was
// reopened.
const seen = () => page.$$eval('#bugList .bug', ds => ds.map(d => d.dataset.id));
const beforeLive = (await seen()).length;
bbBug('add', 'filed by a session while the tab was open', '--sev', 'low');
await page.evaluate(() => refresh());
await page.waitForFunction(n => document.querySelectorAll('#bugList .bug').length > n,
                           beforeLive, { timeout: 20000 });
ok(true, 'a bug a session files appears without the tab being reopened');
const liveId = String(read().at(-1).id);
bbBug('fix', liveId, 'closed by the session too');
await page.evaluate(() => refresh());
await page.waitForFunction(n => document.querySelector(
  `#bugList .bug[data-id="${n}"] .bstat`)?.textContent === 'fixed', liveId,
  { timeout: 20000 });
ok(true, '...and so does a closure, which no count of open bugs would catch');
bbBug('rm', liveId, 'test scaffolding');
await page.evaluate(() => refresh());
await page.waitForFunction(n => !document.querySelector(`#bugList .bug[data-id="${n}"]`),
                           liveId, { timeout: 20000 });
ok(true, '...and a delete, which is the case a revision catches and a count does not');

// ---- Check now answers about the batch, not about one view -----------------
// It used to reload the roadmap, which refreshed one tab of four and left the
// other three showing what the session had already changed.
bbRoadmapBatch('begin');
bbBug('add', 'filed mid-batch, from a session', '--sev', 'high');
await page.evaluate(() => refresh());
await page.waitForFunction(() => !document.getElementById('roadmapBatch').hidden,
                           { timeout: 20000 });
ok(await page.evaluate(() => nbHeldFor('alpha')), 'the notebook is held');
bbRoadmapBatch('commit');
await page.click('#roadmapRecheck');
await page.waitForFunction(() => document.getElementById('roadmapBatch').hidden,
                           { timeout: 20000 });
// Waited for rather than read straight off. A batch now covers the tracker
// too, so a bug filed inside one does not move the tracker's revision until
// the commit. The tab has no reason to reload while the notebook is held,
// and learns about the report from this re-read rather than from a poll that
// happened to fire earlier.
await page.waitForFunction(() => [...document.querySelectorAll('#bugList .bug .btitle')]
  .some(t => /filed mid-batch/.test(t.textContent)), { timeout: 20000 });
ok(true, 'Check now lifts the hold and the Bugs tab has the session\'s report on it');

// ---- the tracker's log -----------------------------------------------------
// Same bar, same rows as the roadmap's: search, a window, a cap. Filed,
// noted, fixed, reopened, with who and when, which the tracker's present
// tense cannot answer.
await page.click('#bugLog');
await page.waitForFunction(() => document.querySelectorAll('#bugHist .hist').length > 0,
                           { timeout: 10000 });
// It opens OVER the tracker rather than in place of it: the report you wanted
// to read the log against is still there behind it.
ok(!await page.$eval('#bugList', el => el.hidden)
   && await page.$eval('.nbsheet', el => !el.hidden)
   && await page.$eval('#bugHist', el => el.closest('.sheetslot') !== null),
   'History opens over the tracker, which is still there behind it');
const acts = await page.$$eval('#bugHist .hist .act', as => as.map(a => a.textContent));
ok(acts.includes('filed') && acts.includes('fixed') && acts.includes('noted')
   && acts.includes('reopened') && acts.includes('deleted'),
   'the log carries the tracker\'s verbs: filed, noted, fixed, reopened, deleted');
await page.fill('#bugHistBar input', 'resize listener');
await page.waitForFunction(() => document.querySelectorAll('#bugHist .hist').length === 1,
                           { timeout: 10000 });
ok(await page.$eval('#bugHist .hist .note', n => /resize listener/.test(n.textContent)),
   '...and the search reads the notes, so a fix is findable by what fixed it');
// Escape, not the History button again: the sheet covers the whole page now,
// so the button that opened it is behind the overlay, which is the point of
// an overlay, and was the bug. It used to stop at the notebook's text column
// and leave the header reachable through the gap.
await page.evaluate(() => document.querySelector('.nbsheet:not([hidden]) .foot button')
                            ?.click());
await page.waitForFunction(() => !document.querySelector('.nbsheet:not([hidden])'),
                           { timeout: 8000 });
await page.waitForFunction(() => !document.getElementById('bugList').hidden);

// One search across the whole notebook, for a session: roadmap, bugs and the
// memory log merged by time, tagged by source.
const merged = execFileSync(BB, ['history', '--find', 'compose files'],
  { env: { ...process.env, BB_ROADMAP_PROJECT: 'alpha', DASHBOARD_STATE: `${DIR}/state`,
           WORKSPACE: `${DIR}/ws` } }).toString();
ok(/bugs\s+claude\s+filed/.test(merged),
   'bb history finds a bug by its words, tagged with which log it came from');

const post = body => page.evaluate(async b => {
  const r = await fetch('/api/bugs', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json() };
}, body);

// ---- opening one is a slide, not a snap -------------------------------------
// The same height tween the sidebar cards fold with. A <details> opens
// instantly by construction, so the summary's click is taken over; what
// proves it is an animation running on the element and a height between the
// two resting sizes rather than at one of them.
{
  // Back on the list: the History above swapped it out, and a fold cannot be
  // measured through a view that is not on screen.
  await page.click(`${row('alpha')} [data-m]`);
  await page.click('.pane .nb .nbtabs [data-v="bugs"]');
  // Waited on the LOAD, not on a row appearing. The view is drawn before its
  // fetch lands, so a wait on `.bug` was a wait on a round trip it could not
  // see, and about one run in three it lost (B99). reloadBugs returns the
  // fetch, so awaiting it is awaiting the data the rows are made of.
  await page.evaluate(() => notebooks.get('alpha').reloadBugs());
  await page.waitForSelector('#bugList .bug', { timeout: 15000 });
  const one = await page.$eval('#bugList .bug', d => d.dataset.id);
  const sel = `#bugList .bug[data-id="${one}"]`;
  // The shut height, the click and the keyframes, all in ONE task.
  // slideDetails animates synchronously inside the handler, so this cannot
  // miss the tween the way asking "is it animating?" in a later round trip
  // can. The shut height is read here too: measured a round trip earlier it
  // was sometimes an OPEN row's, because a revision poll landing between the
  // two calls redrew the list with the row a prior check had left open
  // (B204), which read as the slide starting from the wrong height.
  const kf = await page.evaluate(s => {
    const el = document.querySelector(s);
    if (el.open) el.open = false;             // a shut row is what is measured
    const shut = el.offsetHeight;
    el.querySelector("summary").click();
    const a = el.getAnimations()[0];
    return { shut, kf: a ? a.effect.getKeyframes().map(k => parseFloat(k.height)) : null };
  }, sel);
  const shut = kf.shut;
  ok(kf.kf && kf.kf[0] === shut && kf.kf[1] > shut,
     `a bug report opens with a slide, from its shut height (${kf.kf?.join(' → ')}px)`);
  await page.waitForFunction(s => !document.querySelector(s).getAnimations().length,
                             sel, { timeout: 5000 });
  const full = await page.$eval(sel, d => d.offsetHeight);
  ok(full > shut && kf.kf[1] === full,
     `...landing at the height it aimed for (${shut} → ${full}px)`);
  await closeFold(page, sel);
  // Against the row as it is NOW, not against `shut`. The click on the project
  // row above reopened the notebook, and its re-read repaints this list when it
  // lands, on a loaded box that is under the fold rather than before it. The
  // repaint swaps the row for an equal one (closeFold copes), but a height
  // sampled on the old row and one on its replacement agree only while nothing
  // around it moved (the first-child border, the doc's scrollbar), which is not
  // what this is about (B71). Shut means the box is its summary plus its own
  // padding and border, with no inline height left by the tween.
  const back = await page.$eval(sel, d => {
    const cs = getComputedStyle(d), sum = d.querySelector("summary");
    const chrome = ["paddingTop", "paddingBottom", "borderTopWidth", "borderBottomWidth"]
      .reduce((n, k) => n + parseFloat(cs[k]), 0);
    return { open: d.open, inline: d.style.height + d.style.overflow,
             box: d.getBoundingClientRect().height,
             want: sum.getBoundingClientRect().height + chrome };
  });
  ok(!back.open && back.inline === "" && Math.abs(back.box - back.want) < 0.05,
     `...and closes back to exactly its shut height, nothing of the tween left (${back.box} vs ${back.want}px)`);
}

// ---- handing one to a session ----------------------------------------------
// A bug goes over as a NUMBER and an instruction to look it up, never as a
// copy of the report. The tracker is the copy that stays current: paste the
// fields into a conversation and they start going stale the moment anybody
// adds a note, and the session is then working from the paste.
await page.waitForSelector('#bugList .bug', { timeout: 15000 });
const first = await page.$eval('#bugList .bug', d => d.dataset.id);
await openFold(page, `#bugList .bug[data-id="${first}"]`);
await page.click(`#bugList .bug[data-id="${first}"] .bSend`);
await page.waitForSelector('.sendbox');
ok(await page.$eval('.sendbox', b => b.closest('.bug')?.dataset.id) === first,
   'the send box opens inside the report it would send');
// Model and effort are set once on the Claude card now, not asked per send.
ok(await page.$('#sendModelSel') === null && await page.$('#sendMore') !== null,
   '...with the note field, and no pickers; those moved to the Claude card');
ok(await page.$eval('#sendMore', e => e.value) === '',
   '...and the note starts empty, never carrying words written for something else');
await page.fill('#sendMore', 'it happens on the second run, not the first');
await page.click('#roadmapGo');
await page.waitForFunction(() => !document.querySelector('.sendbox'),
                           null, { timeout: 20000 });
const sent = tmuxCapture('claude-alpha');
ok(new RegExp(`bug B${first}\\b`).test(sent)
   && new RegExp(`bb bug show B${first}`).test(sent),
   'the line names the bug and tells the session to look it up');
ok(!/expected:|actual:|repro:/i.test(sent),
   '...and carries none of the fields, which is the whole point');
ok(/it happens on the second run/.test(sent),
   '...but does carry the operator\'s note');
ok(new RegExp(`bb bug fix B${first}`).test(sent),
   '...and says how to close it when it is dealt with');
// Back into the notebook: the send above lands you in the session's tab.
await page.click(`${row('alpha')} [data-m]`);
await page.click('.pane .nb .nbtabs [data-v="bugs"]');
await page.waitForSelector('#bugList .bug', { timeout: 15000 });
// A closed bug is a record, not work. Both halves of that: the button goes
// dead on the row, and the server refuses even if something asks anyway,
// because a rule only the panel honors is a suggestion.
const closed = await page.$$eval('#bugList .bug',
  ds => ds.filter(d => !d.querySelector('.bReopen')).length === ds.length
        ? null
        : ds.find(d => d.querySelector('.bReopen'))?.dataset.id);
if (closed){
  await openFold(page, `#bugList .bug[data-id="${closed}"]`);
  ok(await page.$eval(`#bugList .bug[data-id="${closed}"] .bSend`, b => b.disabled),
     'a closed bug cannot be sent from the row');
  ok((await page.$eval(`#bugList .bug[data-id="${closed}"] .bSend`, b => b.title))
       .includes('reopen it first'),
     '...and the button says to reopen it rather than going quiet');
  const refused = await post({ action: 'send', project: 'alpha', id: Number(closed) });
  ok(refused.status === 400 && /reopen it first/.test(refused.body.error),
     '...and the server refuses it too, not just the panel');
}
ok(closed !== null, 'there was a closed bug to try it on');

const log = await post({ action: 'history', project: 'alpha' });
ok(log.body.history.some(e => e.act === 'sent' && String(e.id) === String(first)),
   '...and the tracker records that it went, since "was this ever handed over" is a tracker question');

// ---- what the server refuses ------------------------------------------------
for (const [what, body] of [
  ['a project that does not exist', { action: 'add', project: 'nosuch', title: 'x' }],
  ['a project name that is really a path', { action: 'add', project: '../etc', title: 'x' }],
  ['a bug with no title', { action: 'add', project: 'alpha', title: '  ' }],
  ['a severity nobody defined', { action: 'add', project: 'alpha', title: 'x', severity: 'catastrophic' }],
  ['a status nobody defined', { action: 'status', project: 'alpha', id: 1, status: 'maybe' }],
  ['a bug history request for a project that does not exist',
   { action: 'history', project: 'nosuch' }],
  ['a bug nobody has', { action: 'status', project: 'alpha', id: 999, status: 'fixed' }],
  ['an action nobody offers', { action: 'purge', project: 'alpha' }],
  ['deleting a bug nobody has', { action: 'remove', project: 'alpha', id: 999 }],
]){
  const r = await post(body);
  ok(r.status === 400 && r.body.error, `refused: ${what}`);
}
page.errors = [];


// The history sheet covers the PAGE, not the notebook's text column. It is a
// direct child of .nb, and `.nb > *{max-width:var(--doc-w)}` was capping the
// fixed backdrop at 1080px of a 1280px viewport: the dim stopped short of the
// right edge, and everything outside that strip (the header, About, the other
// pane) stayed clickable through the gap, so two dialogs could be open at
// once. One rule reaching one child too far.
const sheetBox = await page.evaluate(async () => {
  document.getElementById('bugLog').click();
  await new Promise(r => setTimeout(r, 400));
  const sh = document.querySelector('.nbsheet:not([hidden])');
  const r = sh.getBoundingClientRect();
  return {w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.x),
          view: [window.innerWidth, window.innerHeight],
          // Anything the operator could reach past it is a second dialog
          // waiting to happen, so the test is "what is on top at the corners".
          topRight: document.elementFromPoint(window.innerWidth - 4, 4) === sh,
          bottomRight: document.elementFromPoint(window.innerWidth - 4,
                                                 window.innerHeight - 4) === sh};
});
ok(sheetBox.w === sheetBox.view[0] && sheetBox.h === sheetBox.view[1] && sheetBox.x === 0,
   'the history sheet dims the whole page, not the notebook\'s text column');
ok(sheetBox.topRight && sheetBox.bottomRight,
   '...so nothing outside it can be clicked while it is open, and a second dialog '
   + 'cannot be opened over the top of it');
// Its own Close, not getElementById: there is one sheet per notebook, so in a
// split there are two of every id inside them.
await page.evaluate(() => {
  const sh = document.querySelector('.nbsheet:not([hidden])');
  sh?.querySelector('.foot button')?.click();
});
await page.waitForFunction(() => !document.querySelector('.nbsheet:not([hidden])'),
                           { timeout: 8000 });

// ---- two writers, one report ---------------------------------------------
// The tracker is write-through and the tab re-reads on bug_rev, so its window
// is one poll, but a report is mostly long text fields, and losing a
// paragraph of somebody's repro to a poll's worth of lateness is exactly the
// silent loss roadmap #26 is about. The form carries the revision it opened
// over. Unlike a roadmap item, a whole form replaces every field at once, so
// the row's own revision is the right unit here.
bbBug('add', 'two people will edit this one', '--sev', 'low');
const twoId = read().find(b => b.title === 'two people will edit this one').id;
await page.evaluate(() => notebooks.get('alpha').reloadBugs());
await page.waitForFunction(i => !!document.querySelector(`#bugList .bug[data-id="${i}"]`),
                           twoId, { timeout: 15000 });
await page.click(`#bugList .bug[data-id="${twoId}"] summary`);
await page.click(`#bugList .bug[data-id="${twoId}"] .bEdit`);
await page.waitForSelector('.bugform .bfTitle', { timeout: 10000 });
await page.fill('.bugform .bfRepro', "the operator's repro, typed at length");
// The other writer, after the form was opened and before it is saved.
bbBug('note', String(twoId), 'a session got here first');
// The form stays on screen either way, so what says the write was refused is
// the revision it now carries. It is waited for, or the second press below
// goes out while the first is still in flight and they both carry the old one.
const formRev = () => page.$eval('.bugform', f => f.dataset.rev);
const opened = await formRev();
await page.click('.bugform .bfGo');
await page.waitForFunction(r => document.querySelector('.bugform')?.dataset.rev !== r,
                           opened, { timeout: 15000 });
ok(read().find(b => b.id === twoId).repro === undefined,
   'a form saved over a report somebody else edited is refused, not applied');
ok(await page.$eval('.bugform .bfRepro', t => t.value)
     === "the operator's repro, typed at length",
   '...with what was typed still in the form, which is the only copy of it');
await page.click('.bugform .bfGo');
await page.waitForFunction(() => !document.querySelector('.bugform .bfTitle'),
                           { timeout: 15000 });
const settledBug = read().find(b => b.id === twoId);
ok(settledBug.repro === "the operator's repro, typed at length"
   && !/a session got here first/.test(settledBug.notes || ''),
   '...and pressing Save again writes it over theirs, note and all, which is '
   + 'what a whole-form edit means, and why the first press had to stop');

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
// A deleted report's number is not handed out again either (bug B72). Last,
// because its two log lines would push the oldest verb off the History
// pane's first page for the check above.
{
  const filed = bbBug('add', 'numbered after the deletions above', '--sev', 'low');
  const n = Number((filed.match(/filed B(\d+)/) || [])[1]);
  ok(n > 5, `a report filed after the newest were deleted gets a new number, not a reused one (B${n})`);
  bbBug('rm', String(n), 'numbering fixture');
}

// B197: the token an open Bugs tab watches was the history's LENGTH, and the
// history is capped, so past 300 events it sat at 300 for good and the tab
// never re-read again. A tracker at the cap, one more write, and the token has
// to have moved.
{
  const call = (path, body) => page.evaluate(async ([p, b]) => {
    const r = await fetch(p, b === null ? {} : { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
    return { status: r.status, ...(await r.json().catch(() => ({}))) };
  }, [path, body ?? null]);
  const fs = await import('node:fs');
  const d = JSON.parse(fs.readFileSync(FILE, 'utf8'));
  const h = (d.history = d.history || {}).alpha = d.history.alpha || [];
  while (h.length < 300) h.unshift({ at: 1, by: 'you', act: 'pad' });
  fs.writeFileSync(FILE, JSON.stringify(d));
  const token = async () => { await page.evaluate(() => pollRevs());
                              await new Promise(r => setTimeout(r, 500));
                              return page.evaluate(() => revs['bug:alpha']); };
  const before = await token();
  const added = await call('/api/bugs', { project: 'alpha', action: 'add', title: 'one more, past the cap',
                                          severity: 'low', area: '', repro: '', expected: '', actual: '', notes: '' });
  const after = await token();
  const len = JSON.parse(fs.readFileSync(FILE, 'utf8')).history.alpha.length;
  ok(!added.error && len === 300 && after !== before,
     `a tracker whose history is at its cap still moves its token on a write (${before} to ${after}, history ${len})`);
}

// The cap is on OPEN bugs. It used to count every row, so a project that had
// fixed 195 and had 5 open could file nothing more, under a message telling
// it to close some, which changed nothing.
{
  const fs = await import('node:fs');
  const d = JSON.parse(fs.readFileSync(FILE, 'utf8'));
  const rows = d.projects.gamma = d.projects.gamma || [];
  const top = rows.reduce((m, r) => Math.max(m, r.id), 0);
  for (let n = 1; n <= 200; n++)
    rows.push({ id: top + n, title: 'done ' + n, severity: 'low', status: 'fixed', rev: 1, by: 'you', at: 1 });
  fs.writeFileSync(FILE, JSON.stringify(d));
  const r = await page.evaluate(async () => (await fetch('/api/bugs', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'gamma', action: 'add', title: 'one more, with 200 fixed behind it',
                           severity: 'low', area: '', repro: '', expected: '', actual: '', notes: '' }) })).json());
  ok(!r.error, `200 fixed bugs do not stop the next one being filed (${r.error || 'filed'})`);
}

await done(browser);
