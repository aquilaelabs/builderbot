// A pane keeps the terminals behind the visible one loaded.
//
// Switching tabs used to rebuild the pane's innerHTML, which threw the iframe
// away, and ttyd is 700KB of javascript that then had to parse, connect a
// websocket, attach to tmux and draw. On a phone that was a second and a half
// of blank pane, every switch. The frames now sit on top of one another at the
// same size with one visible, so coming back to one is a class toggle.
//
// Same size matters as much as staying loaded: a hidden frame is still an
// attached tmux client, and tmux sizes a window to its smallest client.
import { launch, newPage, ok, done, ready, URL } from './lib.mjs';
import { readFileSync, readdirSync } from 'node:fs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
await ready(page);

// Three terminals, so there is something to switch between and something to
// push past the keep-alive ceiling.
await page.evaluate(() => { newShell(''); newShell('alpha'); newShell('beta'); });
await page.waitForFunction(() => tabs.filter(t => t.kind === 'term').length >= 3,
                           { timeout: 20000 });
const ids = await page.evaluate(() => tabs.filter(t => t.kind === 'term').map(t => t.id));

// A terminal is the dock's (R218 step 4): shown there, the dock up.
const show = id => page.evaluate(id => { panes[1] = id; dockUp = true; render(); }, id);
// The terminals the pane keeps: its slots. A page opens on the Projects tab
// now (R119), whose document is in the same stack and is not a terminal.
const seen = () => page.evaluate(() => [...document.querySelectorAll('#pane1 .stack > .slot')]
  .map(c => ({ key: c.dataset.key, on: c.classList.contains('on') })));

await show(ids[0]);
await page.waitForSelector('#pane1 .slot.on iframe');
// Stamp the frame, so a rebuild is detectable: a new element loses the mark.
await page.evaluate(() => { document.querySelector('#pane1 .slot.on').dataset.mark = 'first'; });

await show(ids[1]);
await page.waitForFunction(id => document.querySelector('#pane1 .slot.on')?.dataset.key
  ?.startsWith(id + '|'), ids[1]);
let rows = await seen();
ok(rows.filter(r => r.on).length === 1
   && rows.some(r => r.key?.startsWith(ids[0] + '|'))
   && rows.some(r => r.key?.startsWith(ids[1] + '|')),
   `switching away keeps the first terminal in the pane, not on screen (${JSON.stringify(rows)})`);
ok(await page.$eval('#pane1 .stack > [data-mark="first"]',
     el => getComputedStyle(el).visibility === 'hidden'),
   '...hidden rather than removed');
ok(await page.$eval('#pane1 .stack > [data-mark="first"]', el => {
     const r = el.getBoundingClientRect(), o = document.querySelector('#pane1 .slot.on')
       .getBoundingClientRect();
     return Math.abs(r.width - o.width) < 1 && Math.abs(r.height - o.height) < 1
            && r.width > 0;
   }), '...and at exactly the size of the visible one, so tmux has nothing to resize');

await show(ids[0]);
ok(await page.$eval('#pane1 .slot.on', el => el.dataset.mark === 'first'),
   'coming back shows the same element (no reload)');
ok(await page.$$eval('#pane1 .slot.on iframe', f => f.length === 1),
   '...and exactly one terminal is on screen');

// No ceiling below the strip's own (the operator, 6 Oct): every terminal tab
// on the strip stays attached, and Minimize is what detaches one.
await show(ids[2]);
const fourth = await page.evaluate(() => { newShell('gamma'); return null; });
await page.waitForFunction(() => tabs.filter(t => t.kind === 'term').length >= 4,
                           { timeout: 20000 });
const id4 = await page.evaluate(() => tabs.filter(t => t.kind === 'term').at(-1).id);
await show(id4);
rows = await seen();
const before = rows.length;
ok([...ids, id4].every(id => rows.some(r => r.key?.startsWith(id + '|'))),
   `a pane keeps every terminal on the strip attached, the fourth included (${rows.map(r => r.key).join(' ')})`);
await page.evaluate(id => hideTab(id), id4);
await page.waitForFunction(id => ![...document.querySelectorAll('#pane1 .stack > .slot')]
  .some(c => c.dataset.key?.startsWith(id + '|')), id4, { timeout: 5000 }).catch(() => {});
rows = await seen();
ok(rows.length === before - 1 && !rows.some(r => r.key?.startsWith(id4 + '|')),
   `...and Minimize detaches one: its frame goes with its tab (${rows.length})`);
void fourth;

// A document tab is not kept: it redraws from state instantly, and one #docN
// per pane is what renders into it.
await page.evaluate(() => openTab({kind: 'toolchains', arg: '__toolchains', label: 'toolchains'}));
await page.waitForSelector('#pane0 .doc.on');
// One #docN per pane is the invariant: the element of a tab shown before is
// kept behind, unnamed, so bringing it back is its own painted ground on the
// first frame (uniform.mjs holds that), and a page opening on the Projects
// tab (R119) leaves its document there.
ok(await page.$$eval('#pane0 .stack > .doc', d => d.filter(x => x.id === 'doc0').length === 1
     && d.find(x => x.id === 'doc0').classList.contains('on')),
   `a document tab is one per pane, and keeps the id that renders into it (${
     await page.$$eval('#pane0 .stack > .doc', d => d.map(x => x.id + ':' + x.className).join(' '))})`);
const slotsBefore = rows.length;
ok(await page.$$eval('#pane1 .stack > .slot', (s, n) => s.length === n, slotsBefore),
   `...and opening it did not disturb the terminals behind it (${
     await page.$$eval('#pane1 .stack > *', c => c.map(x => x.dataset.key).join(' '))})`);

// Coming back to a page a phone had backgrounded reconnects the terminal that
// is on screen, and only that one. All of them at once was six ttyd instances
// starting together (700KB of javascript, a websocket and a full repaint
// each) on the device least able to afford it, which is what the page spent
// its first seconds back doing.
await page.evaluate(() => openTab({kind: 'term', arg: 'shell', label: 'sh'}));
await page.waitForSelector('#pane1 .slot.on iframe');
await page.setViewportSize({ width: 412, height: 900 });      // the phone path
let reloads = 0;
page.on('framenavigated', f => { if (f.url().includes('/term')) reloads++; });
// Headless Chromium never really backgrounds a page, so the state it reads is
// faked and the event it listens for is dispatched by hand.
await page.evaluate(() => {
  let v = 'hidden';
  Object.defineProperty(document, 'visibilityState', { get: () => v, configurable: true });
  Object.defineProperty(document, 'hidden', { get: () => v === 'hidden', configurable: true });
  window.__show = () => { v = 'visible'; document.dispatchEvent(new Event('visibilitychange')); };
  document.dispatchEvent(new Event('visibilitychange'));
});
await new Promise(r => setTimeout(r, 3600));    // past the "really dropped" gate
reloads = 0;
await page.evaluate(() => window.__show());
await new Promise(r => setTimeout(r, 1500));
ok(reloads === 1, `returning reconnects the terminal on screen, and only it (${reloads})`);
const behind = await page.$$eval('#pane1 .slot:not(.on) iframe',
                                 f => f.map(x => !!x.dataset.stale));
ok(behind.length > 0 && behind.every(Boolean),
   `...the ones behind it are marked instead (${behind.length})`);

// ...and a marked one reconnects when it is next brought forward.
await page.setViewportSize({ width: 1280, height: 800 });
const asleep = await page.$eval('#pane1 .slot:not(.on) iframe',
                                f => f.closest('.slot').dataset.key.split('|')[0]);
reloads = 0;
await show(asleep);
await new Promise(r => setTimeout(r, 1500));
ok(reloads === 1, `bringing one forward reconnects it then (${reloads})`);
ok(await page.$$eval('#pane1 .slot.on iframe', f => !f[0].dataset.stale),
   '...and it is not marked twice');

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
// One window onto one thing. A notebook is per project and several may be
// open; everything else is a single view, and a second open focuses the first
// whatever argument it carries. That is enforced by the kind's own entry
// rather than by every caller remembering to pass the same magic arg.
const kindCount = (k) => page.evaluate((kk) => tabs.filter(t => t.kind === kk).length, k);
for (const k of ['projects', 'docker', 'toolchains']){
  await page.evaluate((kk) => { openTab({kind: kk, arg: 'one', label: kk});
                                openTab({kind: kk, arg: 'two', label: kk}); }, k);
  ok(await kindCount(k) === 1, `only one ${k} tab, whatever it is opened with`);
}
await page.evaluate(() => { openTab({kind: 'notebook', arg: 'alpha', label: 'a'});
                            openTab({kind: 'notebook', arg: 'beta', label: 'b'}); });
ok(await kindCount('notebook') >= 2,
   '...while notebooks are one per project, which is the whole point of them');

// Every tab kind the page knows must be one the SERVER will keep. A kind
// missing from TAB_KINDS is dropped from the saved layout without a word, so
// the tab comes back from a reload as if it had never been opened, which has
// happened, and is invisible until somebody reloads. Compared against the
// files rather than trusted, because the two are in different languages and
// nothing else makes them agree.
// Every script the page is made of: TABKINDS is page-tabs.js's since R77.
const html = ['index.html', ...readdirSync(new globalThis.URL('..', import.meta.url))
    .filter(f => /^(page|tab|nb)-.*\.js$/.test(f))]
  .map(f => readFileSync(new globalThis.URL('../' + f, import.meta.url).pathname, 'utf8')).join('\n');
// The server's half is layout.py's since R77: what a saved layout may carry.
const py = readFileSync(new globalThis.URL('../layout.py', import.meta.url).pathname, 'utf8');
const inPage = [...html.matchAll(/^ {2}([a-z]+):\s*\{ multi:/gm)].map(m => m[1]).sort();
const inServer = (py.match(/^TAB_KINDS = \{([^}]*)\}/m) || [, ''])[1]
  .match(/"([a-z]+)"/g).map(s => s.replace(/"/g, '')).sort();
ok(inPage.length > 3 && JSON.stringify(inPage) === JSON.stringify(inServer),
   `every tab kind the page has is one the server keeps (page: ${inPage}, server: ${inServer})`);

// The limit is on terminals, per account (R78): a shell past it is refused
// with a toast that says so, and a document tab opens past it, because it
// costs no terminal. The strip counted is this account's own layout.
// Each in one round trip: a status poll landing between setting the limit
// and opening the tab put the server's limit back, and the shell opened
// (B289).
{
  const shell = await page.evaluate(() => {
    state.max_tabs = tabs.filter(t => t.kind === 'term').length;
    const before = tabs.length;
    openTab({kind: 'term', arg: 'sh:99:alpha', label: 'sh 99'});
    return { before, after: tabs.length,
             said: /Terminal tab limit reached/.test(document.body.textContent) };
  });
  ok(shell.after === shell.before && shell.said,
     'a shell past the terminal limit is refused, and the toast names the terminal limit');
  const doc = await page.evaluate(() => {
    state.max_tabs = tabs.filter(t => t.kind === 'term').length;
    const before = tabs.length;
    openNodesTab();
    return { before, after: tabs.length, nodes: tabs.some(t => t.kind === 'nodes') };
  });
  ok(doc.after === doc.before + 1 && doc.nodes,
     '...while a document tab opens past it: it costs no terminal');
  await page.evaluate(() => { state.max_tabs = 12; });
}

// A terminal in its own window (R8): the pop-out opens the terminal's own
// URL in a window, the tab stays as a placeholder with Reattach and its
// frame is torn down (a second client on the session is the size fight),
// the layout carries the flag, and the window closing brings the tab back.
{
  const id = ids[1];
  await page.evaluate(id => dockShow(id), id);
  await page.evaluate(() => { window.__pops = []; window.open = (url, name) => {
    const w = { url, name, closed: false, close(){ this.closed = true; } }; window.__pops.push(w); return w; }; });
  await page.click('#pane1 .bar [data-pop]');
  ok(await page.evaluate(() => window.__pops.length === 1 && /^\/term\/\?arg=/.test(window.__pops[0].url) && /^bb-pop-/.test(window.__pops[0].name)),
     'the pop-out opens the terminal in its own window, on its own /term connection');
  ok(await page.evaluate(id => tabOf(id).popped === true
       && !document.querySelector(`#pane1 .stack > [data-key^="${id}|"] iframe`)
       && !!document.querySelector('#pane1 .slot.popped.on .reattach'), id),
     '...and the tab stays, blank, with Reattach, its frame torn down');
  ok(await page.evaluate(id => layoutNow().tabs.find(t => t.id === id).popped === true, id),
     '...and the layout carries the flag');
  ok(await page.$eval('#pane1 .bar [data-pop]', b => /reattach/.test(saidOf(b))),
     "...and the dock's button now says reattach");
  await page.click('#pane1 .slot.popped.on .reattach');
  ok(await page.evaluate(id => tabOf(id).popped === false && window.__pops[0].closed === true
       && !!document.querySelector(`#pane1 .stack > [data-key^="${id}|"].on iframe`), id),
     'Reattach closes the window and the terminal is back in the pane');
  await page.click('#pane1 .bar [data-pop]');
  await page.evaluate(() => { window.__pops[1].closed = true; });
  await page.waitForFunction(id => tabOf(id).popped === false, id, { timeout: 6000 });
  ok(await page.evaluate(id => !!document.querySelector(`#pane1 .stack > [data-key^="${id}|"].on iframe`), id),
     'closing the popped window brings the tab back on its own');
}

await done(browser);
