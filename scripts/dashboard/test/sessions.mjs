// Sessions card and its relationship to the tab strip: name goes to the tab,
// the button minimizes/closes/opens, attached pill and pane glyphs, tooltips,
// macros only on shell tabs, middle-click ends a session, findings tab
// behavior, and the phone's bottom bar: flyout slides and swaps, the strip
// arrows and reveal, and the remembered view.
import { launch, newPage, ok, done, ready, sleep, tmuxNew, tmuxKill, tmuxFmt, layoutSettled, refreshUntil, URL, DIR, closePage, unfold, member } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
// Sessions hangs off the terminal now, at every width, so a desktop page has
// to open the panel before there is a list to click: the sidebar card it
// used to live in is gone.
await page.waitForSelector('#mSessions');
await page.click('#mSessions');
await page.waitForFunction(() => document.querySelectorAll('#sessions .row').length >= 2, { timeout: 40000 });
// On a desktop the flyout is an OVERLAY: the terminal keeps its height, and
// with it its fit and its scrollback; a resize costs a terminal a refit and a
// reflow of everything on screen, which is a lot to charge for looking at a
// list. The phone pushes instead, because there is not the screen to cover one
// thing with another.
//
// Measured on a CLOSE-then-open, not on the first open, and after the strip has
// stopped moving: the first render that puts a tab pill on the strip grows it
// by a row, and measuring across that reads 30px of tab strip as if the panel
// had taken it. Both heights in one task, for the reason at the phone's own
// version of this below.
await page.click('#mSessions');
await page.waitForFunction(() => !document.getElementById('sespanel').classList.contains('show'));
await page.waitForFunction(
  () => !document.getAnimations().some(a => a.playState === 'running'), { timeout: 10000 });
const deskOpen = await page.evaluate(() => {
  const panes = document.getElementById('panes');
  const before = panes.offsetHeight;
  document.getElementById('mSessions').click();
  const el = document.getElementById('sespanel');
  return { before, after: panes.offsetHeight, anim: el.getAnimations().length > 0,
    over: el.classList.contains('over') && getComputedStyle(el).position === 'absolute' };
});
ok(deskOpen.over && deskOpen.anim, 'a desktop flyout opens as an animated overlay');
ok(deskOpen.after === deskOpen.before,
   `...and the terminal is not pushed up for it (${deskOpen.after} vs ${deskOpen.before}px)`);
const row = n => page.locator('#sessions .row', { has: page.locator(`[data-go="${n}"]`) });
const btn = n => row(n).locator('button').first();

ok((await btn('shell-9').textContent()).trim() === 'Open', 'minimized session shows Open');
await row('shell-9').locator('[data-go]').click();
await page.waitForFunction(() => tabs.some(t => sessionOf(t.arg) === 'shell-9'));
ok((await btn('shell-9').textContent()).trim() === 'Minimize' && await btn('shell-9').evaluate(b => b.classList.contains('primary')),
   'clicking the name opens the tab; button becomes green Minimize');
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
ok((await btn('shell-9').textContent()).trim() === 'Open', 'Minimize takes the tab away');

await row('shell-9').locator('[data-go]').click();
await page.waitForFunction(() => tabs.some(t => sessionOf(t.arg) === 'shell-9'));
await page.evaluate(() => pinTo(tabs.find(x => sessionOf(x.arg) === 'shell-9').id, 1));
ok((await row('shell-9').locator('.pill.att').textContent()).trim().startsWith('◨'), 'split: pane glyph on the pill');
ok(await page.$$eval('.tab .lbl', els => els.some(e => e.textContent.includes('◧')) && els.some(e => e.textContent.includes('◨'))), 'split: tabs carry glyphs');
await page.evaluate(() => closePane(1));

// ---- the git/GitHub card ghosts against the shell's directory ----------
// shell-9 lives in /tmp; alpha has a GitHub remote; ep.silon's remote is
// GitLab, so between the three shells every ghosting state appears, and the
// dotted name proves the cwd-to-project mapping survives tmux's rename.
tmuxNew('shell-alpha', `${DIR}/ws/alpha`);
tmuxNew('shell-ep_silon', `${DIR}/ws/ep.silon`);
await page.evaluate(() => refresh());
await page.waitForFunction(() => state.sessions.some(s => s.name === 'shell-ep_silon'));
const gitBtn = () => page.$eval('#git [data-m="git-status"]', b => ({ dis: b.disabled, tip: b.title }));
const ghBtn  = () => page.$eval('#git [data-m="gh-prs"]', b => ({ dis: b.disabled, tip: b.title }));
await row('shell-9').locator('[data-go]').click();
await page.waitForFunction(() => sessionOf(tabOf(panes[active])?.arg || '') === 'shell-9');
ok(!(await page.$eval('#linux [data-m]', b => b.disabled)), 'linux commands live on any shell');
let g = await gitBtn(), h = await ghBtn();
ok(g.dis && g.tip.includes('not a git repository'), 'outside a repo the git commands ghost, saying why');
ok(h.dis, '...and the gh commands with them');
await row('shell-alpha').locator('[data-go]').click();
await page.waitForFunction(() => sessionOf(tabOf(panes[active])?.arg || '') === 'shell-alpha');
g = await gitBtn(); h = await ghBtn();
ok(!g.dis && !h.dis, 'in a GitHub-remoted repo, git and gh commands are both live');
await row('shell-ep_silon').locator('[data-go]').click();
await page.waitForFunction(() => sessionOf(tabOf(panes[active])?.arg || '') === 'shell-ep_silon');
g = await gitBtn(); h = await ghBtn();
ok(!g.dis, 'a repo with a non-GitHub remote keeps its git commands');
ok(h.dis && h.tip.includes('no GitHub remote'), '...but the gh ones ghost, saying why');
// Tidy the strip for the sections below: these two tabs were this block's.
await page.evaluate(() => { for (const s of ['shell-alpha', 'shell-ep_silon']){
  const t = tabs.find(x => sessionOf(x.arg) === s); if (t) hideTab(t.id); } });

await row('claude-alpha').locator('[data-go]').click();
await page.waitForFunction(() => tabs.some(t => sessionOf(t.arg) === 'claude-alpha'));
ok((await btn('claude-alpha').textContent()).trim() === 'Close', 'claude session on the strip shows Close');
ok(await page.$eval('#commands [data-m]', b => b.disabled), 'macros grayed on a Claude tab');
const nd = page.dialogs.length;
await btn('claude-alpha').click();
await page.waitForFunction(() => !document.querySelector('[data-go="claude-alpha"]'), { timeout: 15000 });
ok(page.dialogs.length === nd + 1 && page.dialogs[nd].includes('Claude'), 'Close asked first, then ended the session');

// The session is gone; a tab still pointing at it takes a Resume's argument
// so the transcript id reaches the terminal, and the frame is rebuilt for it.
// Opened and read in ONE task, which is the whole trick here. This tab points
// at a session that was just ended, and a tab whose session was seen alive and
// is now gone is REAPED by the next poll, correctly and by design. On a quiet
// box the read won that race; under load the poll won it, and the failure read
// as "the page lost the tab" rather than "the page did exactly what it says it
// does". Nothing between the two openTab calls and the measurement means
// nothing can run between them.
const resumed = await page.evaluate(() => {
  openTab({kind: 'term', arg: 'claude:alpha', label: 'Claude: alpha'});
  openTab({kind: 'term', arg: 'claude:alpha:r:abc123', label: 'Claude: alpha'});
  return {
    tabs: tabs.filter(t => sessionOf(t.arg) === 'claude-alpha').length,
    arg: tabs.find(t => sessionOf(t.arg) === 'claude-alpha')?.arg,
    src: document.querySelector('#pane0 .slot.on iframe')?.src,
    slots: [...document.querySelectorAll('#pane0 .slot')].map(c => c.dataset.key),
  };
});
ok(resumed.tabs === 1 && resumed.arg === 'claude:alpha:r:abc123'
     && (resumed.src || "").includes(encodeURIComponent('claude:alpha:r:abc123'))
     // ...and the frame the old tab had is gone with it. A pane keeps
     // terminals alive behind the visible one; one whose tab has closed is
     // still an attached client, on a session nothing is showing.
     && !resumed.slots.some(k => k.includes('|claude:alpha') && !k.includes(':r:')),
   `Resume on a dead session's tab carries the transcript id into the frame (${JSON.stringify(resumed)})`);
await page.evaluate(() => { const t = tabs.find(x => sessionOf(x.arg) === 'claude-alpha');
                            if (t) hideTab(t.id); });

// The findings card is gone (the Analysis tab in Tools is the cross-project
// browser now), so the notebook's view opens by name, which is what the tab's
// rows and bb's messages point at.
await page.evaluate(() => openNotebook('alpha', 'analysis'));
await page.waitForSelector('.pane .nb [data-view="analysis"]:not([hidden]) .rule',
                           { timeout: 20000 });
ok(true, 'a notebook opens on its Analysis view when asked by name');
ok(await page.$eval('#commands [data-m]', b => b.disabled), 'macros grayed on a notebook tab');
ok(await page.$$eval('.pane .nb .rule .rid .pill', ps => ps.length > 0),
   '...with the findings for that project alone, worst level first');

// The same filters the Analysis tab carries, project-fixed: one slice of
// narrowing shared by both surfaces, so learning one is learning the other.
const anaRules = await page.$$eval('.pane .nb #anaList .rule', rs => rs.length);
await page.selectOption('.pane .nb #anaList .fxLevel', 'error');
await page.waitForFunction(n =>
  document.querySelectorAll('.pane .nb #anaList .rule').length <= n,
  anaRules, { timeout: 10000 });
ok(await page.$$eval('.pane .nb #anaList .rule .pill',
     ps => ps.length && ps.every(p => p.textContent.trim().startsWith('error'))),
   'the notebook view narrows by level with the same control the tab has');
await page.fill('.pane .nb #anaList .fxFind', 'no-such-rule-anywhere');
await page.waitForFunction(() => /nothing matches the filters/.test(
  document.querySelector('.pane .nb #anaList')?.textContent || ''),
  null, { timeout: 10000 });
ok(true, '...and by search, saying plainly when the filters leave nothing');
await page.selectOption('.pane .nb #anaList .fxLevel', '');
await page.fill('.pane .nb #anaList .fxFind', '');
await page.waitForFunction(n =>
  document.querySelectorAll('.pane .nb #anaList .rule').length === n,
  anaRules, { timeout: 10000 });
// The view's bands line up with every other view's. The filter bar was a
// .field inside a .field and inset twice; the rules carried the sidebar's
// tighter 11px, so this one view had three left edges where the roadmap
// beside it had one.
{
  const xs = await page.evaluate(() => {
    const x = sel => { const e = document.querySelector(sel);
      return e ? Math.round(e.getBoundingClientRect().x
                            + parseFloat(getComputedStyle(e).paddingLeft)) : null; };
    return { head: x('.pane .nb .nbview:not([hidden]) .nbhead'),
             bar: x('.pane .nb #anaList .fxbar'),
             rule: x('.pane .nb #anaList .rule') };
  });
  ok(new Set(Object.values(xs)).size === 1 && !Object.values(xs).includes(null),
     'the notebook\'s Analysis bands share one left edge: ' + JSON.stringify(xs));
}
ok(await page.$$eval('.pane .nb .field .field', es => es.length === 0),
   '...and nothing in the notebook is inset twice by a field inside a field');
// The fourth log. Nothing writes it (it is the difference between one scan
// and the last), but it opens and filters like the other three, which is the
// point of it being here at all.
await page.click('.pane .nb #anaLog');
await page.waitForFunction(() => !document.getElementById('anaHist').hidden,
                           null, { timeout: 15000 });
ok(!await page.$eval('.pane .nb #anaList', el => el.hidden)
   && await page.$eval('.pane .nb #anaHistBar', el => !el.hidden)
   && await page.$eval('.pane .nb #anaHist', el => el.closest('.sheetslot') !== null),
   'Analysis has a History, opening over the findings the way the other three do');
ok((await page.$eval('.pane .nb #anaHistBar input', i => i.placeholder)).includes('search')
   && await page.$$eval('.pane .nb #anaHistBar select', ss => ss.length === 2),
   '...with the same search box and the same two filters');
// At "all time" with nothing to show, this log says why it is empty rather
// than reusing the shared line about a notebook nobody has written in; no
// one writes this one at all.
await page.selectOption('.pane .nb #anaHistBar .hwhen', '0');
await page.waitForFunction(() => /second scan/.test(
  document.getElementById('anaHist').textContent), null, { timeout: 15000 });
ok(true, '...and says why it is empty rather than looking broken');
// Closed by the sheet's own Close, not by the button that opened it: the
// sheet covers the whole page now, so that button is behind the overlay,
// which is the point of an overlay, and was the bug. It used to stop at the
// notebook's text column and leave the header reachable through the gap.
await page.evaluate(() => document.querySelector('.nbsheet:not([hidden]) .foot button')
                            ?.click());
await page.waitForFunction(() => !document.querySelector('.nbsheet:not([hidden])'),
                           { timeout: 8000 });
await page.waitForFunction(() => document.getElementById('anaHist').hidden,
                           null, { timeout: 15000 });
// A notebook tab survives the reload and loads itself: the restore story
// the findings tab used to carry, now the notebook's.
await layoutSettled(l => l.tabs.some(t => t.kind === 'notebook'));
await page.reload();
await page.waitForFunction(() => document.querySelector('.pane .nb') !== null,
                           { timeout: 30000 });
ok(true, 'a notebook tab restored from the layout loads itself');
// A reload closes the flyout, the way it always has on a phone: the panel
// is a toggle, not a card that is simply there. Open it again for the rest.
await page.click('#mSessions');
await page.evaluate(() => hideTab(tabs.find(t => t.kind === 'notebook').id));

// The rest needs shell-9 on the strip; reopen it if the restore above failed.
await page.evaluate(() => { if (!tabs.some(t => sessionOf(t.arg) === 'shell-9'))
  openTab({kind:"term", arg: argForSession('shell-9'), label:'shell-9'}); });
await page.evaluate(() => focusTab(tabs.find(t => sessionOf(t.arg) === 'shell-9').id));
ok(await page.$eval('#commands [data-m]', b => !b.disabled), 'macros live on a shell tab');
// no tabs at all → grayed too, with a tooltip saying to open a shell
await page.evaluate(() => { const keep = tabs.slice(); keep.forEach(t => dropTab(t.id)); });
ok(await page.$eval('#commands [data-m]', b => b.disabled && /open one/.test(b.title)),
   'macros grayed with no tab open');
await page.evaluate(() => openTab({kind:"term", arg: argForSession('shell-9'), label:'shell-9'}));
await page.waitForFunction(() => tabs.some(t => sessionOf(t.arg) === 'shell-9'));

// A project with a dot in its name: tmux stores its session as claude-ep_silon,
// and the page must still label it, reopen it and let the server end it.
tmuxNew('claude-ep_silon');
await page.evaluate(() => refresh());
await page.waitForFunction(() => document.querySelector('#sessions [data-go="claude-ep_silon"]'), { timeout: 15000 });
ok((await page.$eval('#sessions [data-go="claude-ep_silon"]', el => el.textContent.trim())) === 'Claude: ep.silon', 'dotted project: session labeled by its project name');
// `on`, not `primary`: the row's controls are icons now, and a live one is
// lit by color rather than by being a filled button.
ok(await page.$eval('#projects [data-c="ep.silon"]', b => b.classList.contains('on')), 'dotted project: Claude button knows the session is running');
await page.click('#sessions [data-go="claude-ep_silon"]');
await page.waitForFunction(() => tabs.some(t => t.arg === 'claude:ep.silon'));
ok(true, 'dotted project: reopening from Sessions maps back to claude:ep.silon');
ok(await page.evaluate(() => sessionOf('claude:ep.silon') === 'claude-ep_silon' && sessionOf('sh:2:ep.silon') === 'shell-ep_silon-2'), 'sessionOf applies the tmux rewrite');
// ...and another account's session on the same project, which the lock
// ends too: every Claude session there goes, whoever's and wherever it
// runs, and the question names who is running one (the operator, 29 Sep).
await page.evaluate(async () => (await fetch('/api/users', { method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ action: 'add', name: 'w.lock', password: 'w.lock-pass-1', role: 'user' }) })).json());
await member('w.lock');
const lockUid = JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users['w.lock'].uid;
// (The Sessions card lists this account's own sessions, so the other
// account's is checked in tmux itself.)
tmuxNew(`${lockUid}~claude-ep_silon`);
await page.evaluate(() => refresh());
const ndx = page.dialogs.length;
await unfold(page, 'ep.silon');
await page.click('#projects [data-k="ep.silon"]');            // lock: asks, then the server ends the sessions
await page.waitForFunction(() => !document.querySelector('#sessions [data-go="claude-ep_silon"]'), { timeout: 15000 });
const gone = n => { for (let i = 0; i < 20; i++){ try { execFileSync('tmux', ['has-session', '-t', '=' + n], { stdio: 'ignore' }); } catch { return true; } execFileSync('sleep', ['0.25']); } return false; };
// Either wording is the design's: the other account's session is named when
// the poll has seen it by the click, and that is timing (B388).
ok(page.dialogs.length === ndx + 1 && /Your Claude session here ends now|2 Claude sessions here end now: yours, w\.lock\./.test(page.dialogs[ndx]) && /Lock ep\.silon\?/.test(page.dialogs[ndx])
   && !(await page.evaluate(() => tabs.some(t => t.arg === 'claude:ep.silon'))) && gone('claude-ep_silon') && gone(`${lockUid}~claude-ep_silon`),
   `dotted project: locking it asks, naming the sessions running there, ends every one of them and drops its tab (${(page.dialogs[ndx] || '').split('\n')[2]})`);
await page.evaluate(() => setLocked('ep.silon', false));      // and unlock it again
await page.waitForFunction(() => document.querySelector('#projects [data-c="ep.silon"]'), { timeout: 15000 });

// A back/forward-cache restore (persisted pageshow) reloads the terminal
// iframe so a dead socket reconnects instead of sitting on ttyd's prompt.
// .slot.on: a pane keeps the terminals behind the visible one loaded, so
// there is more than one frame in it and only one is on screen.
await page.waitForSelector('.slot.on iframe');
await page.evaluate(() => { window.__loads = 0;
  document.querySelector('.slot.on iframe').addEventListener('load', () => window.__loads++); });
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
await phone.waitForFunction(() => document.getElementById('sessions').parentElement.id === 'sespanel', { timeout: 30000 });
await phone.evaluate(() => setView('terminal'));
await phone.waitForSelector('#mKeys', { state: 'visible' });
ok(await phone.$eval('#mobar', el => getComputedStyle(el).display === 'flex') && !await phone.$('#bKeys'),
   'the phone bar carries the keys, and the strip has no ⌨ anywhere to hide');
// A truncated version string answers nothing, so where it will not fit the
// About control carries the word instead, and exactly one of the two, never
// both: showing the label on a desktop as well stacked it under the version
// and doubled the button's height.
ok(await phone.$eval('#bAbout .alab', el => getComputedStyle(el).display !== 'none')
   && await phone.$eval('#bAbout #build', el => getComputedStyle(el).display === 'none'),
   'a narrow header shows About as the word, not as a version it would have to cut');
ok(await page.$eval('#bAbout .alab', el => getComputedStyle(el).display === 'none')
   && await page.$eval('#bAbout #build', el => getComputedStyle(el).display !== 'none'),
   '...and a wide one shows the version, with no second label under it');
// Measure the terminal before, mid-slide and after: it must hold still
// through the slide (the panel is an overlay then) and shrink once at the end.
//
// Both heights are read in ONE evaluate, either side of a synchronous click,
// and that is the whole point rather than a shortcut. The button's handler is
// mobPanel -> render -> drawKeys -> slidePanel with nothing awaited, so when
// .click() returns the panel is already absolute and its animation started.
// No frame, no poll and no other animation can land between the two reads.
// Sampling the baseline in an earlier round trip is what CI kept failing on,
// four runs running, while an idle box passed: the panel assertion above it
// passed in the same breath, so the panel was still absolute and cannot have
// been what moved the terminal; the baseline was simply stale. The likeliest
// mover is setView('terminal') just above, a 220ms slide that holds overflow-x
// on <main> for its duration, and it was. One task keeps anything from
// landing BETWEEN the two reads and does nothing about a baseline taken while
// that slide is still running; what had been holding THAT off was the round
// trips of the assertion above, which is not a thing to depend on and stopped
// being true the moment that assertion needed one fewer of them. So wait for
// the page to stop moving, which is what the baseline actually wants.
await phone.waitForFunction(
  () => !document.getAnimations().some(a => a.playState === 'running'),
  { timeout: 10000 });
const mid = await phone.evaluate(() => {
  const panes = document.getElementById('panes');
  const before = panes.offsetHeight;
  document.getElementById('mSessions').click();
  const el = document.getElementById('sespanel');
  return { before, after: panes.offsetHeight,
    show: el.classList.contains('show'), anim: el.getAnimations().length > 0,
    overlay: el.classList.contains('sliding') && getComputedStyle(el).position === 'absolute' };
});
ok(mid.show && mid.anim && mid.overlay, 'Sessions opens its panel with a slide, as an overlay');
ok(mid.after === mid.before,
   `the terminal holds still while the panel slides (${mid.after} vs ${mid.before}px)`);
const paneH0 = mid.before;
await phone.waitForFunction(() => !document.getElementById('sespanel').classList.contains('sliding'));
ok(await phone.$eval('#panes', el => el.offsetHeight) < paneH0, 'then the terminal snaps to make room');
// Commands wants a shell under it now, and the tab that was open got ended
// above, so put one there, or this measures the guard instead of the swap.
await phone.evaluate(() => {
  const shell = t => t.kind === 'term' && !t.arg.startsWith('claude:');
  if (!tabs.some(shell)) newShell();
  panes[active] = tabs.find(shell).id;
  render();
});
await phone.click('#mMacros');
// the close is a slide now: the class drops when the tween lands
await phone.waitForFunction(() => !document.getElementById('sespanel').classList.contains('show'));
ok(await phone.$eval('#macpanel', el => el.classList.contains('show')), 'Commands closes it and opens the macros');
ok(await phone.$eval('#commands', el => el.parentElement.id === 'macpanel' && el.querySelectorAll('[data-m]').length > 0), 'bb list lives in the panel');
ok(await phone.$eval('.tab [data-pin]', el => getComputedStyle(el).display === 'none'), 'pin buttons hidden on a phone');
// Claude on a project with a transcript opens the Resume/New chooser, which
// must be visible on a phone (it once shared the hidden pin menu's class).
// Both in one evaluate: setView animates the column synchronously, so asking
// afterwards in a second round trip was asking whether the 220ms tween had
// outlived the trip: true on an idle box, not on a loaded one.
ok(await phone.evaluate(() => {
     setView('dash');
     return document.querySelector('.col.side').getAnimations().length > 0;
   }),
   'the view slides across the switch');
// A Claude session runs on a NODE (R47), so the chooser is what the press
// opens when one COULD start; a project with no node gets the reason under
// the row instead, which is agent.mjs's. So alpha gets a node reporting a
// session half good enough to take one, for as long as this block needs it.
const bapi = async (path, body, hdrs) => (await fetch(URL.replace(/\/$/, '') + path, {
  method: body ? 'POST' : 'GET',
  headers: { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'),
             'Content-Type': 'application/json', ...(hdrs || {}) },
  ...(body ? { body: JSON.stringify(body) } : {}) })).json();
const deskbox = await bapi('/api/v1/nodes', { action: 'enroll', name: 'deskbox' });
await bapi('/api/v1/agent/enroll', { user: 'bb', version: 'harness', census: {
    cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux',
    session: { up: true, port: 7681, ro_port: 7682, user: 'bb',
               workspace: true, writable: true, boot: '9.9', up_s: 5000, claude: '1.0.0 (Claude Code)' } } },
  { Authorization: 'Bearer ' + deskbox.token });
await bapi('/api/prefs', { project: 'alpha', node: deskbox.id });
// ...with the tester signed in to Claude there, as that node would have
// reported it: a Claude press on a node with no sign-in offers the sign-in
// instead of Resume and New conversation, which is signin.mjs's to show.
{
  const rec = `${DIR}/home/.claude/.bb-grant.json`;
  const d = JSON.parse(readFileSync(rec, 'utf8'));
  d.nodes[deskbox.id] = { email: 'tester@example.com', plan: 'max', at: 1 };
  writeFileSync(rec, JSON.stringify(d));
}
// Under a full run this wait has crashed the file more than once (B124): a
// node is live for LIVE_S after its hello, and a slow box can spend that
// before the poll reads deskbox back. So the hello is repeated between
// shorter waits rather than one long wait on a liveness that lapses.
const deskboxCensus = { cpu: 2, mem_mb: 4096, arch: 'x86_64', system: 'linux',
  session: { up: true, port: 7681, ro_port: 7682, user: 'bb',
             workspace: true, writable: true, boot: '9.9', up_s: 5000, claude: '1.0.0 (Claude Code)' } };
for (let tries = 0; ; tries++){
  try {
    await refreshUntil(phone, () => (state?.projects || [])
      .find(p => p.name === 'alpha')?.session_at === 'deskbox', { timeout: 30000 });
    break;
  } catch (e) {
    if (tries >= 3) throw e;
    await bapi('/api/v1/agent/hello', { census: deskboxCensus, version: 'harness', running: [] },
               { Authorization: 'Bearer ' + deskbox.token });
  }
}
// Pressed IN THE PAGE rather than through Playwright's click. The click waits
// for the button to be "visible, enabled and stable", and this row is redrawn
// by every poll, so under a full run the wait ran out and took the whole file
// with it: five times before this, always green when run alone, which is the
// worst shape a test has (B124). Nothing here is about hit-testing the button,
// only about what pressing it opens.
const pressAlpha = () => phone.$eval('#projects [data-c="alpha"]', b => b.click());
// Waited for by the condition openClaude() ACTUALLY branches on, which the
// wait above is not: session_at says only that there is a node a session
// could run on. The press opens the Resume/New chooser when the project has
// a transcript AND this account's claude session is not in state.sessions;
// with a live one listed it starts a session straight away and no chooser is
// ever drawn, which is the timeout that has taken this whole file down under
// a full run on both the node and the container. Waiting on last_claude
// alone was tried and was half the fact.
// The transcript this needs is written HERE rather than relied on from the
// harness's setup. The chooser is offered only for a project that already had
// a conversation, and ~/.claude/projects becomes a link onto the share once a
// node's account is synced, which orphans the fixture written before the
// server started. Depending on it made this file's result depend on which
// other files ran first: green alone, and a crash that took the whole file
// down under a full run, on the node and in the container alike. What is
// being tested is what the press opens, so the precondition is this file's to
// establish.
mkdirSync(`${DIR}/home/.claude/projects/${`${DIR}/ws/alpha`.replace(/\//g, '-')}`,
          { recursive: true });
writeFileSync(`${DIR}/home/.claude/projects/${`${DIR}/ws/alpha`.replace(/\//g, '-')}`
              + '/bbbbbbbb-0000-4000-8000-00000000c0de.jsonl',
              '{"type":"user","message":{"role":"user","content":"hello"}}\n');
const chooserReady = () => phone.evaluate(() => {
  const p = (state?.projects || []).find(x => x.name === 'alpha');
  return { last_claude: !!p?.last_claude, why: p?.session_why || '',
           mine: myClaude('alpha'), live: [...liveSessions()] };
});
await phone.waitForFunction(() => {
  const p = (state?.projects || []).find(x => x.name === 'alpha');
  return !!p?.last_claude && !liveSessions().has(myClaude('alpha'));
}, null, { timeout: 20000 }).catch(async () => {
  console.log('[diag] chooser precondition never held:', JSON.stringify(await chooserReady()));
});
await pressAlpha();
// The press can land on a row the poll is replacing under load, and then
// opens nothing; a press that opened nothing is pressed again, and one
// that did is left alone, since a second press would close the chooser.
await phone.waitForSelector('.resumemenu', { timeout: 5000 }).catch(async () => {
  await pressAlpha();
  await phone.waitForSelector('.resumemenu', { timeout: 10000 });
});
const chooser = await phone.$eval('.resumemenu', el => ({ shown: getComputedStyle(el).display !== 'none',
  buttons: [...el.querySelectorAll('button')].map(b => b.textContent.trim()), text: el.textContent.trim().slice(0, 120) }));
ok(chooser.shown && chooser.buttons.length === 2 && /^Resume/.test(chooser.buttons[0]) && chooser.buttons[1] === 'New conversation',
   `phone: Claude on a project with history shows the Resume/New chooser (${chooser.buttons.join(' | ') || chooser.text})`);
// ...where it can be seen. The sidebar scrolls, the chooser is placed inside
// the card, and pressing Claude on a project whose session has ended opens
// this and NOTHING ELSE, so one drawn below the fold is a press with no
// visible result, which is what bug #65 was reported as.
//
// Set up properly or this asserts nothing: the row has to be at the bottom
// edge before the press, and the press has to be dispatched rather than
// clicked, because Playwright scrolls a target into view for you and would
// undo the very thing being reproduced.
await phone.click('#projects [data-c="alpha"]');          // put it away again
await phone.waitForFunction(() => !document.querySelector('.resumemenu'));
// A window short enough that the row is at the bottom edge, which is the
// only shape in which the chooser has nowhere to be drawn; on a tall one it
// lands on screen whatever this does, and the assertion would be vacuous.
// The press is DISPATCHED rather than clicked, because Playwright scrolls a
// target into view for you and would undo the thing being reproduced.
await phone.setViewportSize({ width: 400, height: 300 });
await phone.evaluate(() => {
  const side = document.querySelector('.col.side');
  const btn = document.querySelector('#projects [data-c="alpha"]');
  side.scrollTop += btn.getBoundingClientRect().bottom
                    - side.getBoundingClientRect().bottom + 6;
});
await phone.evaluate(() => document.querySelector('#projects [data-c="alpha"]').click());
await phone.waitForSelector('.resumemenu', { timeout: 10000 });
// Where it rests, not where it is mid-entrance: menuIn slides the chooser
// down 5px over 140ms, and how far along that is when a round trip lands is
// a fact about the box. Where it stops is what the operator sees (B77).
await phone.waitForFunction(() => document.querySelector('.resumemenu')
  ?.getAnimations().every(a => a.playState !== 'running'), null, { timeout: 10000 });
ok(await phone.$eval('.resumemenu', el => {
     const m = el.getBoundingClientRect();
     const side = el.closest('.col.side').getBoundingClientRect();
     return m.top >= side.top - 1 && m.bottom <= side.bottom + 1;
   }),
   '...brought into the scrolled sidebar, not left below its fold');
await phone.setViewportSize({ width: 400, height: 800 });
await phone.click('.resumemenu [data-n]');
await phone.waitForFunction(() => tabs.some(t => t.arg === 'claude:alpha') && document.body.dataset.view === 'terminal');
ok(true, 'phone: New conversation opens the Claude tab and switches to the terminal');
// ...and alpha goes back to having no node, which is how every other file
// here finds it.
await bapi('/api/prefs', { project: 'alpha', node: '' });
await bapi('/api/v1/nodes', { action: 'retire', id: deskbox.id });
// A picker rather than a strip to swipe (R119 step 5).
ok(await phone.$eval('#tabPick', el => getComputedStyle(el).display !== 'none')
   && await phone.$eval('#tabbar', el => getComputedStyle(el).display === 'none'),
   'the tab strip is the tab picker on a phone');

// Swapping one flyout for another: the outgoing one stays under the incoming
// slide and the terminal changes size once, when the new one lands. Commands
// needs a shell under it, so make sure the pane is showing one.
await phone.evaluate(() => {
  const shell = t => t.kind === 'term' && !t.arg.startsWith('claude:');
  if (!tabs.some(shell)) newShell();
  panes[active] = tabs.find(shell).id;
  render();
});
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
// The whole gesture inside one evaluate, and the wait measured against the
// animation's OWN clock rather than a sleep. Three round trips around a 200ms
// tween is a race: on a loaded box the close lands before the second tap, so
// there is no mid-slide left to reverse from and the test fails for a reason
// that is about the box. Waiting on currentTime is exactly the condition the
// assertion cares about: that the panel really is part-way down.
const from = await phone.evaluate(async () => {
  const el = document.getElementById("macpanel");
  document.getElementById("mMacros").click();          // closing (slides)
  const a = el.getAnimations()[0];
  if (a) await new Promise(res => {
    const tick = () => (a.playState !== "running" || a.currentTime >= 90)
      ? res() : requestAnimationFrame(tick);
    tick();
  });
  document.getElementById("mMacros").click();          // reopen mid-slide
  return parseFloat(el.getAnimations()[0]?.effect.getKeyframes()[0].height);
});
ok(from > 0 && from < hFull, `re-tap mid-slide resumes from the current height (${from} of ${hFull}px)`);
await phone.waitForFunction(() => !document.getElementById('macpanel').classList.contains('sliding'));

// Picking a session from the flyout closes the flyout: it was covering the
// very terminal the tap asked to see. (The desktop half ended both fixture
// sessions above, so make one to pick.)
tmuxNew('shell-7');
await phone.evaluate(() => refresh());
await phone.waitForFunction(() => document.querySelector('#sessions [data-go="shell-7"]'), { timeout: 15000 });
await phone.click('#mSessions');
await phone.waitForFunction(() => document.getElementById('sespanel').classList.contains('show') && !document.getElementById('sespanel').classList.contains('sliding'));
await phone.click('#sessions [data-go="shell-7"]');
ok(await phone.evaluate(() => !showSessions), 'picking a session closes the Sessions flyout');

// Keys over a document tab: not in the bar at all, so Sessions and Chat
// have it (B460).
await phone.evaluate(() => openNotebook('alpha'));
await phone.waitForFunction(() => tabOf(panes[active])?.kind === 'notebook');
ok(await phone.$eval('#mKeys', b => b.hidden && getComputedStyle(b).display === 'none'), 'Keys leaves the bar over a document tab');
ok(await phone.$eval('#mMacros', b => b.hidden), '...and so does Commands');
ok(await phone.$$eval('#mobar button', bs => bs.filter(b => b.offsetWidth).every(b => b.scrollWidth <= b.clientWidth + 1)),
   '...and what is left is not cut short');
// A Claude tab is a terminal, but not one to type keys or macros into: they
// go to a conversation with its own idea of what a keystroke means.
await phone.evaluate(() => {
  const t = tabs.find(x => x.kind === 'term' && x.arg.startsWith('claude:'));
  if (t) { panes[active] = t.id; render(); }
});
ok(await phone.evaluate(() => !tabs.some(t => t.arg.startsWith('claude:')))
   || (await phone.$eval('#mKeys', b => b.hidden)
       && await phone.$eval('#mMacros', b => b.hidden)),
   '...and both leave it over a Claude tab');

// With many open, the picker names the one in front, whichever it is: no
// tab is ever off the end of anything.
await phone.evaluate(() => { for (let i = 0; i < 6; i++) newShell(''); });
await phone.evaluate(() => focusTab(tabs[tabs.length - 1].id));
await phone.waitForFunction(() => document.querySelector('#tabPick .nm')?.textContent === tabLabels().get(tabs[tabs.length - 1].id)
  && document.querySelector('#tabPick .pill')?.textContent === String(tabs.length), { timeout: 5000 });
ok(true, 'the picker names the last tab opened and counts them all');
await phone.click('#tabPick');
const last = await phone.evaluate(() => tabs[tabs.length - 1].id);
await phone.click(`#tabPickList [data-pmin="${last}"]`);
await phone.waitForFunction(id => !document.querySelector(`#tabPickList [data-pshow="${id}"]`), last, { timeout: 5000 });
ok(await phone.$eval('#tabPickList', l => !l.hidden),
   '...and a terminal minimized from its list leaves its row and keeps the list open for the next');
await phone.keyboard.press('Escape');
await phone.waitForFunction(() => document.getElementById('tabPickList').hidden, { timeout: 5000 });
ok(true, '...which Escape closes');

// The view a phone was on comes back after a reload.
await phone.evaluate(() => setView('terminal'));
await phone.reload();
await phone.waitForFunction(() => document.body.dataset.view === 'terminal', { timeout: 20000 });
ok(true, 'a phone reload lands back on the terminal view');
// ...unless the URL says otherwise: ?view= is how something that can only
// speak URLs (bb capture shot, a bookmark) asks for a side, and it beats the memory.
await phone.goto(URL + '?view=dash');
await phone.waitForFunction(() => document.body.dataset.view === 'dash', { timeout: 20000 });
ok(true, '?view= overrides the remembered side');
ok(phone.errors.length === 0, `phone: zero console errors${phone.errors.length ? ': ' + phone.errors.join(' | ') : ''}`);
await closePage(phone);

// A phone held sideways: a flyout must not push the bottom bar off the
// screen; it gives way, and the terminal keeps a strip.
const land = await newPage(browser, { viewport: { width: 844, height: 390 } });
await land.goto(URL);
await land.waitForFunction(() => state !== null, { timeout: 30000 });
// A terminal in front first: Commands opens only over a shell, and since
// R131 a fresh browser starts on the front tab as of the strip's last
// change, which may be a document (B494).
await land.evaluate(() => { setView('terminal'); const t = tabs.find(x => x.kind === 'term'); if (t) focusTab(t.id); mobPanel('macros'); });
await land.waitForFunction(() => document.getElementById('macpanel').classList.contains('show') && !document.getElementById('macpanel').classList.contains('sliding'));
const fit = await land.evaluate(() => ({ bar: document.getElementById('mobar').getBoundingClientRect().bottom, panes: document.getElementById('panes').offsetHeight }));
ok(fit.bar <= 390 && fit.panes >= 90, `landscape: the bar stays on screen with a flyout open (bar bottom ${Math.round(fit.bar)}px, terminal ${fit.panes}px)`);
await land.evaluate(() => mobPanel('keys'));
await land.waitForFunction(() => document.getElementById('keys').classList.contains('show') && !document.getElementById('keys').classList.contains('sliding'));
const fit2 = await land.evaluate(() => ({ bar: document.getElementById('mobar').getBoundingClientRect().bottom, panes: document.getElementById('panes').offsetHeight }));
ok(fit2.bar <= 390 && fit2.panes >= 90, `landscape: same with the keys (bar bottom ${Math.round(fit2.bar)}px, terminal ${fit2.panes}px)`);
await closePage(land);

// ---- a tab that outlived its container ---------------------------------
// A browser left open across a restart still holds its Claude tabs, and a
// phone waking up reloads the terminal iframe, which spawns whatever the URL
// names. Pruning the saved layout at boot cannot stop that, because the page
// never re-read it. So the URL carries the boot it was opened in, and bb-tty
// refuses to *start* a session for one from a previous run. Attaching to a
// session that is already there is untouched: that is how a tab comes back.
const BBTTY = join(dirname(fileURLToPath(import.meta.url)), '..', 'bb-tty');
const tty = (arg) => {
  try {
    return execFileSync(BBTTY, [arg], { env: { ...process.env,
      WORKSPACE: `${DIR}/ws`, DASHBOARD_STATE: `${DIR}/state` },
      stdio: ['ignore', 'pipe', 'pipe'] }).toString();
  } catch (e) { return String(e.stdout || '') + String(e.stderr || ''); }
};
ok(/before the container restarted/.test(tty('claude:alpha:b:not-this-boot')),
   'a Claude tab stamped with an older boot is refused rather than obeyed');
ok(/before the container restarted/.test(tty('claude:alpha')),
   '...and so is one with no stamp at all, since only the dashboard mints these');
// A name that is not a project, so this asks the question without starting
// anything: the point is only that the boot gate is a Claude rule.
ok(!/before the container restarted/.test(tty('shell:nosuchproject:1')),
   'a shell carries no stamp and never did: it is safe to recreate in place');

// The task line is what a session is doing, and only while it is doing it.
// It comes off the tmux pane title, which Claude sets as it goes and never
// clears, so an idle session kept showing the last thing it had been doing,
// with no age on it and nothing to expire it. "done: <whatever>" reads as a
// status and is a fossil.
const taskLines = await page.evaluate(() => {
  const seen = {};
  const rows = () => Array.from(document.querySelectorAll('#sessions .row .sub'))
                          .map(d => d.textContent.trim());
  const s = (state, task) => ({name: 'claude-alpha', attached: false, cwd: '',
                               claude: {state, task}});
  drawSessions([s('working', 'reading the emulator log')]);
  seen.working = rows();
  drawSessions([s('waiting', 'reading the emulator log')]);
  seen.idle = rows();
  return seen;
});
ok(taskLines.working.some(t => /working on: reading the emulator log/.test(t)),
   'a working session says what it is working on');
ok(!taskLines.idle.some(t => /emulator log/.test(t)),
   '...and an idle one says nothing, rather than the last thing it happened to do');

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ': ' + page.errors.join(' | ') : ''}`);
// ---- a terminal tab closes when its session ends ------------------------
// bb-tty execs claude, so the pane's process IS the conversation: exiting it
// (Ctrl+C twice, /exit, a crash) ends the tmux session, and the tab used to be
// left holding a dead terminal until somebody pressed ✕. Nothing is lost by
// closing it: the transcript is on disk and the project's Claude button offers
// to resume it.
tmuxNew('shell-reaped');
await page.evaluate(() => openTab({kind: 'term', arg: 'shell:reaped'}));
await page.waitForFunction(() => tabs.some(t => t.arg === 'shell:reaped'),
                           null, { timeout: 15000 });
// Seen alive first: the rule is seen-then-gone, because "no session" is also
// true of a tab restored from a layout before anything has started.
await refreshUntil(page, () => seenLive.has('shell-reaped'), { timeout: 20000 });
ok(true, 'a terminal tab is noted once its session is actually running');
tmuxKill('shell-reaped');
await refreshUntil(page, () => !tabs.some(t => t.arg === 'shell:reaped'),
                   { timeout: 20000 });
ok(true, '...and the tab closes when that session ends');

// The case the transition rule exists for: a tab whose session has NEVER been
// seen is left alone, because that is what every tab looks like for a moment
// after a restore, and reaping those would wipe the strip at every boot.
await page.evaluate(() => openTab({kind: 'term', arg: 'shell:neverran'}));
await page.waitForFunction(() => tabs.some(t => t.arg === 'shell:neverran'),
                           null, { timeout: 15000 });
await page.evaluate(() => refresh());
await page.evaluate(() => refresh());
ok(await page.evaluate(() => tabs.some(t => t.arg === 'shell:neverran')),
   '...while one whose session was never seen is left where it is');
await page.evaluate(() => {
  const t = tabs.find(x => x.arg === 'shell:neverran');
  if (t) dropTab(t.id);
});

// ---- a new run of the container reloads the page ------------------------
// Whichever poll notices first. The status poll used to drop the Claude tabs
// that died with the container and open the changelog, and carry on with the
// code it had: the operator met the old Global rules dialog under the new
// version's notes. It reloads now, before the changelog, so the page is the
// new run's code and the changelog is opened by that page.
{
  await page.evaluate(() => { window.__before = 1; });
  const nav = page.waitForNavigation({ timeout: 20000 }).then(() => true).catch(() => false);
  await page.evaluate(async () => {
    while (refreshBusy) await new Promise(r => setTimeout(r, 50));   // a poll in flight would swallow the call
    bootSeen = 'the-run-before';
    refresh();
  });
  const reloaded = await nav;
  await ready(page);
  ok(reloaded && await page.evaluate(() => window.__before === undefined),
     `a restart the status poll notices reloads the page (${reloaded ? 'reloaded' : 'did not'})`);
}

await done(browser);
