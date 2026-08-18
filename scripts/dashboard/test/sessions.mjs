// Sessions card and its relationship to the tab strip: name goes to the tab,
// the button minimises/closes/opens, attached pill and pane glyphs, tooltips,
// macros only on shell tabs, middle-click ends a session, findings tab
// behaviour, and the phone's bottom bar.
import { launch, newPage, ok, done, URL } from './lib.mjs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
await page.waitForFunction(() => document.querySelectorAll('#sessions .row').length >= 2, { timeout: 40000 });
const row = n => page.locator('#sessions .row', { has: page.locator(`[data-go="${n}"]`) });
const btn = n => row(n).locator('button').first();

ok((await btn('shell-9').textContent()).trim() === 'Open', 'minimised session shows Open');
await row('shell-9').locator('[data-go]').click();
await page.waitForFunction(() => tabs.some(t => sessionOf(t.arg) === 'shell-9'));
ok((await btn('shell-9').textContent()).trim() === 'Minimise' && await btn('shell-9').evaluate(b => b.classList.contains('primary')),
   'clicking the name opens the tab; button becomes green Minimise');
ok(await page.evaluate(() => sessionOf(tabOf(panes[0]).arg) === 'shell-9'), '...and goes to it');
ok((await row('shell-9').locator('.pill.att').textContent()).trim() === 'attached', 'attached pill, no glyph while unsplit');
ok(await page.$eval('.tab.on .lbl', el => !el.textContent.includes('◧')), 'no pane glyph on the tab while unsplit');
ok((await row('shell-9').locator('[data-go]').getAttribute('title')) === await page.$eval('.tab.on .lbl', el => el.title),
   'session tooltip equals the tab tooltip');
await btn('shell-9').click();
await page.waitForFunction(() => !tabs.some(t => sessionOf(t.arg) === 'shell-9'));
ok((await btn('shell-9').textContent()).trim() === 'Open', 'Minimise takes the tab away');

await row('shell-9').locator('[data-go]').click();
await page.waitForFunction(() => tabs.some(t => sessionOf(t.arg) === 'shell-9'));
await page.evaluate(() => pinTo(tabs.find(x => sessionOf(x.arg) === 'shell-9').id, 1));
ok((await row('shell-9').locator('.pill.att').textContent()).trim().startsWith('◨'), 'split: pane glyph on the pill');
ok(await page.$$eval('.tab .lbl', els => els.some(e => e.textContent.includes('◧')) && els.some(e => e.textContent.includes('◨'))), 'split: tabs carry glyphs');
await page.evaluate(() => closePane(1));

await row('claude-alpha').locator('[data-go]').click();
await page.waitForFunction(() => tabs.some(t => sessionOf(t.arg) === 'claude-alpha'));
ok((await btn('claude-alpha').textContent()).trim() === 'Close', 'claude session on the strip shows Close');
ok(await page.$eval('#commands [data-m]', b => b.disabled) && await page.$eval('#runner [data-m]', b => b.disabled), 'macros greyed on a Claude tab');
const nd = page.dialogs.length;
await btn('claude-alpha').click();
await page.waitForFunction(() => !document.querySelector('[data-go="claude-alpha"]'), { timeout: 15000 });
ok(page.dialogs.length === nd + 1 && page.dialogs[nd].includes('Claude'), 'Close asked first, then ended the session');

await page.click('#cardFindings .macros button');
await page.waitForSelector('details[data-proj="alpha"]');
await page.click('details[data-proj="alpha"] summary');
ok(await page.$eval('details[data-proj="alpha"]', d => d.getAnimations().length > 0 && d.open), 'findings group animates open');
await page.waitForFunction(() => document.querySelector('details[data-proj="alpha"]').getAnimations().length === 0);
ok(await page.$eval('#commands [data-m]', b => b.disabled), 'macros greyed on the findings tab');
ok(await page.$$eval('.stats .pill', ps => ps.some(p => p.textContent.trim() === '2 hidden')), 'report says how many findings it held back');
await page.click('#cardFindings .macros button');
ok(await page.$eval('details[data-proj="alpha"]', d => d.open), 'reopening the report keeps the expanded group');
// The layout save is debounced; reload only once the server has the tab.
await page.waitForFunction(async () =>
  (await (await fetch('/api/status')).json()).layout.tabs.some(t => t.kind === 'findings'), { timeout: 15000 });
await page.reload();
try {
  await page.waitForFunction(() => document.querySelector('details[data-proj]') !== null, { timeout: 30000 });
  ok(true, 'a findings tab restored from the layout loads itself');
} catch (e) {
  const diag = await page.evaluate(() => ({
    findings: findings && { loading: findings.loading, error: findings.error, reports: findings.reports?.length },
    pane0: document.getElementById('pane0').dataset, tabs: tabs.map(t => t.kind), panes, active,
    doc: document.getElementById('doc0')?.innerHTML.slice(0, 120) }));
  ok(false, 'a findings tab restored from the layout loads itself — ' + JSON.stringify(diag));
}

await page.evaluate(() => focusTab(tabs.find(t => sessionOf(t.arg) === 'shell-9').id));
ok(await page.$eval('#commands [data-m]', b => !b.disabled), 'macros live on a shell tab');

// A back/forward-cache restore (persisted pageshow) reloads the terminal
// iframe so a dead socket reconnects instead of sitting on ttyd's prompt.
await page.waitForSelector('.pane iframe');
await page.evaluate(() => { window.__loads = 0;
  document.querySelector('.pane iframe').addEventListener('load', () => window.__loads++); });
await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })));
await page.waitForFunction(() => window.__loads > 0, { timeout: 10000 });
ok(true, 'a bfcache restore reloads the terminal iframe to reconnect it');
const nd2 = page.dialogs.length;
const tb = await (await page.$('.tab.on')).boundingBox();
await page.mouse.click(tb.x + 20, tb.y + 12, { button: 'middle' });
await page.waitForFunction(() => !document.querySelector('[data-go="shell-9"]'), { timeout: 15000 });
ok(page.dialogs.length === nd2 + 1, 'middle-click asks, then ends the session and its tab');

const phone = await newPage(browser, { viewport: { width: 400, height: 800 } });
await phone.goto(URL);
await phone.waitForFunction(() => document.getElementById('sessions').parentElement.id === 'mpSessions', { timeout: 30000 });
await phone.evaluate(() => setView('terminal'));
await phone.waitForSelector('#bKeys', { state: 'attached' });
ok(await phone.$eval('#mobar', el => getComputedStyle(el).display === 'flex') && await phone.$eval('#bKeys', el => getComputedStyle(el).display === 'none'),
   'phone shows the bottom bar and hides the strip ⌨');
// Measure the terminal before, mid-slide and after: it must hold still
// through the slide (the panel is an overlay then) and shrink once at the end.
const paneH0 = await phone.$eval('#panes', el => el.offsetHeight);
await phone.click('#mSessions');
const mid = await phone.$eval('#sespanel', el => ({
  show: el.classList.contains('show'), anim: el.getAnimations().length > 0,
  overlay: el.classList.contains('sliding') && getComputedStyle(el).position === 'absolute',
  paneH: document.getElementById('panes').offsetHeight }));
ok(mid.show && mid.anim && mid.overlay, 'Sessions opens its panel with a slide, as an overlay');
ok(mid.paneH === paneH0, 'the terminal holds still while the panel slides');
await phone.waitForFunction(() => !document.getElementById('sespanel').classList.contains('sliding'));
ok(await phone.$eval('#panes', el => el.offsetHeight) < paneH0, 'then the terminal snaps to make room');
await phone.click('#mMacros');
// the close is a slide now: the class drops when the tween lands
await phone.waitForFunction(() => !document.getElementById('sespanel').classList.contains('show'));
ok(await phone.$eval('#macpanel', el => el.classList.contains('show')), 'Commands closes it and opens the macros');
ok(await phone.$eval('#commands', el => el.parentElement.id === 'mpCmd' && el.querySelectorAll('[data-m]').length > 0), 'bb list lives in the panel');
ok(await phone.$eval('.tab [data-pin]', el => getComputedStyle(el).display === 'none'), 'pin buttons hidden on a phone');
// Claude on a project with a transcript opens the Resume/New chooser — which
// must be visible on a phone (it once shared the hidden pin menu's class).
await phone.evaluate(() => setView('dash'));
ok(await phone.$eval('.col.side', el => el.getAnimations().length > 0), 'the view slides across the switch');
await phone.click('#projects [data-c="alpha"]');
ok(await phone.$eval('.resumemenu', el => getComputedStyle(el).display !== 'none' && el.querySelectorAll('button').length === 2),
   'phone: Claude on a project with history shows the Resume/New chooser');
await phone.click('.resumemenu [data-n]');
await phone.waitForFunction(() => tabs.some(t => t.arg === 'claude:alpha') && document.body.dataset.view === 'terminal');
ok(true, 'phone: New conversation opens the Claude tab and switches to the terminal');
ok(await phone.$eval('#tabL', el => getComputedStyle(el).display !== 'none') && await phone.$eval('#tabbar', el => getComputedStyle(el).flexWrap === 'nowrap'),
   'strip is one row with scroll arrows');
await phone.close();

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);
await done(browser);
