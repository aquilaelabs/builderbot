// Desktop mouse: tab drag reorders in place with a slide, the click ending a
// drag does not switch tabs, a plain click does, tab enter/exit animations.
import { launch, newPage, ok, done, URL } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
await page.waitForFunction(() => document.querySelectorAll('#commands [data-m]').length > 0, { timeout: 40000 });
await page.evaluate(() => { newShell(''); newShell(''); });
await page.waitForFunction(() => document.querySelectorAll('.tab[data-id]').length === 3);
const ids0 = await page.$$eval('.tab[data-id]', ts => ts.map(t => t.dataset.id));
const activeBefore = await page.evaluate(() => panes[0]);
const lb = await (await page.$(`.tab[data-id="${ids0[2]}"] .lbl`)).boundingBox();
const first = await (await page.$(`.tab[data-id="${ids0[0]}"]`)).boundingBox();
await page.mouse.move(lb.x + lb.width / 2, lb.y + lb.height / 2); await page.mouse.down();
await page.mouse.move(first.x + 4, first.y + 10, { steps: 10 });
const mid = await page.evaluate(id => ({
  held: document.querySelector(`.tab[data-id="${id}"]`).classList.contains('held'),
  anims: [...document.querySelectorAll('.tab[data-id]')].some(t => t.getAnimations().length > 0) }), ids0[2]);
await page.mouse.up();
ok((await page.$$eval('.tab[data-id]', ts => ts.map(t => t.dataset.id)))[0] === ids0[2], 'mouse drag reorders');
ok(mid.held && mid.anims, 'dragged tab shows held; displaced tabs slide');
ok(await page.evaluate(() => panes[0]) === activeBefore, 'the click ending the drag did not switch tabs');
// The drop saves straight away (debounced 400ms), not on the 15s poll.
await page.waitForFunction(async () =>
  (await (await fetch('/api/status')).json()).layout.tabs[0]?.id === document.querySelector('.tab[data-id]').dataset.id, { timeout: 4000 });
ok(true, 'the new order reaches the server within a second');
await page.click(`.tab[data-id="${ids0[1]}"] .lbl`);
ok(await page.evaluate(() => panes[0]) === ids0[1], 'a plain click still switches tabs');
await page.click(`.tab[data-id="${ids0[1]}"] [data-min]`);
ok(await page.$$eval('.tab:not([data-id])', gs => gs.length === 1), 'a minimised tab leaves a fading ghost');
await page.waitForFunction(() => document.querySelectorAll('.tab:not([data-id])').length === 0);
await page.click('#bKeys');
ok(await page.$eval('#keys', el => el.classList.contains('show')), 'strip ⌨ toggles the keys on desktop');

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
await page.waitForFunction(() => isSplit() && document.querySelectorAll('.pane iframe').length === 2);
await page.evaluate(() => { document.querySelector('#pane1 iframe').focus(); window.dispatchEvent(new Event('blur')); });
ok(await page.evaluate(() => active === 1), 'focus into the right pane\'s terminal activates that pane');
await page.evaluate(() => { document.querySelector('#pane0 iframe').focus(); window.dispatchEvent(new Event('blur')); });
ok(await page.evaluate(() => active === 0), '...and back to the left');
await page.evaluate(() => closePane(1));

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
ok(page.errors.length === 0, `zero console errors${page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);
await done(browser);
