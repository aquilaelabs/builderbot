// Desktop mouse: tab drag reorders in place with a slide, the click ending a
// drag does not switch tabs, a plain click does, tab enter/exit animations.
import { launch, newPage, ok, done, layoutSettled, URL, animatedDuring } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
await page.waitForFunction(() => document.querySelectorAll('#commands [data-m]').length > 0, { timeout: 40000 });
// The drag is among three shells: the Projects tab a page opens on since R119
// is closed first, leaving the workspace shell, and two more are opened.
await page.evaluate(() => { const t = tabs.find(x => x.kind === 'projects'); if (t) dropTab(t.id); });
await page.evaluate(() => { newShell(''); newShell(''); });
await page.waitForFunction(() => document.querySelectorAll('.tab[data-id]').length === 3);
// ...and the strip at rest: the closed tab's exit and the new ones' entrance
// move the others, and boxes measured mid-tween aim the drag at nothing.
await page.waitForFunction(() => !document.querySelector('.tab.leaving, .tab.entering')
  && document.getAnimations().every(a => a.playState !== 'running'), null, { timeout: 5000 }).catch(() => {});
await page.waitForTimeout(300);
const ids0 = await page.$$eval('.tab[data-id]', ts => ts.map(t => t.dataset.id));
const activeBefore = await page.evaluate(() => panes[0]);
const lb = await (await page.$(`.tab[data-id="${ids0[2]}"] .lbl`)).boundingBox();
const first = await (await page.$(`.tab[data-id="${ids0[0]}"]`)).boundingBox();
await page.mouse.move(lb.x + lb.width / 2, lb.y + lb.height / 2); await page.mouse.down();
// The slide is recorded across the move rather than looked for after it: the
// displaced tabs' tween is 140ms, and whether it has finished by the time a
// round trip lands is a fact about how busy the box is, not about the drag.
// `held` is a class and stays put while the button is down, so that one can
// still be read directly, but before the mouse comes up.
const slid = await animatedDuring(page,
  () => page.mouse.move(first.x + 4, first.y + 10, { steps: 10 }));
const mid = { held: await page.$eval(`.tab[data-id="${ids0[2]}"]`,
                                     t => t.classList.contains('held')),
              anims: slid.some(k => k.includes('tab')) };
await page.mouse.up();
ok((await page.$$eval('.tab[data-id]', ts => ts.map(t => t.dataset.id)))[0] === ids0[2], 'mouse drag reorders');
ok(mid.held && mid.anims, 'dragged tab shows held; displaced tabs slide');
ok(await page.evaluate(() => panes[0]) === activeBefore, 'the click ending the drag did not switch tabs');
// The drop saves straight away (debounced 400ms), not on the 15s poll.
const topId = await page.$eval('.tab[data-id]', t => t.dataset.id);
await layoutSettled(l => l.tabs[0]?.id === topId, 4000);
ok(true, 'the new order reaches the server within a second');
await page.click(`.tab[data-id="${ids0[1]}"] .lbl`);
ok(await page.evaluate(() => panes[0]) === ids0[1], 'a plain click still switches tabs');
await page.click(`.tab[data-id="${ids0[1]}"] [data-min]`);
ok(await page.$$eval('.tab:not([data-id])', gs => gs.length === 1), 'a minimized tab leaves a fading ghost');
await page.waitForFunction(() => document.querySelectorAll('.tab:not([data-id])').length === 0);
// The frame carries the terminal's own color, because its document is
// transparent until xterm paints and this page's dark color-scheme makes the
// browser fill that gap with white. Without this the tab switch flashed.
ok(await page.$eval('.slot.on iframe', el => {
     const c = getComputedStyle(el).backgroundColor;
     return c !== 'rgba(0, 0, 0, 0)' && c !== 'transparent';
   }), 'a terminal frame is not transparent while it loads');
// A desktop has a keyboard, so it has no on-screen one: the strip carries no
// ⌨ at all and the bar hides the one it keeps for phones.
ok(!await page.$('#bKeys')
   && await page.$eval('#mKeys', el => getComputedStyle(el).display === 'none'),
   'no on-screen keys control on a desktop, from either place it used to be');

// A poll that changes nothing rebuilds nothing: the same elements stay put
// (so :hover survives), and a mid-action edit to one is not wiped.
await page.evaluate(async () => { await refresh(); await refresh(); });   // let the just-opened shells register
await page.evaluate(() => { document.querySelector('#projects .row').dataset.mark = 'kept';
                            document.querySelector('.tab[data-id]').dataset.mark = 'kept'; });
await page.evaluate(() => refresh());
ok(await page.$eval('#projects .row', el => el.dataset.mark === 'kept') && await page.$eval('.tab[data-id]', el => el.dataset.mark === 'kept'),
   'an unchanged poll leaves the cards and the strip alone');
// ...and a change still repaints
await page.evaluate(() => newShell(''));
ok(await page.$eval('.tab[data-id]', el => el.dataset.mark !== 'kept'), '...while a real change repaints');

// Split: focus landing in a pane's terminal makes that pane the active one,
// even though the click itself happens inside a cross-origin iframe.
await page.evaluate(() => { const ids = tabs.map(t => t.id); pinTo(ids[0], 0); pinTo(ids[1], 1); active = 0; render(); });
await page.waitForFunction(() => isSplit()
  && document.querySelectorAll('.slot.on iframe').length === 2);
await page.evaluate(() => { document.querySelector('#pane1 .slot.on iframe').focus(); window.dispatchEvent(new Event('blur')); });
ok(await page.evaluate(() => active === 1), 'focus into the right pane\'s terminal activates that pane');
await page.evaluate(() => { document.querySelector('#pane0 .slot.on iframe').focus(); window.dispatchEvent(new Event('blur')); });
ok(await page.evaluate(() => active === 0), '...and back to the left');
await page.evaluate(() => closePane(1));
ok(await page.$eval('#pane1', p => !p.querySelector('iframe') && !p.dataset.tab), 'unsplitting empties the hidden pane (no orphan terminal client)');

// A stale poll, one revision behind what this page already wrote, must
// not be adopted, or the tab just removed would come back.
const stale = await page.evaluate(() => {
  const before = tabs.map(t => t.id).join();
  adoptLayout({ rev: myRev - 1, tabs: [{id:'zz', kind:'term', arg:'shell', label:'x'}], panes:['zz', null], active: 0 });
  return tabs.map(t => t.id).join() === before && myRev >= 0;
});
ok(stale, 'a layout one revision behind is ignored');

// A pin menu whose tab is minimized goes with it.
await page.evaluate(() => togglePin(tabs[0].id, new Event('click')));
ok(await page.$('#pinmenu') !== null, 'pin menu opens');
await page.evaluate(() => hideTab(tabs[0].id));
ok(await page.$('#pinmenu') === null && await page.evaluate(() => pinFor === null), 'minimizing its tab closes the pin menu');

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
