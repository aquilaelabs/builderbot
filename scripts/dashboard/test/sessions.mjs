// Sessions card and its relationship to the tab strip: name goes to the tab,
// the button minimises/closes/opens, attached pill and pane glyphs, tooltips,
// macros only on shell tabs, middle-click ends a session, findings tab
// behaviour, and the phone's bottom bar: flyout slides and swaps, the strip
// arrows and reveal, and the remembered view.
import { launch, newPage, ok, done, sleep, tmuxNew, tmuxFmt, URL } from './lib.mjs';

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
// PgUp from the keys row is how a finger scrolls: at a prompt it enters copy
// mode a page up; PgDn pages back and copy mode ends itself at the bottom.
await page.evaluate(() => sendKey('pgup'));
await page.waitForFunction(() => true); await sleep(300);
ok(tmuxFmt('shell-9', '#{pane_in_mode}') === '1', 'PgUp at a prompt enters copy mode (scrolls back)');
await page.evaluate(() => sendKey('pgdn')); await sleep(300);
ok(tmuxFmt('shell-9', '#{pane_in_mode}') === '0', 'PgDn back at the bottom leaves copy mode by itself');
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

// The session is gone; a tab still pointing at it takes a Resume's argument
// so the transcript id reaches the terminal, and the frame is rebuilt for it.
await page.evaluate(() => openTab({kind:'term', arg:'claude:alpha', label:'Claude: alpha'}));
await page.evaluate(() => openTab({kind:'term', arg:'claude:alpha:r:abc123', label:'Claude: alpha'}));
ok(await page.evaluate(() => tabs.filter(t => sessionOf(t.arg) === 'claude-alpha').length === 1
     && tabs.find(t => sessionOf(t.arg) === 'claude-alpha').arg === 'claude:alpha:r:abc123'
     && document.querySelector('#pane0 iframe').src.includes(encodeURIComponent('claude:alpha:r:abc123'))),
   'Resume on a dead session\'s tab carries the transcript id into the frame');
await page.evaluate(() => hideTab(tabs.find(t => sessionOf(t.arg) === 'claude-alpha').id));

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
    myRev, serverLayout: state?.layout && { rev: state.layout.rev, kinds: state.layout.tabs.map(t => t.kind) },
    dot: document.getElementById('dot').className,
    doc: document.getElementById('doc0')?.innerHTML.slice(0, 120) }));
  ok(false, 'a findings tab restored from the layout loads itself — ' + JSON.stringify(diag)
     + ' errors=' + JSON.stringify(page.errors));
}

// The rest needs shell-9 on the strip; reopen it if the restore above failed.
await page.evaluate(() => { if (!tabs.some(t => sessionOf(t.arg) === 'shell-9'))
  openTab({kind:"term", arg: argForSession('shell-9'), label:'shell-9'}); });
await page.evaluate(() => focusTab(tabs.find(t => sessionOf(t.arg) === 'shell-9').id));
ok(await page.$eval('#commands [data-m]', b => !b.disabled), 'macros live on a shell tab');
// no tabs at all → greyed too, with a tooltip saying to open a shell
await page.evaluate(() => { const keep = tabs.slice(); keep.forEach(t => dropTab(t.id)); });
ok(await page.$eval('#commands [data-m]', b => b.disabled && /open one/.test(b.title))
   && await page.$eval('#runner [data-m]', b => b.disabled), 'macros greyed with no tab open');
await page.evaluate(() => openTab({kind:"term", arg: argForSession('shell-9'), label:'shell-9'}));
await page.waitForFunction(() => tabs.some(t => sessionOf(t.arg) === 'shell-9'));

// A project with a dot in its name: tmux stores its session as claude-ep_silon,
// and the page must still label it, reopen it and let the server end it.
tmuxNew('claude-ep_silon');
await page.evaluate(() => refresh());
await page.waitForFunction(() => document.querySelector('#sessions [data-go="claude-ep_silon"]'), { timeout: 15000 });
ok((await page.$eval('#sessions [data-go="claude-ep_silon"]', el => el.textContent.trim())) === 'Claude: ep.silon', 'dotted project: session labelled by its project name');
ok(await page.$eval('#projects [data-c="ep.silon"]', b => b.classList.contains('primary')), 'dotted project: Claude button knows the session is running');
await page.click('#sessions [data-go="claude-ep_silon"]');
await page.waitForFunction(() => tabs.some(t => t.arg === 'claude:ep.silon'));
ok(true, 'dotted project: reopening from Sessions maps back to claude:ep.silon');
ok(await page.evaluate(() => sessionOf('claude:ep.silon') === 'claude-ep_silon' && sessionOf('sh:2:ep.silon') === 'shell-ep_silon-2'), 'sessionOf applies the tmux rewrite');
const ndx = page.dialogs.length;
await page.click('#projects [data-x="ep.silon"]');            // exclude: asks, then the server ends the session
await page.waitForFunction(() => !document.querySelector('#sessions [data-go="claude-ep_silon"]'), { timeout: 15000 });
ok(page.dialogs.length === ndx + 1 && !(await page.evaluate(() => tabs.some(t => t.arg === 'claude:ep.silon'))),
   'dotted project: excluding it ends the session and drops its tab');
await page.evaluate(() => setExcluded('ep.silon', false));    // include again (its row is folded away now)
await page.waitForFunction(() => document.querySelector('#projects [data-c="ep.silon"]'), { timeout: 15000 });

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

// Swapping one flyout for another: the outgoing one stays under the incoming
// slide and the terminal changes size once, when the new one lands.
await phone.waitForFunction(() => document.querySelector('.col.term').getAnimations().length === 0);
await phone.click('#mSessions');
await phone.waitForFunction(() => !document.getElementById('sespanel').classList.contains('sliding'));
const hSess = await phone.$eval('#panes', el => el.offsetHeight);
await phone.click('#mMacros');
const swap = await phone.evaluate(() => ({
  oldShown: document.getElementById('sespanel').classList.contains('show') && !document.getElementById('sespanel').classList.contains('sliding'),
  newSliding: document.getElementById('macpanel').classList.contains('sliding'),
  paneH: document.getElementById('panes').offsetHeight }));
ok(swap.oldShown && swap.newSliding && swap.paneH === hSess, 'a flyout swap slides the new one over the old, terminal untouched');
await phone.waitForFunction(() => !document.getElementById('macpanel').classList.contains('sliding'));
ok(await phone.$eval('#sespanel', el => !el.classList.contains('show')) && await phone.$eval('#macpanel', el => el.classList.contains('show')),
   '...and the old one is gone when the new one lands');
// A second tap mid-slide reverses from where the panel is, not from full height.
const hFull = await phone.$eval('#macpanel', el => el.offsetHeight);   // landed, in the flow
await phone.click('#mMacros');                       // closing (slides)
await sleep(90);                                      // ...part-way down
await phone.click('#mMacros');                       // reopen mid-slide
const from = parseFloat(await phone.$eval('#macpanel', el => el.getAnimations()[0]?.effect.getKeyframes()[0].height));
ok(from > 0 && from < hFull, `re-tap mid-slide resumes from the current height (${from} of ${hFull}px)`);
await phone.waitForFunction(() => !document.getElementById('macpanel').classList.contains('sliding'));

// Picking a session from the flyout closes the flyout: it was covering the
// very terminal the tap asked to see. (The desktop half ended both fixture
// sessions above, so make one to pick.)
tmuxNew('shell-7');
await phone.evaluate(() => refresh());
await phone.waitForFunction(() => document.querySelector('#mpSessions [data-go="shell-7"]'), { timeout: 15000 });
await phone.click('#mSessions');
await phone.waitForFunction(() => document.getElementById('sespanel').classList.contains('show') && !document.getElementById('sespanel').classList.contains('sliding'));
await phone.click('#mpSessions [data-go="shell-7"]');
ok(await phone.evaluate(() => !showSessions), 'picking a session closes the Sessions flyout');

// Keys over a document tab: the toggle is disabled and says why.
await phone.evaluate(() => openFindings());
await phone.waitForFunction(() => tabOf(panes[active])?.kind === 'findings');
ok(await phone.$eval('#mKeys', b => b.disabled && /document/.test(b.title)), 'Keys is disabled over a document tab');

// Opening a tab that sits off the end of the strip scrolls it into view, and
// the arrows grey at the ends they cannot go past.
await phone.evaluate(() => { for (let i = 0; i < 6; i++) newShell(''); });
await phone.waitForFunction(() => { const b = document.getElementById('tabbar'); return b.scrollWidth > b.clientWidth + 50; });
await phone.evaluate(() => { document.getElementById('tabbar').scrollTo({left: 0, behavior: 'instant'}); focusTab(tabs[0].id); });
await phone.evaluate(() => focusTab(tabs[tabs.length - 1].id));
await phone.waitForFunction(() => { const b = document.getElementById('tabbar'), t = b.querySelector('.tab.on');
  return t.offsetLeft + t.offsetWidth <= b.scrollLeft + b.clientWidth + 1; }, { timeout: 5000 });
ok(true, 'focusing a tab off the end of the strip scrolls it into view');
await phone.waitForFunction(() => document.getElementById('tabR').disabled, { timeout: 5000 });   // the smooth scroll lands
ok(await phone.$eval('#tabL', b => !b.disabled), 'at the right end › is greyed and ‹ is live');
await phone.evaluate(() => { document.getElementById('tabbar').scrollTo({left: 0, behavior: 'instant'}); });
await phone.waitForFunction(() => document.getElementById('tabL').disabled);
ok(await phone.$eval('#tabR', b => !b.disabled), 'at the left end ‹ is greyed and › is live');

// The view a phone was on comes back after a reload.
await phone.evaluate(() => setView('terminal'));
await phone.reload();
await phone.waitForFunction(() => document.body.dataset.view === 'terminal', { timeout: 20000 });
ok(true, 'a phone reload lands back on the terminal view');
ok(phone.errors.length === 0, `phone: zero console errors${phone.errors.length ? ' — ' + phone.errors.join(' | ') : ''}`);
await phone.close();

// A phone held sideways: a flyout must not push the bottom bar off the
// screen — it gives way, and the terminal keeps a strip.
const land = await newPage(browser, { viewport: { width: 844, height: 390 } });
await land.goto(URL);
await land.waitForFunction(() => state !== null, { timeout: 30000 });
await land.evaluate(() => { setView('terminal'); mobPanel('macros'); });
await land.waitForFunction(() => document.getElementById('macpanel').classList.contains('show') && !document.getElementById('macpanel').classList.contains('sliding'));
const fit = await land.evaluate(() => ({ bar: document.getElementById('mobar').getBoundingClientRect().bottom, panes: document.getElementById('panes').offsetHeight }));
ok(fit.bar <= 390 && fit.panes >= 90, `landscape: the bar stays on screen with a flyout open (bar bottom ${Math.round(fit.bar)}px, terminal ${fit.panes}px)`);
await land.evaluate(() => mobPanel('keys'));
await land.waitForFunction(() => document.getElementById('keys').classList.contains('show') && !document.getElementById('keys').classList.contains('sliding'));
const fit2 = await land.evaluate(() => ({ bar: document.getElementById('mobar').getBoundingClientRect().bottom, panes: document.getElementById('panes').offsetHeight }));
ok(fit2.bar <= 390 && fit2.panes >= 90, `landscape: same with the keys (bar bottom ${Math.round(fit2.bar)}px, terminal ${fit2.panes}px)`);
await land.close();

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);
await done(browser);
