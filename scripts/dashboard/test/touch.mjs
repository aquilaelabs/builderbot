// Real touch through Chromium's gesture recognizer: the dock's line under a
// finger, and pull to refresh.
import { launch, newPage, ok, done, finger, sleep, URL } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 400, height: 700 }, hasTouch: true, isMobile: true });
await page.goto(URL);
await page.waitForFunction(() => typeof state !== 'undefined' && state && !document.body.classList.contains('booting'), null, { timeout: 40000 });

// On a phone the terminals are the dock's (R218 step 4): a tap on one on
// its line brings the sheet up with it, the whole height above the bottom
// bar; the chevron puts it down; a page opened puts it down too.
await page.evaluate(() => { for (let i = 0; i < 2; i++) newShell(''); dockToggle(false); });
await page.waitForFunction(() => document.querySelectorAll('#pane1 .dtab[data-id]').length >= 2);
await page.waitForTimeout(300);
const want = await page.evaluate(() => tabs.filter(t => t.kind === 'term')[1].id);
const rb = await (await page.$(`#pane1 .dtab[data-id="${want}"] .dlbl`)).boundingBox();
await finger(page, rb.x + 20, rb.y + rb.height / 2, rb.x + 20, rb.y + rb.height / 2, 0);
await page.waitForFunction(w => panes[1] === w && dockUp, want, { timeout: 5000 });
ok(await page.evaluate(() => getComputedStyle(document.getElementById('pane0')).display === 'none'),
   "a tap on a terminal brings the dock's sheet up over the page");
const cb = await (await page.$('#pane1 [data-dtoggle]')).boundingBox();
await finger(page, cb.x + cb.width / 2, cb.y + cb.height / 2, cb.x + cb.width / 2, cb.y + cb.height / 2, 0);
await page.waitForFunction(() => !dockUp, null, { timeout: 5000 });
ok(await page.evaluate(() => getComputedStyle(document.getElementById('pane0')).display !== 'none'),
   '...and its chevron puts it down to its line under the page');
await page.evaluate(() => { dockToggle(true); openJobsTab(); });
await page.waitForFunction(() => !dockUp, null, { timeout: 5000 });
ok(true, '...and a page opened on a phone puts the sheet down');

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);
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
