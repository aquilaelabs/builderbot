// Real touch through Chromium's gesture recognizer: a quick swipe on a card
// header or tab label scrolls, a half-second hold then move drags, and never
// the other way round.
import { launch, newPage, ok, done, finger, sleep, URL } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 400, height: 700 }, hasTouch: true, isMobile: true });
await page.goto(URL);
await page.waitForFunction(() => document.querySelectorAll('#projects .row').length > 0, { timeout: 40000 });
const order = () => page.$$eval('.side .card[data-card]', els => els.map(e => e.dataset.card));
const side = () => page.$eval('.col.side', el => el.scrollTop);

// A swipe can only be told from a drag on a sidebar that SCROLLS, and how
// tall this one is was an accident of the fixture until it stopped being tall
// enough: the projects each carried an issue line ("no environment block")
// that went with the block itself (R63 step 3), and this assertion silently
// became a measurement of nothing. So the overflow is made here and asserted,
// rather than hoped for.
await page.evaluate(() => {
  const spacer = document.createElement('div');
  spacer.id = 'touch-spacer';
  spacer.style.minHeight = '900px';
  spacer.style.flex = '0 0 900px';
  document.querySelector('.col.side').append(spacer);
});
ok(await page.$eval('.col.side', el => el.scrollHeight > el.clientHeight + 200),
   'the sidebar is taller than its column, which is what makes a swipe a scroll');

const o0 = await order();
let hb = await (await page.$('.card[data-card="projects"] h2')).boundingBox();
await finger(page, hb.x + 40, hb.y + 12, hb.x + 40, hb.y - 250, 0);
ok((await side()) > 20, `quick swipe on a header scrolls the sidebar (${await side()}px)`);
ok(JSON.stringify(await order()) === JSON.stringify(o0), '...and does not drag');

await page.evaluate(() => {
  document.getElementById('touch-spacer')?.remove();
  document.querySelector('.col.side').scrollTop = 0;
}); await sleep(100);
hb = await (await page.$('.card[data-card="projects"] h2')).boundingBox();
const top = await (await page.$('.side .card[data-card]')).boundingBox();
await finger(page, hb.x + 40, hb.y + 12, hb.x + 40, top.y + 2, 650);
ok((await order())[0] === 'projects', `hold then move drags the card (${(await order()).join(',')})`);
ok((await side()) === 0, '...without scrolling');

// On a phone the strip is a picker (R119 step 5): the tab on show and how
// many are open, and a list of them under it. Driven by real taps.
await page.evaluate(() => { for (let i = 0; i < 4; i++) newShell(''); setView('terminal'); });
await page.waitForFunction(() => document.querySelector('.col.term').getAnimations().length === 0);
ok(await page.evaluate(() => getComputedStyle(document.getElementById('tabbar')).display === 'none'
     && getComputedStyle(document.getElementById('tabL')).display === 'none'
     && getComputedStyle(document.getElementById('tabPick')).display !== 'none'),
   'on a phone the strip and its arrows give way to the tab picker');
const open = await page.evaluate(() => tabs.length);
ok(new RegExp(`${open}`).test(await page.$eval('#tabPick .pill', e => e.textContent)),
   `...which names the tab on show and counts the ${open} open`);
let pb = await (await page.$('#tabPick')).boundingBox();
await finger(page, pb.x + 30, pb.y + pb.height / 2, pb.x + 30, pb.y + pb.height / 2, 0);
await page.waitForFunction(() => !document.getElementById('tabPickList').hidden, null, { timeout: 5000 });
ok(await page.$$eval('#tabPickList [data-pshow]', r => r.length) === open,
   'a tap lists every tab, each a row');
const want = await page.evaluate(() => tabs[1].id);
const rb = await (await page.$(`#tabPickList [data-pshow="${want}"]`)).boundingBox();
await finger(page, rb.x + 20, rb.y + rb.height / 2, rb.x + 20, rb.y + rb.height / 2, 0);
await page.waitForFunction(w => panes[active] === w && document.getElementById('tabPickList').hidden, want, { timeout: 5000 });
ok(true, '...and a tapped row brings its tab forward and closes the list');
await finger(page, pb.x + 30, pb.y + pb.height / 2, pb.x + 30, pb.y + pb.height / 2, 0);
await page.waitForFunction(() => !document.getElementById('tabPickList').hidden, null, { timeout: 5000 });
await finger(page, 200, 650, 200, 650, 0);
await page.waitForFunction(() => document.getElementById('tabPickList').hidden, null, { timeout: 5000 });
ok(true, '...and a tap anywhere else closes it');

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);
// A phone comes back to the side it left, but not across a container
// restart. Whatever was on the terminal side ended with the container, so
// landing there shows tabs for sessions that are gone. The boot the side was
// chosen under is stored beside it, and a different one sends it back to the
// Dashboard once.
await page.evaluate(() => setView('terminal'));
ok(await page.evaluate(() => document.body.dataset.view) === 'terminal',
   'the terminal side can be chosen');
ok(await page.evaluate(() => localStorage.getItem('bb.view.boot')) !== null,
   '...and is remembered against the run of the container it was chosen under');
// An absent stamp is a browser that has never been here, not a restart.
await page.evaluate(() => localStorage.removeItem('bb.view.boot'));
await page.evaluate(() => viewAfterRestart());
ok(await page.evaluate(() => document.body.dataset.view) === 'terminal',
   '...and no stamp at all leaves the side alone, rather than reading as a restart');
// A reload of the SAME boot keeps it.
await page.evaluate(() => viewAfterRestart());
ok(await page.evaluate(() => document.body.dataset.view) === 'terminal',
   '...which a plain reload leaves alone');
// A different boot does not.
await page.evaluate(() => { localStorage.setItem('bb.view.boot', 'someolderboot'); });
await page.evaluate(() => viewAfterRestart());
ok(await page.evaluate(() => document.body.dataset.view) === 'dash',
   '...while a container that came back since puts it on the Dashboard');

// ---- pull to refresh (page-pull.js) ---------------------------------------
// The page scrolls inside its panes, so a phone browser's own pull never
// fires; the page's does: a drag down from the top re-reads the dashboard,
// and the header has no ↻ beside it any more (the operator, 2 Oct).
{
  ok(!(await page.$('header button[aria-label="refresh now"], #hdr button[aria-label="refresh now"]')),
     'the header carries no refresh button');
  // Counted at the pull itself: the poll calls refresh() on its own clock.
  const before = await page.evaluate(() => { window.__pulls = 0; const r = window.pullRefresh;
    window.pullRefresh = (...a) => { window.__pulls++; return r(...a); }; return true; });
  // From the top of a document tab in front (a terminal is the terminal's
  // own to scroll), where a list is read from.
  await page.evaluate(() => openNodesTab());
  await page.waitForSelector('.doctab.nodestab .doclist', { timeout: 15000 });
  await sleep(400);
  const top = await page.evaluate(() => { const r = document.querySelector('.doctab.nodestab .doclist')?.getBoundingClientRect();
    return r ? Math.round(r.top + 20) : 200; });
  await finger(page, 200, top, 200, top + 140);
  const pulled = await page.evaluate(() => window.__pulls);
  const where = await page.evaluate(y => { const el = document.elementFromPoint(200, y); const sc = pullScroller(el);
    return `${el?.tagName}.${el?.className} in ${sc ? sc.className + ' at ' + sc.scrollTop : 'no scroller'}`; }, top);
  ok(before && pulled >= 1, `a drag down from the top refreshes (${pulled}; ${where})`);
  await page.evaluate(() => { window.__pulls = 0; });
  await finger(page, 200, top, 200, top + 30);
  ok(await page.evaluate(() => window.__pulls) === 0, '...and a short one does not');
}

await done(browser);
