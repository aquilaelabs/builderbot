// Real touch through Chromium's gesture recogniser: a quick swipe on a card
// header or tab label scrolls, a half-second hold then move drags — and never
// the other way round.
import { launch, newPage, ok, done, finger, sleep, URL } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 400, height: 700 }, hasTouch: true, isMobile: true });
await page.goto(URL);
await page.waitForFunction(() => document.querySelectorAll('#projects .row').length > 0, { timeout: 40000 });
const order = () => page.$$eval('.side .card[data-card]', els => els.map(e => e.dataset.card));
const side = () => page.$eval('.col.side', el => el.scrollTop);

const o0 = await order();
let hb = await (await page.$('.card[data-card="projects"] h2')).boundingBox();
await finger(page, hb.x + 40, hb.y + 12, hb.x + 40, hb.y - 250, 0);
ok((await side()) > 20, `quick swipe on a header scrolls the sidebar (${await side()}px)`);
ok(JSON.stringify(await order()) === JSON.stringify(o0), '...and does not drag');

await page.evaluate(() => document.querySelector('.col.side').scrollTop = 0); await sleep(100);
hb = await (await page.$('.card[data-card="projects"] h2')).boundingBox();
const top = await (await page.$('.side .card[data-card]')).boundingBox();
await finger(page, hb.x + 40, hb.y + 12, hb.x + 40, top.y + 2, 650);
ok((await order())[0] === 'projects', `hold then move drags the card (${(await order()).join(',')})`);
ok((await side()) === 0, '...without scrolling');

await page.evaluate(() => { for (let i = 0; i < 4; i++) newShell(''); setView('terminal'); });
await page.waitForFunction(() => { const b = document.getElementById('tabbar'); return b.scrollWidth > b.clientWidth + 50; });
const ids0 = await page.$$eval('.tab[data-id]', ts => ts.map(t => t.dataset.id));
let lb = await (await page.$(`.tab[data-id="${ids0[1]}"] .lbl`)).boundingBox();
await finger(page, lb.x + 20, lb.y + 15, lb.x - 200, lb.y + 15, 0);
ok((await page.$eval('#tabbar', el => el.scrollLeft)) > 30, 'quick swipe on a tab label scrolls the strip');
ok(JSON.stringify(await page.$$eval('.tab[data-id]', ts => ts.map(t => t.dataset.id))) === JSON.stringify(ids0), '...and does not reorder');
await page.evaluate(() => document.getElementById('tabbar').scrollLeft = 0); await sleep(100);
lb = await (await page.$(`.tab[data-id="${ids0[1]}"] .lbl`)).boundingBox();
const first = await (await page.$(`.tab[data-id="${ids0[0]}"]`)).boundingBox();
await finger(page, lb.x + 20, lb.y + 15, first.x + 4, first.y + 15, 650);
ok((await page.$$eval('.tab[data-id]', ts => ts.map(t => t.dataset.id)))[0] === ids0[1], 'hold then move reorders the tabs');
ok((await page.$eval('#tabbar', el => el.scrollLeft)) < 10, '...without scrolling the strip');

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);
await done(browser);
