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
await page.click(`.tab[data-id="${ids0[1]}"] .lbl`);
ok(await page.evaluate(() => panes[0]) === ids0[1], 'a plain click still switches tabs');
await page.click(`.tab[data-id="${ids0[1]}"] [data-min]`);
ok(await page.$$eval('.tab:not([data-id])', gs => gs.length === 1), 'a minimised tab leaves a fading ghost');
await page.waitForFunction(() => document.querySelectorAll('.tab:not([data-id])').length === 0);
await page.click('#bKeys');
ok(await page.$eval('#keys', el => el.classList.contains('show')), 'strip ⌨ toggles the keys on desktop');
ok(page.errors.length === 0, `zero console errors${page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);
await done(browser);
