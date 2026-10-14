// Desktop mouse: tab drag reorders in place with a slide, the click ending a
// drag does not switch tabs, a plain click does, tab enter/exit animations.
import { launch, newPage, ok, done, ready, layoutSettled, URL, animatedDuring } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
await page.waitForFunction(() => document.querySelectorAll('#commands [data-m]').length > 0, { timeout: 40000 });
// The dock (R218 step 4): three shells on its line, the workspace's and two
// more; a press on one brings it forward, its − puts it away.
await page.evaluate(() => { newShell(''); newShell(''); });
await page.waitForFunction(() => document.querySelectorAll('#pane1 .dtab[data-id]').length === 3);
const ids0 = await page.$$eval('#pane1 .dtab[data-id]', ts => ts.map(t => t.dataset.id));
ok(await page.evaluate(() => tabOf(panes[0])?.kind !== 'term' && tabOf(panes[1])?.kind === 'term'),
   'a page is on show and the terminals are the dock\'s');
await page.click(`#pane1 .dtab[data-id="${ids0[1]}"] .dlbl`);
await page.waitForFunction(id => panes[1] === id, ids0[1], { timeout: 5000 });
ok(true, 'a press on a terminal in the dock brings it forward');
await page.click(`#pane1 .dtab[data-id="${ids0[1]}"] [data-min]`);
await page.waitForFunction(id => !tabs.some(t => t.id === id), ids0[1], { timeout: 5000 });
ok(await page.evaluate(() => tabOf(panes[1])?.kind === 'term'), '...and its − puts it away, the next terminal taking the dock');
await page.evaluate(() => dockToggle(true));
await page.waitForSelector('#pane1 .slot.on iframe', { timeout: 10000 });
// The frame carries the terminal's own color, because its document is
// transparent until xterm paints and this page's dark color-scheme makes the
// browser fill that gap with white. Without this the tab switch flashed.
ok(await page.$eval('#pane1 .slot.on iframe', el => {
     const c = getComputedStyle(el).backgroundColor;
     return c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent';
   }), 'a terminal frame is not transparent while it loads');
// A desktop has a keyboard, so it has no on-screen one: the bar hides the
// one it keeps for phones.
ok(!await page.$('#bKeys')
   && await page.$eval('#mKeys', el => getComputedStyle(el).display === 'none'),
   'no on-screen keys control on a desktop, from either place it used to be');

// A poll that changes nothing rebuilds nothing: the same elements stay put
// (so :hover survives), and a mid-action edit to one is not wiped.
await page.evaluate(async () => { await refresh(); await refresh(); });   // let the just-opened shells register
await page.evaluate(() => { document.querySelector('.side .card[data-card="doctor"]').dataset.mark = 'kept';
                            document.querySelector('#pane1 .dtab[data-id]').dataset.mark = 'kept'; });
await page.evaluate(() => refresh());
ok(await page.$eval('.side .card[data-card="doctor"]', el => el.dataset.mark === 'kept')
   && await page.$eval('#pane1 .dtab[data-id]', el => el.dataset.mark === 'kept'),
   'an unchanged poll leaves the cards and the dock\'s line alone');
await page.evaluate(() => newShell(''));
ok(await page.$eval('#pane1 .dtab[data-id]', el => el.dataset.mark !== 'kept'), '...while a real change repaints');

// Focus landing in the dock's terminal gives the dock the keyboard, though
// the click happens inside a cross-origin iframe; a press on the page gives
// it back; shut, the dock keeps its terminal.
await page.waitForSelector('#pane1 .slot.on iframe', { timeout: 10000 });
await page.evaluate(() => { active = 0; document.querySelector('#pane1 .slot.on iframe').focus(); window.dispatchEvent(new Event('blur')); });
ok(await page.evaluate(() => active === 1), "focus into the dock's terminal gives the dock the keyboard");
await page.click('#pane0 .bar');
ok(await page.evaluate(() => active === 0), '...and a press on the page gives it back');
const keptTerm = await page.evaluate(() => panes[1]);
await page.click('#pane1 [data-dtoggle]');
ok(await page.evaluate(t => !dockUp && panes[1] === t && !document.getElementById('panes').classList.contains('dockup'), keptTerm),
   'the chevron puts the dock down to its line, keeping its terminal');
ok(await page.$eval('#pane1', p => p.getBoundingClientRect().height < 60), '...a line tall');
await page.click('#pane1 [data-dtoggle]');
ok(await page.evaluate(() => dockUp && document.getElementById('panes').classList.contains('dockup')), '...and up again');

// A stale poll, one revision behind what this page already wrote, must
// not be adopted, or the tab just removed would come back.
const stale = await page.evaluate(() => {
  const before = tabs.map(t => t.id).join();
  adoptLayout({ rev: myRev - 1, tabs: [{id:'zz', kind:'term', arg:'shell', label:'x'}], panes:['zz', null], active: 0 });
  return tabs.map(t => t.id).join() === before && myRev >= 0;
});
ok(stale, 'a layout one revision behind is ignored');

// R131: which tab is in front is this browser's own. A layout another
// browser wrote with a different tab in front still brings its tabs, and
// leaves this browser's front tab where it was; a reload keeps it; and a
// switch here writes nothing to the server.
// A page of this browser's in front, its tab saved, before the other
// browser's layout arrives.
await page.evaluate(() => openJobsTab());
await page.waitForFunction(() => !savePending && !pushing, null, { timeout: 10000 });   // the last push landed
const front = await page.evaluate(() => {
  const was = panes[0];
  const theirs = tabs.map(t => ({id:t.id, kind:t.kind, arg:t.arg, label:t.label}));
  theirs.push({id:'r131', kind:'jobs', arg:'', label:'theirs'});
  adoptLayout({ rev: myRev + 1, tabs: theirs, panes:[tabs[0].id, null], active: 0 });
  return { kept: panes[0] === was, added: tabs.some(t => t.id === 'r131'), was };
});
ok(front.kept && front.added, `a strip another browser wrote brings its new tab and leaves this browser's front tab alone (${JSON.stringify(front)})`);
await page.reload({ waitUntil: 'domcontentloaded' });
await ready(page);
const kept = await page.evaluate(() => panes[0]);
ok(kept === front.was, `...and a reload keeps this browser's front tab (${kept})`);
const quiet = await page.evaluate(async () => {
  const rev = myRev, other = tabs.find(t => t.id !== panes[0]).id;
  focusTab(other);
  await new Promise(r => setTimeout(r, 900));          // past the 400 ms save debounce
  return { rev, now: myRev, front: panes[active], other };
});
ok(quiet.now === quiet.rev && quiet.front === quiet.other, `...and switching tabs writes nothing to the server (rev ${quiet.rev} still ${quiet.now}, ${quiet.front} in front)`);

// A card another browser folded folds here with the tween, on the poll.
await page.evaluate(async () => { const c = JSON.parse(JSON.stringify(cards)); c.closed.push('runner');
  await fetch('/api/cards', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(c)}); });
const folded = await page.evaluate(async () => {
  const el = document.querySelector('.card[data-card="runner"]');
  const p = refresh();
  for (let i = 0; i < 600; i++){          // up to 3s: the poll has to come back first
    if (el.getAnimations().length > 0) return 'slid';
    if (el.classList.contains('closed')) return 'snapped';
    await new Promise(r => setTimeout(r, 5));
  }
  await p; return 'nothing';
});
ok(folded === 'slid', `a fold from another browser slides shut here (${folded})`);
ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);
await done(browser);
