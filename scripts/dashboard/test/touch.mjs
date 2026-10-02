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

await page.evaluate(() => { for (let i = 0; i < 4; i++) newShell(''); setView('terminal'); });
await page.waitForFunction(() => { const b = document.getElementById('tabbar'); return b.scrollWidth > b.clientWidth + 50; });
// let the view-switch slide land before measuring where anything is
await page.waitForFunction(() => document.querySelector('.col.term').getAnimations().length === 0);
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

// The tab strip's paging arrows do not ghost at the end they cannot go past.
// Two half-there arrows on a strip too short to page read as broken rather than
// as a limit. They stay `disabled` (pressing one still does nothing and a
// screen reader is still told), so this asserts the LOOK and the behavior
// separately, which is exactly the pair a previous attempt got wrong: it
// dropped an `opacity:.35` from the .tscroll rule and handed them straight back
// to `button:disabled{opacity:.5}`, leaving them just as faded.
await page.evaluate(() => { const b = [...document.querySelectorAll('button')]
  .find(x => /^Terminal$/.test(x.textContent.trim())); b && b.click(); });
await sleep(600);
const arrows = await page.evaluate(() => ['#tabL', '#tabR'].map(sel => {
  const e = document.querySelector(sel);
  return e ? { sel, disabled: e.disabled, opacity: getComputedStyle(e).opacity } : null;
}).filter(Boolean));
// The outline is the STRIP's, not the scroller's. A mask fades everything it
// applies to, borders included, so masking the element that carried them broke
// the line as it reached each arrow. Drawn by an ancestor that is not masked,
// it runs the full width and only what scrolls fades.
const frame = await page.evaluate(() => {
  const strip = getComputedStyle(document.querySelector('.tabstrip'));
  const bar = getComputedStyle(document.querySelector('#tabbar'));
  return { strip: strip.borderTopWidth, bar: bar.borderTopWidth,
           arrow: getComputedStyle(document.querySelector('#tabL')).borderTopWidth };
});
ok(frame.strip !== '0px' && frame.bar === '0px' && frame.arrow === '0px',
   `the tab strip's outline is on the strip, so a fade cannot cut it (${
     JSON.stringify(frame)})`);
ok(arrows.length === 2 && arrows.every(a => a.opacity === '1'),
   `the tab arrows are full strength whether or not they can page (${
     arrows.map(a => a.sel + ' ' + a.opacity).join(', ')})`);
ok(arrows.some(a => a.disabled),
   '...and still disabled at an end, so a dead press stays dead');

// A tab cut off by the edge fades out rather than being sliced, and only on
// the edge doing the cutting: hard against one end, that side is showing a
// whole tab and fading a complete tab is worse than the seam was.
await page.click('#tabbar .newtab').catch(() => {});
await sleep(500);
await page.click('#tabbar .newtab').catch(() => {});
await sleep(700);
const edge = async pos => page.$eval('#tabbar', (e, p) => {
  e.scrollLeft = p === 'L' ? 0 : p === 'R' ? e.scrollWidth : (e.scrollWidth - e.clientWidth) / 2;
  e.dispatchEvent(new Event('scroll'));
  return { over: e.scrollWidth > e.clientWidth + 1,
           l: e.classList.contains('fadeL'), r: e.classList.contains('fadeR') };
}, pos);
await edge('M'); await sleep(300);
const mid = await edge('M');
if (!mid.over){
  ok(true, 'the strip does not overflow at this width, so nothing to fade');
} else {
  ok(mid.l && mid.r, 'mid-scroll both edges of the tab strip fade');
  await edge('L'); await sleep(300);
  const left = await edge('L');
  ok(!left.l && left.r,
     '...hard left, only the right fades: the first tab is whole and stays crisp');
  await edge('R'); await sleep(300);
  const right = await edge('R');
  ok(right.l && !right.r, '...and hard right, only the left');
}

// ---- pull to refresh (page-pull.js) ---------------------------------------
// The page scrolls inside its panes, so a phone browser's own pull never
// fires; the page's does: a drag down from the top re-reads the dashboard,
// and the header has no ↻ beside it any more (the operator, 2 Oct).
{
  ok(!(await page.$('header button[title="refresh now"], #hdr button[title="refresh now"]')),
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
