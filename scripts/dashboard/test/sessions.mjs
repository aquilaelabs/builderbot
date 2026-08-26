// Sessions card and its relationship to the tab strip: name goes to the tab,
// the button minimizes/closes/opens, attached pill and pane glyphs, tooltips,
// macros only on shell tabs, middle-click ends a session, findings tab
// behavior, and the phone's bottom bar: flyout slides and swaps, the strip
// arrows and reveal, and the remembered view.
import { launch, newPage, ok, done, sleep, tmuxNew, tmuxFmt, layoutSettled, URL, DIR } from './lib.mjs';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
// Sessions hangs off the terminal now, at every width, so a desktop page has
// to open the panel before there is a list to click — the sidebar card it
// used to live in is gone.
await page.waitForSelector('#mSessions');
await page.click('#mSessions');
await page.waitForFunction(() => document.querySelectorAll('#sessions .row').length >= 2, { timeout: 40000 });
// On a desktop the flyout is an OVERLAY: the terminal keeps its height, and
// with it its fit and its scrollback — a resize costs a terminal a refit and a
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
// GitLab — so between the three shells every ghosting state appears, and the
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
ok(await page.$eval('#commands [data-m]', b => b.disabled) && await page.$eval('#runner [data-m]', b => b.disabled), 'macros grayed on a Claude tab');
const nd = page.dialogs.length;
await btn('claude-alpha').click();
await page.waitForFunction(() => !document.querySelector('[data-go="claude-alpha"]'), { timeout: 15000 });
ok(page.dialogs.length === nd + 1 && page.dialogs[nd].includes('Claude'), 'Close asked first, then ended the session');

// The session is gone; a tab still pointing at it takes a Resume's argument
// so the transcript id reaches the terminal, and the frame is rebuilt for it.
await page.evaluate(() => openTab({kind:'term', arg:'claude:alpha', label:'Claude: alpha'}));
await page.evaluate(() => openTab({kind:'term', arg:'claude:alpha:r:abc123', label:'Claude: alpha'}));
const resumed = await page.evaluate(() => ({
  tabs: tabs.filter(t => sessionOf(t.arg) === 'claude-alpha').length,
  arg: tabs.find(t => sessionOf(t.arg) === 'claude-alpha')?.arg,
  src: document.querySelector('#pane0 .slot.on iframe')?.src,
  slots: [...document.querySelectorAll('#pane0 .slot')].map(c => c.dataset.key),
}));
ok(resumed.tabs === 1 && resumed.arg === 'claude:alpha:r:abc123'
     && (resumed.src || "").includes(encodeURIComponent('claude:alpha:r:abc123'))
     // ...and the frame the old tab had is gone with it. A pane keeps
     // terminals alive behind the visible one; one whose tab has closed is
     // still an attached client, on a session nothing is showing.
     && !resumed.slots.some(k => k.includes('|claude:alpha') && !k.includes(':r:')),
   `Resume on a dead session's tab carries the transcript id into the frame (${JSON.stringify(resumed)})`);
await page.evaluate(() => hideTab(tabs.find(t => sessionOf(t.arg) === 'claude-alpha').id));

await page.click('#findingsSum .row[data-ana="alpha"]');
await page.waitForSelector('.pane .nb [data-view="analysis"]:not([hidden]) .rule',
                           { timeout: 20000 });
ok(true, 'a project\'s row on the card opens its notebook, on the Analysis view');
ok(await page.$eval('#commands [data-m]', b => b.disabled), 'macros grayed on a notebook tab');
ok(await page.$$eval('.pane .nb .rule .rid .pill', ps => ps.length > 0),
   '...with the findings for that project alone, worst level first');
// The fourth log. Nothing writes it — it is the difference between one scan
// and the last — but it opens and filters like the other three, which is the
// point of it being here at all.
await page.click('.pane .nb #anaLog');
await page.waitForFunction(() => !document.getElementById('anaHist').hidden,
                           null, { timeout: 15000 });
ok(await page.$eval('.pane .nb #anaList', el => el.hidden)
   && await page.$eval('.pane .nb #anaHistBar', el => !el.hidden),
   'Analysis has a History that swaps the findings out, the way the other three do');
ok((await page.$eval('.pane .nb #anaHistBar input', i => i.placeholder)).includes('search')
   && await page.$$eval('.pane .nb #anaHistBar select', ss => ss.length === 2),
   '...with the same search box and the same two filters');
// At "all time" with nothing to show, this log says why it is empty rather
// than reusing the shared line about a notebook nobody has written in — no
// one writes this one at all.
await page.selectOption('.pane .nb #anaHistBar .hwhen', '0');
await page.waitForFunction(() => /first scan/.test(
  document.getElementById('anaHist').textContent), null, { timeout: 15000 });
ok(true, '...and says why it is empty rather than looking broken');
await page.click('.pane .nb #anaLog');
await page.waitForFunction(() => document.getElementById('anaHist').hidden,
                           null, { timeout: 15000 });
// A notebook tab survives the reload and loads itself — the restore story
// the findings tab used to carry, now the notebook's.
await layoutSettled(l => l.tabs.some(t => t.kind === 'todo'));
await page.reload();
await page.waitForFunction(() => document.querySelector('.pane .nb') !== null,
                           { timeout: 30000 });
ok(true, 'a notebook tab restored from the layout loads itself');
// A reload closes the flyout, the way it always has on a phone — the panel
// is a toggle, not a card that is simply there. Open it again for the rest.
await page.click('#mSessions');
await page.evaluate(() => hideTab(tabs.find(t => t.kind === 'todo').id));

// The rest needs shell-9 on the strip; reopen it if the restore above failed.
await page.evaluate(() => { if (!tabs.some(t => sessionOf(t.arg) === 'shell-9'))
  openTab({kind:"term", arg: argForSession('shell-9'), label:'shell-9'}); });
await page.evaluate(() => focusTab(tabs.find(t => sessionOf(t.arg) === 'shell-9').id));
ok(await page.$eval('#commands [data-m]', b => !b.disabled), 'macros live on a shell tab');
// no tabs at all → grayed too, with a tooltip saying to open a shell
await page.evaluate(() => { const keep = tabs.slice(); keep.forEach(t => dropTab(t.id)); });
ok(await page.$eval('#commands [data-m]', b => b.disabled && /open one/.test(b.title))
   && await page.$eval('#runner [data-m]', b => b.disabled), 'macros grayed with no tab open');
await page.evaluate(() => openTab({kind:"term", arg: argForSession('shell-9'), label:'shell-9'}));
await page.waitForFunction(() => tabs.some(t => sessionOf(t.arg) === 'shell-9'));

// A project with a dot in its name: tmux stores its session as claude-ep_silon,
// and the page must still label it, reopen it and let the server end it.
tmuxNew('claude-ep_silon');
await page.evaluate(() => refresh());
await page.waitForFunction(() => document.querySelector('#sessions [data-go="claude-ep_silon"]'), { timeout: 15000 });
ok((await page.$eval('#sessions [data-go="claude-ep_silon"]', el => el.textContent.trim())) === 'Claude: ep.silon', 'dotted project: session labeled by its project name');
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
// About control carries the word instead — and exactly one of the two, never
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
// .click() returns the panel is already absolute and its animation started —
// no frame, no poll and no other animation can land between the two reads.
// Sampling the baseline in an earlier round trip is what CI kept failing on,
// four runs running, while an idle box passed: the panel assertion above it
// passed in the same breath, so the panel was still absolute and cannot have
// been what moved the terminal — the baseline was simply stale. The likeliest
// mover is setView('terminal') just above, a 220ms slide that holds overflow-x
// on <main> for its duration — and it was. One task keeps anything from
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
// above — so put one there, or this measures the guard instead of the swap.
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
// Claude on a project with a transcript opens the Resume/New chooser — which
// must be visible on a phone (it once shared the hidden pin menu's class).
// Both in one evaluate: setView animates the column synchronously, so asking
// afterwards in a second round trip was asking whether the 220ms tween had
// outlived the trip — true on an idle box, not on a loaded one.
ok(await phone.evaluate(() => {
     setView('dash');
     return document.querySelector('.col.side').getAnimations().length > 0;
   }),
   'the view slides across the switch');
await phone.click('#projects [data-c="alpha"]');
ok(await phone.$eval('.resumemenu', el => getComputedStyle(el).display !== 'none' && el.querySelectorAll('button').length === 2),
   'phone: Claude on a project with history shows the Resume/New chooser');
await phone.click('.resumemenu [data-n]');
await phone.waitForFunction(() => tabs.some(t => t.arg === 'claude:alpha') && document.body.dataset.view === 'terminal');
ok(true, 'phone: New conversation opens the Claude tab and switches to the terminal');
ok(await phone.$eval('#tabL', el => getComputedStyle(el).display !== 'none') && await phone.$eval('#tabbar', el => getComputedStyle(el).flexWrap === 'nowrap'),
   'strip is one row with scroll arrows');

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
// assertion cares about — that the panel really is part-way down.
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

// Keys over a document tab: the toggle is disabled and says why.
await phone.evaluate(() => openNotebook('alpha'));
await phone.waitForFunction(() => tabOf(panes[active])?.kind === 'todo');
ok(await phone.$eval('#mKeys', b => b.disabled && /not one/.test(b.title)), 'Keys is disabled over a document tab');
ok(await phone.$eval('#mMacros', b => b.disabled), '...and so is Commands');
// A Claude tab is a terminal, but not one to type keys or macros into: they
// go to a conversation with its own idea of what a keystroke means.
await phone.evaluate(() => {
  const t = tabs.find(x => x.kind === 'term' && x.arg.startsWith('claude:'));
  if (t) { panes[active] = t.id; render(); }
});
ok(await phone.evaluate(() => !tabs.some(t => t.arg.startsWith('claude:')))
   || (await phone.$eval('#mKeys', b => b.disabled)
       && await phone.$eval('#mMacros', b => b.disabled)),
   '...and both are disabled over a Claude tab');

// Opening a tab that sits off the end of the strip scrolls it into view, and
// the arrows gray at the ends they cannot go past.
await phone.evaluate(() => { for (let i = 0; i < 6; i++) newShell(''); });
await phone.waitForFunction(() => { const b = document.getElementById('tabbar'); return b.scrollWidth > b.clientWidth + 50; });
await phone.evaluate(() => { document.getElementById('tabbar').scrollTo({left: 0, behavior: 'instant'}); focusTab(tabs[0].id); });
await phone.evaluate(() => focusTab(tabs[tabs.length - 1].id));
await phone.waitForFunction(() => { const b = document.getElementById('tabbar'), t = b.querySelector('.tab.on');
  return t.offsetLeft + t.offsetWidth <= b.scrollLeft + b.clientWidth + 1; }, { timeout: 5000 });
ok(true, 'focusing a tab off the end of the strip scrolls it into view');
await phone.waitForFunction(() => document.getElementById('tabR').disabled, { timeout: 5000 });   // the smooth scroll lands
ok(await phone.$eval('#tabL', b => !b.disabled), 'at the right end › is grayed and ‹ is live');
await phone.evaluate(() => { document.getElementById('tabbar').scrollTo({left: 0, behavior: 'instant'}); });
await phone.waitForFunction(() => document.getElementById('tabL').disabled);
ok(await phone.$eval('#tabR', b => !b.disabled), 'at the left end ‹ is grayed and › is live');

// The view a phone was on comes back after a reload.
await phone.evaluate(() => setView('terminal'));
await phone.reload();
await phone.waitForFunction(() => document.body.dataset.view === 'terminal', { timeout: 20000 });
ok(true, 'a phone reload lands back on the terminal view');
// ...unless the URL says otherwise: ?view= is how something that can only
// speak URLs (bb shot, a bookmark) asks for a side, and it beats the memory.
await phone.goto(URL + '?view=dash');
await phone.waitForFunction(() => document.body.dataset.view === 'dash', { timeout: 20000 });
ok(true, '?view= overrides the remembered side');
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

// ---- a tab that outlived its container ---------------------------------
// A browser left open across a restart still holds its Claude tabs, and a
// phone waking up reloads the terminal iframe — which spawns whatever the URL
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
   'a shell carries no stamp and never did — it is safe to recreate in place');

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);
await done(browser);
