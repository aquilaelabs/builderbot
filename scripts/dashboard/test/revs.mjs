// Which clock a view is on, and the rule that there is only one.
//
// The page has exactly two: /api/status every fifteen seconds, which runs git
// for every project and carries what only it knows, and /api/revs every
// second and a half, which is stats and counters and is what a view watches
// to know it must re-read. Anything a person is waiting for after pressing
// something is redrawn by the handler itself; anything arriving from
// elsewhere — another window, a session, `bb`, a node — arrives on the
// revisions poll.
//
// What this file measures is the join between the two halves, because that is
// where it drifted: the server published a token for the Settings tab and for
// the package store and NOTHING watched either, so those two waited on the
// fifteen-second poll while the tab beside them woke in a second; and five of
// the notebook's six halves rode a counter on the status payload while the
// sixth rode this one. Both are the same failure — a view whose clock nobody
// chose — and neither shows up as a broken test anywhere else, because the
// page is not wrong afterwards, only late.
import { URL, launch, newPage, ok, done, ready, sleep, patience } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);

// What the page is watching, and what the server sends it. Both read the same
// way the poll does: the watch keys are evaluated, because half of them are
// functions that close over a project.
const watched = () => page.evaluate(() => [...new Set(revWatch
  .map(w => (typeof w.key === 'function' ? w.key() : w.key)).filter(Boolean))]);
const served = () => page.evaluate(async () => {
  const ps = [...new Set(tabs.filter(t => t.kind === 'notebook').map(t => t.arg))];
  const r = await fetch('/api/revs?p=' + encodeURIComponent(ps.join(',')));
  return Object.keys(await r.json());
});
// pollRevs reads it itself, before any watch is consulted: a new container is
// not news for a view, it is the end of the page.
const OWN = ['boot'];

const bare = { watched: await watched(), served: await served() };
let orphan = bare.watched.filter(k => !bare.served.includes(k));
ok(orphan.length === 0,
   `every watch is on a token the server sends${
     orphan.length ? ` — never sent: ${orphan.join(', ')}` : ''} (${
     bare.watched.length} watched)`);
ok(!bare.served.some(k => k.includes(':')),
   'a page with no notebook open is sent no per-project tokens');

// The per-project half, which only a notebook watches — and the state in
// which every token has somebody watching it, since three of the global ones
// (the reports, the findings log, the version policy) are a notebook's too.
await page.evaluate(() => setView('terminal'));
await page.evaluate(() => openNotebook('alpha', 'roadmap'));
// Not the list itself: the fixture's alpha has an empty roadmap, and the
// field around the list is hidden until there is something in it.
await page.waitForSelector('.nb [data-view="roadmap"]:not([hidden])',
                           { timeout: 20000 });
await sleep(patience(500));
const open = { watched: await watched(), served: await served() };
const extra = open.served.filter(k => !OWN.includes(k) && !open.watched.includes(k));
ok(extra.length === 0,
   `with a notebook open, every token the server sends is watched${
     extra.length ? ` — nobody watches: ${extra.join(', ')}` : ''} (${
     open.served.length} sent)`);
orphan = open.watched.filter(k => !open.served.includes(k));
ok(orphan.length === 0,
   `...and every watch is on a token the server sends${
     orphan.length ? ` — never sent: ${orphan.join(', ')}` : ''} (${
     open.watched.length} watched)`);
const per = open.served.filter(k => k.includes(':'));
ok(per.length > 0 && per.every(k => k.endsWith(':alpha')),
   `...and the per-project tokens are the open notebook's alone (${
     per.join(', ') || 'none'})`);

// The six halves, named, because "the notebook re-reads" is the claim and a
// list of six is what makes it checkable.
const HALVES = ['roadmap:alpha', 'mem:alpha', 'bug:alpha',
                'tests:alpha', 'rules:alpha', 'pending:alpha'];
const missing = HALVES.filter(k => !open.watched.includes(k));
ok(missing.length === 0,
   `every half of the notebook watches its own token${
     missing.length ? ` — not: ${missing.join(', ')}` : ''}`);
// ...and none of them is still reading a revision off the status payload,
// which is the shape the drift took the first time.
const onStatus = await page.evaluate(async () => {
  const r = await fetch('/api/status');
  const p = (await r.json()).projects.find(x => x.name === 'alpha') || {};
  return Object.keys(p).filter(k => /_rev$/.test(k));
});
ok(onStatus.length === 0,
   `...and no revision is left on the status payload${
     onStatus.length ? ` — still there: ${onStatus.join(', ')}` : ''}`);

// The behaviour all of that is for: another window writes, and this one shows
// it without being touched. Bounded, because the point is the clock — the
// status poll could not do this in the time allowed, and before this change
// it was the only thing that would have.
// The token has to have reached this page at least once, or what follows is
// testing the poll that first names the project rather than the one that
// notices it moving. Both work; only one of them is this test.
await page.waitForFunction(() => revs['roadmap:alpha'] !== undefined,
                           null, { timeout: 15000 });
const other = await newPage(browser);
await other.goto(URL);
await ready(other);
const mark = 'a line written from the other window ' + Date.now();
await other.evaluate(async text => {
  await fetch('/api/roadmap', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project: 'alpha', action: 'add', text }) });
}, mark);
const began = Date.now();
await page.waitForFunction(
  t => [...document.querySelectorAll('#roadmapList')]
         .some(el => el.textContent.includes(t)),
  mark, { timeout: 9000 });
const took = Date.now() - began;
ok(took < patience(9000),
   `a roadmap item added in another window arrives without a touch (${
     (took / 1000).toFixed(1)}s)`);

// A closed notebook stops watching. Its thirteen watches close over a root
// that removal only detaches, and `showing()` reads .hidden off a detached
// element perfectly happily — so every notebook ever closed went on fetching
// its artifacts and its version, once per token that moved, forever.
const before = await page.evaluate(() => revWatch.length);
await page.evaluate(() => {
  const t = tabs.find(x => x.kind === 'notebook' && x.arg === 'alpha');
  if (t) hideTab(t.id);          // the ✕: it is what ends a notebook's instance
});
await sleep(patience(600));
const after = await page.evaluate(() => revWatch.length);
ok(after < before,
   `closing a notebook puts its watches down (${before} -> ${after})`);
ok((await watched()).every(k => !k.endsWith(':alpha')),
   '...so nothing is left watching a project with no notebook open');

ok(page.errors.length === 0,
   `zero console errors${page.errors.length ? ': ' + page.errors[0] : ''}`);
await done(browser);
