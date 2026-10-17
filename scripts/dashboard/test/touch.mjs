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
// Up, it is the full width of the screen, between the header and the
// bottom bar, which stay (the operator, 16 Oct): measured once its slide
// up out of the line has ended.
ok(await page.evaluate(() => getComputedStyle(document.getElementById('pane1')).animationName === 'dockUp'),
   '...sliding up out of its line as it opens');
await page.waitForFunction(() => !document.getElementById('pane1').getAnimations().some(a => a.playState === 'running'), null, { timeout: 5000 });
const up = await page.evaluate(() => { const r = s => document.querySelector(s).getBoundingClientRect();
  // A shell wears its Keys row under it, between the dock and the bottom bar.
  const d = r('#pane1'), h = r('header'), b = r('#railbar'), m = document.getElementById('mobar');
  const under = m.offsetParent ? m.getBoundingClientRect() : b;
  return { left: Math.round(d.left), right: Math.round(innerWidth - d.right), top: Math.round(d.top - h.bottom), foot: Math.round(under.top - d.bottom), bar: Math.round(b.height) }; });
ok(!up.left && !up.right && !up.top && !up.foot && up.bar > 0, `...and up it spans the screen's width between the header and the bottom bar ${JSON.stringify(up)}`);
// One line where two boxes meet, never two (the operator, 16 Oct): the
// header's over the dock, the bottom bar's under the Keys row.
const meet = await page.evaluate(() => { const w = (s, side) => getComputedStyle(document.querySelector(s))['border' + side + 'Width'];
  return { dockTop: w('#pane1', 'Top'), keysFoot: w('#mobar', 'Bottom') }; });
ok(meet.dockTop === '0px' && meet.keysFoot === '0px', `...with one line at its top and one at its foot ${JSON.stringify(meet)}`);
const cb = await (await page.$('#pane1 [data-dtoggle]')).boundingBox();
await finger(page, cb.x + cb.width / 2, cb.y + cb.height / 2, cb.x + cb.width / 2, cb.y + cb.height / 2, 0);
await page.waitForFunction(() => !dockUp, null, { timeout: 5000 });
ok(await page.evaluate(() => getComputedStyle(document.getElementById('pane0')).display !== 'none'),
   '...and its chevron puts it down to its line under the page');
// Down, the page's box runs to both edges of the screen and meets the header
// and the bottom bar with no gap, so what scrolls goes under them.
const box = await page.evaluate(() => { const r = s => document.querySelector(s).getBoundingClientRect();
  const p = r('#panes'), h = r('header'), b = r('#railbar');
  return { left: Math.round(p.left), right: Math.round(innerWidth - p.right), top: Math.round(p.top - h.bottom), foot: Math.round(b.top - p.bottom) }; });
ok(!box.left && !box.right && !box.top && !box.foot, `...and the page's box is flush with the edges, the header and the bottom bar ${JSON.stringify(box)}`);
ok(await page.evaluate(() => getComputedStyle(document.querySelector('#pane1 > .bar')).borderBottomWidth === '0px'),
   "...and the dock's line shut on the bottom bar draws no second line under itself");
// ...and shut, it slides back into its line, laid over the page, which has
// its own layout at once (the operator, 16 Oct).
await page.evaluate(() => dockToggle(true));
await page.waitForFunction(() => !document.getElementById('pane1').getAnimations().some(a => a.playState === 'running'), null, { timeout: 5000 });
const down = await page.evaluate(() => { dockToggle(false);
  return { cls: document.getElementById('panes').className, anim: getComputedStyle(document.getElementById('pane1')).animationName,
           page: getComputedStyle(document.getElementById('pane0')).display }; });
ok(/dockdown/.test(down.cls) && !/dockup/.test(down.cls) && down.anim === 'dockDown' && down.page !== 'none',
   `...and shutting, it slides down into its line over the page (${JSON.stringify(down)})`);
await page.waitForFunction(() => !document.getElementById('panes').classList.contains('dockdown'), null, { timeout: 5000 });
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

// A dock tab held and dragged takes a new place on the line (the strip's
// gesture, kept when the dock took its place: the operator, 17 Oct), and a
// quick swipe across the line scrolls it rather than picking a tab up. Each
// terminal's tab carries Close beside minimize.
{
  await page.evaluate(() => { location.hash = '#/home'; dockToggle(false); });
  await page.waitForFunction(() => document.querySelectorAll('#pane1 .dtab[data-id]').length >= 2);
  // The line keeps the newest terminal in view; its first two tabs are what
  // the finger goes for, so the line is brought back to its start.
  await page.evaluate(() => { document.querySelector('#pane1 .dockline').scrollLeft = 0; });
  await sleep(300);
  const order = () => page.evaluate(() => [...document.querySelectorAll('#pane1 .dtab[data-id]')].map(e => e.dataset.id));
  const before = await order();
  const box = id => page.$eval(`#pane1 .dtab[data-id="${id}"] .dlbl`, e => { const r = e.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; });
  const a = await box(before[0]), b = await box(before[1]);
  await finger(page, a.x + 10, a.y + a.h / 2, b.x + b.w - 4, b.y + b.h / 2, 0);
  ok(JSON.stringify(await order()) === JSON.stringify(before), 'a quick swipe along the dock line moves no tab');
  await finger(page, a.x + 10, a.y + a.h / 2, b.x + b.w - 4, b.y + b.h / 2, 700);
  const after = await order();
  ok(after[0] === before[1] && after[1] === before[0],
     `a tab held for a moment and dragged past the next takes its place (${before.slice(0, 2)} -> ${after.slice(0, 2)})`);
  ok(JSON.stringify(await page.evaluate(() => tabs.filter(t => t.kind === 'term').map(t => t.id)).then(ids => ids.slice(0, 2))) === JSON.stringify(after.slice(0, 2)),
     '...and the tabs list keeps the new order');
  ok(await page.$$eval('#pane1 .dtab[data-id]', ts => ts.every(t => t.querySelector('[data-min]') && t.querySelector('[data-close]'))),
     "each terminal's tab carries minimize and close");
  // Chat stays anchored at the line's start (the operator, 17 Oct): held,
  // it lifts nothing, and a terminal dragged past it lands after it.
  const first = () => page.evaluate(() => document.querySelector('#pane1 .dockline > .dtab')?.classList.contains('dchat'));
  const chat = await page.$eval('#pane1 .dtab.dchat .dlbl', e => { const r = e.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; });
  const before2 = await order(), t1 = await box(before2[1]), hash0 = await page.evaluate(() => location.hash);
  await finger(page, chat.x + chat.w / 2, chat.y + chat.h / 2, t1.x + t1.w - 4, t1.y + t1.h / 2, 700);
  ok(await first() && JSON.stringify(await order()) === JSON.stringify(before2), 'Chat held and dragged moves nothing: it is anchored');
  // ...and the swipe at the line's start stays the line's (B820): it fell
  // through to the browser's swipe-back and the page went back a page.
  ok(await page.evaluate(() => location.hash) === hash0, `...nor does the swipe take the page back (${hash0})`);
  const t1b = await box(before2[1]);
  await finger(page, t1b.x + 10, t1b.y + t1b.h / 2, chat.x + 2, chat.y + chat.h / 2, 700);
  const after2 = await order();
  ok(await first() && after2[0] === before2[1],
     `...and a terminal dragged past it lands first among the terminals, Chat still at the start (${after2.slice(0, 2)})`);
}

await done(browser);
