// A pane keeps the terminals behind the visible one loaded.
//
// Switching tabs used to rebuild the pane's innerHTML, which threw the iframe
// away — and ttyd is 700KB of javascript that then had to parse, connect a
// websocket, attach to tmux and draw. On a phone that was a second and a half
// of blank pane, every switch. The frames now sit on top of one another at the
// same size with one visible, so coming back to one is a class toggle.
//
// Same size matters as much as staying loaded: a hidden frame is still an
// attached tmux client, and tmux sizes a window to its smallest client.
import { launch, newPage, ok, done, ready, URL } from './lib.mjs';

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

const show = id => page.evaluate(id => { panes[0] = id; render(); }, id);
const seen = () => page.evaluate(() => [...document.querySelectorAll('#pane0 .stack > *')]
  .map(c => ({ key: c.dataset.key, on: c.classList.contains('on') })));

await show(ids[0]);
await page.waitForSelector('#pane0 .slot.on iframe');
// Stamp the frame, so a rebuild is detectable: a new element loses the mark.
await page.evaluate(() => { document.querySelector('#pane0 .slot.on').dataset.mark = 'first'; });

await show(ids[1]);
await page.waitForFunction(id => document.querySelector('#pane0 .slot.on')?.dataset.key
  ?.startsWith(id + '|'), ids[1]);
let rows = await seen();
ok(rows.filter(r => r.on).length === 1
   && rows.some(r => r.key?.startsWith(ids[0] + '|'))
   && rows.some(r => r.key?.startsWith(ids[1] + '|')),
   `switching away keeps the first terminal in the pane, not on screen (${JSON.stringify(rows)})`);
ok(await page.$eval('#pane0 .stack > [data-mark="first"]',
     el => getComputedStyle(el).visibility === 'hidden'),
   '...hidden rather than removed');
ok(await page.$eval('#pane0 .stack > [data-mark="first"]', el => {
     const r = el.getBoundingClientRect(), o = document.querySelector('#pane0 .slot.on')
       .getBoundingClientRect();
     return Math.abs(r.width - o.width) < 1 && Math.abs(r.height - o.height) < 1
            && r.width > 0;
   }), '...and at exactly the size of the visible one, so tmux has nothing to resize');

await show(ids[0]);
ok(await page.$eval('#pane0 .slot.on', el => el.dataset.mark === 'first'),
   'coming back shows the same element — no reload');
ok(await page.$$eval('#pane0 .slot.on iframe', f => f.length === 1),
   '...and exactly one terminal is on screen');

// The ceiling. A fourth terminal drops the one used longest ago.
await show(ids[2]);
const fourth = await page.evaluate(() => { newShell('gamma'); return null; });
await page.waitForFunction(() => tabs.filter(t => t.kind === 'term').length >= 4,
                           { timeout: 20000 });
const id4 = await page.evaluate(() => tabs.filter(t => t.kind === 'term').at(-1).id);
await show(id4);
rows = await seen();
ok(rows.length === 3, `a pane keeps three terminals, not every one ever opened (${rows.length})`);
ok(!rows.some(r => r.key?.startsWith(ids[1] + '|')),
   '...and the one dropped is the one used longest ago');

// A document tab is not kept: it redraws from state instantly, and one #docN
// per pane is what renders into it.
await page.evaluate(() => openTab({kind: 'packages', arg: '__packages', label: 'packages'}));
await page.waitForSelector('#pane0 .doc.on');
ok(await page.$$eval('#pane0 .stack > .doc', d => d.length === 1
     && d[0].id === 'doc0'),
   'a document tab is one per pane, and keeps the id that renders into it');
ok(await page.$$eval('#pane0 .stack > .slot', s => s.length === 3),
   `...and opening it did not disturb the terminals behind it (${
     await page.$$eval('#pane0 .stack > *', c => c.map(x => x.dataset.key).join(' '))})`);

// Coming back to a page a phone had backgrounded reconnects the terminal that
// is on screen, and only that one. All of them at once was six ttyd instances
// starting together — 700KB of javascript, a websocket and a full repaint
// each — on the device least able to afford it, which is what the page spent
// its first seconds back doing.
await page.evaluate(() => openTab({kind: 'term', arg: 'shell', label: 'sh'}));
await page.waitForSelector('#pane0 .slot.on iframe');
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
const behind = await page.$$eval('#pane0 .slot:not(.on) iframe',
                                 f => f.map(x => !!x.dataset.stale));
ok(behind.length > 0 && behind.every(Boolean),
   `...the ones behind it are marked instead (${behind.length})`);

// ...and a marked one reconnects when it is next brought forward.
await page.setViewportSize({ width: 1280, height: 800 });
const asleep = await page.$eval('#pane0 .slot:not(.on) iframe',
                                f => f.closest('.slot').dataset.key.split('|')[0]);
reloads = 0;
await show(asleep);
await new Promise(r => setTimeout(r, 1500));
ok(reloads === 1, `bringing one forward reconnects it then (${reloads})`);
ok(await page.$$eval('#pane0 .slot.on iframe', f => !f[0].dataset.stale),
   '...and it is not marked twice');

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
await done(browser);
