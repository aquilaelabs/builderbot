// Sidebar cards: universal collapse with a height tween, header-only
// controls, drag-to-reorder, ▤ reset, doctor's inner fold vs the card fold,
// per-project findings, valid-projects filter, and server-side persistence.
import { launch, newPage, ok, done, ready, doctorFixture, animatedDuring, refreshUntil,
         tmuxNew, tmuxKill, tmuxFmt, URL, DIR } from './lib.mjs';
import { writeFileSync, readFileSync, existsSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
await ready(page);
const order = () => page.$$eval('.side .card[data-card]', els => els.map(e => e.dataset.card));

// headers are title + chevron only; doctor sits first
const hs = await page.$$eval('.side .card[data-card] h2', hs => hs.map(h => ({
  buttons: h.querySelectorAll('button').length, chev: !!h.querySelector('.chev') })));
ok(hs.length === 6 && hs.every(h => h.buttons === 0 && h.chev),
   `headers are title + chevron only (${hs.length} cards)`);
ok((await order())[0] === 'doctor', 'doctor is first by default');
ok(await page.$eval('#bDocTog', el => el.textContent.trim() === 'all 3 ok'), 'doctor status row folded green');

// collapse animates, persists across reload
const collapsed = await animatedDuring(page,
  () => page.click('.card[data-card="tools"] h2'));
ok(collapsed.some(k => k.includes('tools'))
   && !await page.$eval('.card[data-card="tools"]', el => el.classList.contains('closed')),
   'collapse runs a height tween before the class lands');
await page.waitForFunction(() => document.querySelector('.card[data-card="tools"]').classList.contains('closed'));
await page.reload(); await ready(page);
ok(await page.$eval('.card[data-card="tools"]', el => el.classList.contains('closed')), 'collapsed state survives a reload');

// doctor: card collapse is the operator's; the verdict only drives the inner detail
await page.click('.card[data-card="doctor"] h2');
await page.waitForFunction(() => document.querySelector('.card[data-card="doctor"]').classList.contains('closed'));
doctorFixture('fail');
await page.evaluate(() => document.getElementById('bDoctor').onclick());
await page.waitForFunction(() => document.getElementById('docDot').className.includes('bad'));
ok(await page.$eval('.card[data-card="doctor"]', el => el.classList.contains('closed')), 'a FAIL leaves a collapsed doctor card collapsed');
ok(await page.$eval('#doctor', el => !el.hidden), '...but opens the detail behind it');
ok(await page.$eval('#docBar', el => getComputedStyle(el).display === 'none'), 'collapsed card hides the status row too');
doctorFixture('ok');
await page.evaluate(() => document.getElementById('bDoctor').onclick());
await page.waitForFunction(() => document.getElementById('docDot').className.includes('ok'));

// projects: fold-away toggle at the foot; slides the card. It names what it
// is hiding rather than calling all of it errors — gamma has no git, delta was
// excluded on purpose, and those are not the same kind of thing.
ok(await page.$eval('#projects #bAll', el => el.textContent.trim()) === 'Show Excluded (1) / Error (2)',
   'the toggle says what it is hiding, by kind');
ok((await animatedDuring(page, () => page.click('#projects #bAll')))
     .some(k => k.includes('projects')),
   'in-card toggle slides the card');
await page.click('#projects #bAll');

// findings card: per-project counts, valid projects only, plain button
const rows = await page.$$eval('#findingsSum .row', rs => rs.map(r => r.querySelector('.name').textContent.trim()));
// alpha and beta are the valid projects; the last row is the one path that
// genuinely places nowhere. gamma (error), delta (excluded), toolstore and
// vendored-junk all had findings in the fixture and none of them are here:
// attribution only knows valid projects now, so everything else is set aside
// rather than swelling the unattributed row it used to swamp.
ok(rows.join(',') === 'alpha,beta,unattributed paths',
   `findings card lists valid projects, and the one real orphan (${rows.join(',')})`);
ok(await page.$('#cardFindings .macros button') === null,
   'the card carries no report button — its rows open a notebook\'s Analysis view');
ok(await page.$eval('#findingsSum .row[data-ana="alpha"]', r => r.classList.contains('go')),
   '...and a project\'s row says it is clickable');

// The unplaceable row says where, not only how many. A bare count sat at 276
// through several passes without ever saying that 267 of them were one share.
ok(/somewhere\/else/.test(await page.$eval('#findingsSum .row:last-child .sub',
                                            e => e.textContent)),
   'the unattributed row names the paths it could not place');

// Which shares count as "not a project" no longer comes only from what sits
// inside /workspace. That worked while /workspace was the whole development
// share; pointing it at the projects folder took the SDK share outside it and
// sent 267 findings about downloaded toolchains to the label meant for a path
// that is genuinely wrong. The rule asks the mount table instead.
//
// Sliced out of server.py rather than imported: server.py is written to be
// run, not imported — it configures modules and seeds state at import — and
// the case that must not regress cannot be produced by mounting something on
// this box.
const sibOut = execFileSync('python3', ['-c', `
import posixpath, re, json
src = open(${JSON.stringify(new globalThis.URL('../server.py', import.meta.url).pathname)}).read()
i = src.index('def siblings_of('); j = src.index('def nonproject_dirs(')
ns = {'posixpath': posixpath}
exec(src[i:j], ns)
mi = """
26 25 0:24 /development/projects /workspace rw - fuse.shfs x rw
27 25 0:24 /development/SDK /sdk rw - fuse.shfs x rw
28 25 0:25 /appdata/BuilderBot /config rw - xfs x rw
29 25 0:26 / /reports ro - xfs x ro
"""
print(json.dumps(sorted(ns['siblings_of'](mi, '/workspace'))))
`], { encoding: 'utf8' });
const sib = JSON.parse(sibOut.trim().split('\n').pop());
ok(sib.includes('SDK'),
   'a share mounted beside the projects folder is known to be one');
ok(!sib.includes('BuilderBot'),
   '...while a mount from somewhere else is not, even named after a project');
ok(!sib.includes('reports') && sib.length === 1,
   '...and a whole-filesystem mount names no directory, so it says nothing');

// .bbignore hides a directory from the card entirely — not listed, not
// counted, not folded away under the Excluded/Error toggle either.
const names = await page.$$eval('#projects .name', ns => ns.map(n => n.textContent.trim()));
ok(!names.includes('toolstore'), 'a directory carrying .bbignore is not a project');
await page.click('#projects #bAll');
const all = await page.$$eval('#projects .name', ns => ns.map(n => n.textContent.trim()));
await page.click('#projects #bAll');
ok(!all.includes('toolstore'), '...not even with the error rows shown');
// An unmarked directory IS still listed, as a project with an error — that is
// the card doing its job, and how you find out something in the share is not a
// repository. What changed is that its findings no longer count as anybody's.
ok(all.includes('vendored-junk'),
   '...while one with no marker is listed, as the error it is');

// drag: reorder + slide + persistence; the click ending a drag is not a toggle
const hb = await (await page.$('.card[data-card="runner"] h2')).boundingBox();
const top = await (await page.$('.side .card[data-card]')).boundingBox();
// Recorded, not sampled. The FLIP tween is 140ms, and asking for it in a
// round trip AFTER the drag only works if that round trip happens to land
// inside those 140ms — true on an idle box, false on a loaded one, which is
// the test timing the browser rather than the behaviour. Wrapping
// Element.animate says whether the displaced card WAS animated, whenever
// that was. Undone straight after, so nothing later in this file is
// measuring through a patched prototype.
await page.evaluate(() => {
  window.__flipped = [];
  window.__realAnimate = Element.prototype.animate;
  Element.prototype.animate = function(...a){
    window.__flipped.push(this.dataset?.card || "");
    return window.__realAnimate.apply(this, a);
  };
});
await page.mouse.move(hb.x + 40, hb.y + 12); await page.mouse.down();
await page.mouse.move(hb.x + 40, top.y + 2, { steps: 10 });
await page.mouse.up();
const sliding = await page.evaluate(() => {
  Element.prototype.animate = window.__realAnimate;
  return window.__flipped.includes("doctor");
});
ok(sliding, 'displaced cards slide during a drag');
ok((await order())[0] === 'runner', `runner dragged to the top (${(await order()).join(',')})`);
ok(!(await page.$eval('.card[data-card="runner"]', el => el.classList.contains('closed'))), 'the drop did not toggle the card');
await page.reload(); await ready(page);
ok((await order())[0] === 'runner', 'order survives a reload');

// ▤ reset, now an item in the menu the broom opens rather than the broom's
// own action. The menu is the other half: twelve colour schemes, each swatch
// rendered in the scheme it selects.
await page.click('#bCards');
await page.waitForSelector('#uiMenu:not([hidden])');
ok(await page.$$eval('#uiMenu .sw', s => s.length) === 12,
   'the broom opens a menu of twelve schemes');
ok(await page.$eval('#uiMenu .sw[data-theme="default"]', b => b.classList.contains('on')),
   '...with the one in use marked, which is Default until something says otherwise');
// A swatch is the palette itself at 1cm — the stylesheet defines each scheme
// for .sw[data-theme] as well as for the page — so this reads the computed
// colour rather than trusting that two lists match.
const swAccent = t => page.$eval(`#uiMenu .sw[data-theme="${t}"] .swa`,
                                 e => getComputedStyle(e).backgroundColor);
ok(await swAccent('default') !== await swAccent('nostromo'),
   '...and two schemes really do preview differently, not just by label');

await page.click('#uiMenu .sw[data-theme="nostromo"]');
ok(await page.evaluate(() => document.documentElement.dataset.theme) === 'nostromo',
   'picking one applies it to the page');
ok(await page.evaluate(() => { try { return localStorage.getItem('bb.theme'); }
                               catch (e) { return null; } }) === 'nostromo',
   '...and remembers it here rather than on the server: it is about the room, not the work');
// Nostromo's flare is drawn, not fetched — no image files in a repo whose
// image is rebuilt weekly. The header's decal is the visible half.
ok(await page.evaluate(() => {
     const st = getComputedStyle(document.querySelector('header'), '::after');
     return /repeating-linear-gradient/.test(st.backgroundImage);
   }), '...and Nostromo brings its hazard stripe with it, as a gradient');

await page.click('#uiMenu .sw[data-theme="default"]');
ok(await page.evaluate(() => document.documentElement.dataset.theme) === undefined,
   'Default carries no attribute at all, so :root is simply left to stand');

// Escape shuts it, like the bell panel it sits beside.
await page.keyboard.press('Escape');
await page.waitForFunction(() => document.getElementById('uiMenu').hidden,
                           null, { timeout: 5000 });
ok(true, 'Escape closes the menu');

await page.click('#bCards');
await page.waitForSelector('#uiMenu:not([hidden])');
await page.click('#uiReset');
await page.waitForFunction(() => document.querySelector('.side .card[data-card]').dataset.card === 'doctor'
  && !document.querySelector('.side .card.closed'));
ok(true, 'reset restores default order and expands everything');

// The whole-report tab is retired: findings are read per project, in the
// notebook's Analysis view, and the digest is fetched when one is opened.
ok(await page.evaluate(() => !tabs.some(t => t.kind === 'findings')
     && typeof openFindings === 'undefined'),
   'no whole-report findings tab exists to open any more');

// The favicon set: served by the allow-list, linked from the head. Sizes and
// content types matter — a wrong type is a globe in the tab, silently.
const fav = await page.evaluate(async () => {
  const get = async u => { const r = await fetch(u);
    return [r.status, r.headers.get('content-type'), (await r.arrayBuffer()).byteLength]; };
  return { ico: await get('/favicon.ico'), svg: await get('/favicon.svg'),
           touch: await get('/apple-touch-icon.png'),
           links: [...document.querySelectorAll('link[rel*="icon"]')].map(l => l.getAttribute('href')) };
});
ok(fav.ico[0] === 200 && fav.ico[1] === 'image/x-icon' && fav.ico[2] > 1000, 'favicon.ico is served');
ok(fav.svg[0] === 200 && fav.svg[1] === 'image/svg+xml', 'favicon.svg is served');
ok(fav.touch[0] === 200 && fav.touch[1] === 'image/png', 'apple-touch-icon is served');
ok(fav.links.includes('/favicon.svg') && fav.links.includes('/favicon.ico')
   && fav.links.includes('/apple-touch-icon.png'), 'the head links all three');

// ---- which build this is ------------------------------------------------
// Beside the uptime, because an Unraid container keeps serving whatever it
// last pulled: "up two hours" and "has the fix" are different questions, and
// answering the second by inferring from the first is how a published fix and
// a stale container looked identical for a whole afternoon.
const build = await page.$eval('#build', e => ({ text: e.textContent.trim() }));
// The version rather than the commit, because it is the half that can be
// ordered: two shas do not say which came first, which is the question
// anybody reading this is actually asking.
ok(build.text === '0.4.0-dev.390+abc1234',
   'the header carries the ordered version the image was stamped with');
// The detail lives in the About popup now — a phone cannot hover a tooltip,
// and the truncated string it showed instead answered nothing.
await page.click('#bAbout');
await page.waitForSelector('#aboutModal:not([hidden])');
const about = await page.$eval('#aboutModal', e => e.textContent);
ok(about.includes('abc1234def5678901234567890abcdef12345678')
   && about.includes('2026-08-21T19:30Z') && /bb drift/.test(about),
   '...and About carries the whole commit, the build time and where to look');
await page.click('#aboutModal >> text=Close');
await page.waitForSelector('#aboutModal', { state: 'hidden' });
// An image built before versions existed still has a commit, and the header
// falls back to it rather than going blank.
ok(await page.evaluate(() => { drawBuild({ rev: 'deadbee1234', built: '' });
                               return document.getElementById('build')
                                      .textContent === 'deadbee'; }),
   '...falling back to the commit for an image with no version');
// An image built outside CI carries no stamp, and says so rather than leaving
// a gap that reads as "this dashboard is too old to tell you" — in the label
// and in the popup both.
ok(await page.evaluate(() => { drawBuild({ rev: '', built: '' });
                               return document.getElementById('build')
                                        .textContent === 'unstamped'
                                 && /built outside CI/.test(
                                      document.getElementById('aRev').textContent); }),
   'an unstamped image says so, rather than showing nothing');
await page.evaluate(() => refresh());

// ---- signing in and out ------------------------------------------------
// The first thing to get right on a new box, and the last place anybody would
// think to look for it on a command line. Driven against a stub claude: the
// real one would sign this container out for good.
await page.waitForSelector('#docAuth:not([hidden])', { timeout: 25000 });
ok((await page.$eval('#docAuth', e => e.textContent)).includes('tester@example.com'),
   'the doctor card says who this container is signed in as');
ok(await page.$('#bSignOut') !== null && await page.$('#bSignIn') === null,
   '...and offers the way out, not the way in');

// Not while a conversation is running: signing out pulls the ground from
// under every session on the box. The fixture has one.
ok(await page.$eval('#bSignOut', b => b.disabled)
   && (await page.$eval('#bSignOut', b => b.title)).includes('claude-alpha'),
   'signing out is dead while a Claude session is running, and says which');
const blocked = await page.evaluate(async () => {
  const r = await fetch('/api/signout', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: '{}' });
  return r.status;
});
ok(blocked === 409,
   '...and the server refuses it too, because a page can be fifteen seconds stale');
page.errors = [];

tmuxKill('claude-alpha');
await page.evaluate(() => refresh());
await page.waitForFunction(() => !document.getElementById('bSignOut')?.disabled,
                           { timeout: 25000 });
ok(true, 'with the last one ended, it comes alive');

// Signed out: the offer flips, and signing in opens a terminal, because the
// flow is a URL to open and a code to paste back.
writeFileSync(`${DIR}/auth.json`, readFileSync(`${DIR}/auth-out.json`));
// Kept asking rather than asked once: the verdict is cached for 20s and the
// page polls every 15, which together outlast any patience worth calling a
// timeout. See refreshUntil.
await refreshUntil(page, () => document.getElementById('bSignIn') !== null);
ok(await page.$('#bSignOut') === null
   && (await page.$eval('#docAuth', e => e.textContent)).includes('not signed in'),
   'signed out, it says so where the verdict is and offers the way in');
// ...and nothing offers to start a conversation that cannot start.
ok(await page.$$eval('#projects [data-c]', bs => bs.length > 0 && bs.every(b => b.disabled)),
   '...and every project\'s Claude button goes with it');

// And back: the stub's logout rewrites its own fixture, so this proves the
// button reaches the command without going near anybody's credentials.
writeFileSync(`${DIR}/auth.json`, readFileSync(`${DIR}/auth-in.json`));
await refreshUntil(page, () => document.getElementById('bSignOut') !== null);
page.dialogs = [];
await page.click('#bSignOut');
await page.waitForFunction(() => document.getElementById('bSignIn') !== null,
                           { timeout: 25000 });
ok(page.dialogs.some(d => /Sign this container out/.test(d)),
   'signing out asks first — every session here stops working');
ok(JSON.parse(readFileSync(`${DIR}/auth.json`, 'utf8')).loggedIn === false,
   '...and really runs it');
writeFileSync(`${DIR}/auth.json`, readFileSync(`${DIR}/auth-in.json`));

// ---- the sign-in, all of it -------------------------------------------
// No terminal anywhere in this: the flow runs under a pty the server holds,
// so the whole thing is drivable — which it never was while it lived in a
// tmux session behind ttyd. The stub claude is shaped like the real one: a
// URL, a prompt with no newline after it, and a line read back.
writeFileSync(`${DIR}/auth.json`, readFileSync(`${DIR}/auth-out.json`));
await refreshUntil(page, () => document.getElementById('bSignIn') !== null);
await page.click('#bSignIn');
await page.waitForFunction(() => document.getElementById('authCode') !== null,
                           { timeout: 25000 });
ok((await page.$eval('#docAuth a', a2 => a2.href)).includes('oauth/authorize'),
   'Sign in starts the flow and the card carries its link, tappable');
// In the button's own answer, not fifteen seconds later on the next poll:
// the flow prints the URL about a second in, and start() waits for it.
const started = await page.evaluate(async () => {
  const t0 = performance.now();
  const r = await fetch('/api/signin', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: '{}' });
  return { ms: performance.now() - t0, url: !!(await r.json()).signin?.url };
});
ok(started.url && started.ms < 8000,
   `...and the link is in the reply that starts it (${Math.round(started.ms)}ms)`);
ok(await page.$eval('#docAuth a', a2 => a2.target === '_blank'),
   '...opening away from the dashboard, not over it');
ok(await page.$$eval('.tab[data-id]', t => !t.some(x => /sign-in/i.test(x.textContent))),
   '...and no terminal was opened for it at all');

// The code is pasted into that field on a phone, while the card is polling
// every 1.2s to catch the answer. A poll must not take the field away: the
// card layout used to re-append every card on every poll, and a node leaving
// the document takes the focus — and the on-screen keyboard — with it.
await page.click('#authCode');
ok(await page.evaluate(() => document.activeElement?.id === 'authCode'),
   'the code field takes focus when it is tapped');
await page.evaluate(() => { refresh(); refresh(); });
await page.waitForTimeout(1500);
ok(await page.evaluate(() => document.activeElement?.id === 'authCode'),
   '...and keeps it across the polls that are watching for the answer');
await page.evaluate(() => applyCards(false));
ok(await page.evaluate(() => document.activeElement?.id === 'authCode'),
   '...even when the card order is reapplied, since nothing actually moved');

// A code that is not one never reaches the process.
const junk = await page.evaluate(async () => {
  const send = code => fetch('/api/login-code', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }) }).then(r => r.status);
  return { link: await send('https://claude.com/cai/oauth/authorize?code=true'),
           blank: await send('  \n\t '), long: await send('x'.repeat(5000)) };
});
ok(junk.link === 400 && junk.blank === 400 && junk.long === 400,
   'the link alone, an empty paste and a novel are refused; nothing else is');
page.errors = [];

// Everything else goes to the flow, junk stripped rather than refused, and
// the flow's own verdict comes back to the card. This paste carries the lot:
// base64 padding, a line break from a wrapped copy, a space, a control
// character, a zero-width mark from an HTML copy button, and the authorize
// URL the code page sets flush against the code so that Copy takes both.
const padded = await page.evaluate(async () => {
  const r = await fetch('/api/login-code', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code: '\u200bwrong+code/12\n34 =\u0003=https://claude.com/cai/oauth/authorize?code=true' }) });
  return r.status;
});
ok(padded === 200, '...while everything a real paste drags along goes through');
await page.waitForFunction(() => /did not finish|Login failed/.test(
  document.getElementById('docAuth')?.textContent || ''), { timeout: 25000 });
ok(/Login failed/.test(await page.$eval('#docAuth', e => e.textContent)),
   'a refused code is reported on the card, in the words the flow used');
ok(/\[got wrong\+code\/1234==\]/.test(await page.$eval('#docAuth', e => e.textContent)),
   '...and what reached the flow was the code, without what the copy added');

// And a good one signs in, which flips the whole row.
await page.click('#bSignIn');
await page.waitForFunction(() => document.getElementById('authCode') !== null,
                           { timeout: 25000 });
await page.fill('#authCode', 'goodcode1234');
await page.click('#bAuthCode');
await page.waitForFunction(() => document.getElementById('bSignOut') !== null,
                           { timeout: 30000 });
ok(JSON.parse(readFileSync(`${DIR}/auth.json`, 'utf8')).loggedIn === true
   && (await page.$eval('#docAuth', e => e.textContent)).includes('signed in as'),
   'a good code signs in, and the card goes back to saying who you are');
ok(await page.$('#authCode') === null,
   '...with the code field gone, because there is nothing left to ask');

// ---- the runner's states -----------------------------------------------
// Drawn directly, because the interesting ones need GitHub to be in a
// particular mood. The one that matters is the difference between a runner
// that cannot be reached and one waiting for GitHub to let go of its own
// name — which happens after every restart and every finished job on an
// ephemeral runner, clears itself in a minute or two, and had been wearing
// the same red as a real outage.
const runnerPill = r => page.evaluate(x => {
  drawRunner(x);
  const p = document.querySelector('#runner .pill');
  return { cls: p.className, text: p.textContent.trim(),
           body: document.getElementById('runner').textContent };
}, r);

let rp = await runnerPill({ enabled: true, listening: true, connected: false,
  detail: 'a session for this runner already exists' });
ok(rp.cls.includes('warn') && !rp.cls.includes('bad'),
   'waiting for GitHub to release a session is amber, not a fault');
ok(/waiting for GitHub/.test(rp.text) && /clears itself/.test(rp.body),
   '...and says it clears itself, which is the thing worth knowing');

rp = await runnerPill({ enabled: true, listening: true, connected: false,
  detail: 'connection refused' });
ok(rp.cls.includes('bad') && /cannot connect/.test(rp.text),
   'a runner that genuinely cannot reach GitHub is still red');

rp = await runnerPill({ enabled: true, listening: true, connected: true });
ok(rp.cls.includes('ok') && /listening for jobs/.test(rp.text),
   'and a healthy one says so');
await page.evaluate(() => refresh());

// The padlock: a project the operator keeps and runs themselves. Its whole
// point is being the OTHER button — excluding hides a row, this one leaves it
// intact and takes away only the session, so that is what gets asserted.
await page.evaluate(() => refresh());
await page.waitForSelector('#projects [data-k="alpha"]', { timeout: 10000 });
ok(await page.$$eval('#projects [data-k]', bs => bs.length > 0),
   'every project row carries a padlock');
await page.evaluate(() => setLocked('alpha', true));
await page.waitForFunction(
  () => document.querySelector('#projects [data-c="alpha"]')?.disabled === true,
  { timeout: 10000 });
const locked = await page.$eval('#projects .row:has([data-k="alpha"])', r => ({
  claude: r.querySelector('[data-c="alpha"]')?.disabled,
  shell:  !!r.querySelector('[data-s="alpha"]'),
  note:   r.textContent.replace(/\s+/g, ' '),
}));
ok(locked.claude === true, 'locking a project takes its Claude button away');
ok(locked.shell, '...and leaves the shell, which is the operator\'s own way in');
// The control moves at once; the row's note comes from the server payload and
// lands on the next poll. Instant feedback on the thing pressed, and the
// derived text a beat behind it rather than the page re-implementing it.
await page.waitForFunction(() => /locked/.test(
  document.querySelector('#projects .row:has([data-k="alpha"])')?.textContent || ''),
  { timeout: 15000 });
const note = await page.$eval('#projects .row:has([data-k="alpha"])',
  r => r.textContent.replace(/\s+/g, ' '));
ok(/locked/.test(note) && !/excluded/.test(note),
   '...saying locked rather than excluded, which is the other thing entirely');
await page.evaluate(() => setLocked('alpha', false));
await page.waitForFunction(
  () => document.querySelector('#projects [data-c="alpha"]')?.disabled === false,
  { timeout: 10000 });
ok(true, 'unlocking gives it back');

// The Projects tab: every project, pinned or not, and the same controls on
// each. The thumbtack decides only where a project is met, not what it can do.
await page.click('#projects #bAllProj');
await page.waitForSelector('.doc .projtab .row', { timeout: 15000 });
const inTab = await page.$$eval('.doc .projtab .row .name', ns => ns.map(n => n.textContent.trim()));
const inCard = await page.$$eval('#projects .row .name', ns => ns.map(n => n.textContent.trim()));
ok(inTab.length >= inCard.length && inCard.every(n => inTab.includes(n)),
   'the Projects tab lists at least what the card does');
ok(await page.$eval('.doc .projtab .row', r =>
     !!r.querySelector('[data-m]') && !!r.querySelector('[data-s]')
     && !!r.querySelector('[data-k]') && !!r.querySelector('[data-p]')),
   '...with the same buttons on a row: notebook, shell, padlock, thumbtack');

// Unpinning takes a project off the sidebar and leaves it on the tab, whole.
await page.evaluate(() => setProjectPinned('alpha', false));
await page.waitForFunction(
  () => ![...document.querySelectorAll('#projects .row .name')]
          .some(n => n.textContent.trim() === 'alpha'), { timeout: 15000 });
ok(await page.$$eval('.doc .projtab .row .name',
     ns => ns.some(n => n.textContent.trim() === 'alpha')),
   'an unpinned project leaves the sidebar and stays on the tab');
ok(await page.$eval('.doc .projtab .row:has([data-p="alpha"])',
     r => !!r.querySelector('[data-c]') && !!r.querySelector('[data-m]')),
   '...still carrying every control, which is the whole promise of the pin');
// The tab is a document, not a card adrift in one. It used to draw itself
// inside .card — rounded, bordered, floating on a darker gutter — while the
// notebook in the pane beside it filled the pane. One language.
ok(await page.$eval('.doc .projtab', e => !e.classList.contains('card'))
   && await page.$eval('.doc:has(.projtab)', e => e.classList.contains('flush')),
   'the Projects tab fills its pane the way the notebook does');
await page.evaluate(() => setProjectPinned('alpha', true));
await page.waitForFunction(
  () => [...document.querySelectorAll('#projects .row .name')]
          .some(n => n.textContent.trim() === 'alpha'), { timeout: 15000 });
ok(true, 'pinning it puts it back on the sidebar');

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);

// Unpinning from the sidebar has to move the Projects TAB too: they render
// the same rows from the same state, and a tab that drew once showed a lit
// thumbtack for a project that was no longer pinned — then clicking it sent
// the state it was already in, which is what "pinning only works sometimes"
// was. No poll is waited for: the answer to the pin request is the new set.
await page.click('#projects #bAllProj');
await page.waitForSelector('.doc .projtab .row', { timeout: 15000 });
const tackLit = () => page.$eval('.doc .projtab [data-p="beta"]',
                                 b => b.classList.contains('on'));
ok(await tackLit(), 'the Projects tab shows beta pinned');
await page.evaluate(() => setProjectPinned('beta', false));
await page.waitForFunction(() =>
  !document.querySelector('.doc .projtab [data-p="beta"]')?.classList.contains('on'),
  { timeout: 5000 });
ok(true, '...and unpinning it there unlights the tab\'s thumbtack too');
ok(!await page.$$eval('#projects .row .name',
     ns => ns.some(n => n.textContent.trim() === 'beta')),
   '...with the sidebar dropping it in the same breath');
await page.evaluate(() => setProjectPinned('beta', true));
await page.waitForFunction(() =>
  document.querySelector('.doc .projtab [data-p="beta"]')?.classList.contains('on'),
  { timeout: 5000 });
ok(true, '...and pinning it back lights it again, first click');
// A project whose name has a dot in it: the row's own selector has to survive
// one, or the change lands without its animation and nothing says why.
await page.evaluate(() => setProjectPinned('ep.silon', false));
await page.waitForFunction(() =>
  ![...document.querySelectorAll('#projects .row .name')]
    .some(n => n.textContent.trim() === 'ep.silon'), { timeout: 8000 });
ok(true, 'a dotted project name unpins too, animation and all');
// ...and back, which is the direction that used to be a plain redraw: pinning
// is watched from the Projects tab, which on a desktop sits in the column
// beside the sidebar, so the row has to unroll rather than shove the projects
// under it down between two frames. The tween is caught while it runs — the
// row exists before it, so waiting for the row alone would prove nothing.
const unrolls = page.waitForFunction(() => {
  // By the row's own name: the card has no thumbtack to reach it through.
  const r = document.querySelector('#projects .row[data-row="ep.silon"]');
  return !!r && r.getAnimations().length > 0;
}, { timeout: 8000 });
await page.evaluate(() => setProjectPinned('ep.silon', true));
await unrolls;
ok(true, '...and pinning it back unrolls the row instead of snapping it in');
await page.waitForFunction(() =>
  [...document.querySelectorAll('#projects .row .name')]
    .some(n => n.textContent.trim() === 'ep.silon'), { timeout: 8000 });

// The docker manager opens from Tools. What it LISTS is asserted in
// devapp.mjs, where a project actually has a compose file and an instance —
// here there are none, so the only honest assertion is that the tab opens and
// shows the daemon's own containers.
await page.click('#bDocker');
await page.waitForSelector('.dmtab', { timeout: 15000 });
ok(await page.$$eval('.dmtab .row', rs =>
     rs.some(r => /someone-elses/.test(r.textContent) && r.classList.contains('off'))),
   'the manager shows a container this dashboard did not start, marked not ours');
await page.click('#projects #bAllProj');
await page.waitForSelector('.doc .projtab .row', { timeout: 15000 });

const api = (path, body) => page.evaluate(async ([p, b]) => {
  const r = await fetch(p, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json().catch(() => ({})) };
}, [path, body]);

// Renaming is a dialog now, not a prompt — it has two fields. The token one
// appears only for a project that already has a token: offering to set one on
// a local repo would be offering a credential to nothing.
await page.click('.doc .projtab [data-rn="alpha"]');
await page.waitForSelector('#rnmodal:not([hidden])');
ok(await page.$eval('#rnName', el => el.value) === 'alpha',
   'the rename dialog opens on the current name');
ok(await page.evaluate(() => document.activeElement?.tagName) !== 'INPUT',
   '...with the keyboard down, like every other dialog here');
// alpha can push — the retroactive seeding granted it, on the deploy key its
// remote uses — so it is offered a token, and told what setting one does and
// does not do. beta cannot push, and is not offered one at all.
ok(!await page.$eval('#rnTokenField', el => el.hidden),
   'a project pushing with a deploy key is offered a token');
const kh = await page.$eval('#rnTokenHint', e => e.textContent);
ok(/deploy key/.test(kh) && /ssh remote/.test(kh),
   '...told plainly that a token does not take effect on an ssh remote by itself');
// The switch that makes it take effect. alpha's remote is ssh and it has no
// token, so the choice is real but one-sided until a token exists — and the
// side you cannot take is disabled rather than absent, because a control that
// silently does nothing is worse than one that says why.
await page.waitForSelector('#rnAuthField:not([hidden])', { timeout: 8000 });
ok(await page.$eval('#rnAuthKey', b => b.classList.contains('on') && !b.disabled),
   'the authentication segment opens on the credential the remote actually uses');
ok(await page.$eval('#rnAuthToken', b => b.disabled),
   '...with the token side disabled while no token is stored');
ok(/No token is stored/.test(await page.$eval('#rnAuthHint', e => e.textContent)),
   '...saying so, rather than leaving a dead button to be poked at');
await page.fill('#rnToken', 'ghp_ExampleTokenValue123');
await page.waitForFunction(() => !document.getElementById('rnAuthToken').disabled,
                           { timeout: 5000 });
ok(true, 'typing a token turns the switch on: setting one and using it is one intention');
await page.click('#rnAuthToken');
ok(await page.$eval('#rnAuthToken', b => b.classList.contains('on'))
   && !await page.$eval('#rnAuthKey', b => b.classList.contains('on')),
   '...and picking it moves the segment without touching either credential');
ok(/stay where they are|stays stored/.test(await page.$eval('#rnAuthHint', e => e.textContent)),
   '...promising in words that switching removes neither');
await page.fill('#rnToken', '');
// Clearing, which is the other half of a stored token: it cannot be shown and
// must not be typed over blind, so the field is closed and this is the way in.
await page.click('#rnCancel');
await page.evaluate(() => renameProject('alpha'));
await page.waitForSelector('#rnAuthField:not([hidden])', { timeout: 8000 });
ok(await page.$eval('#rnTokenClear', b => b.hidden),
   'a project with no token stored is offered nothing to clear');

// The remaining states need a project holding both credentials, which no
// fixture here does — so the answer the dialog was given is set directly and
// the real draw runs against the real DOM. What is being tested is the state
// machine, and it takes exactly this one input.
const authState = (opts, now) => page.evaluate(([o, n]) => {
  rnAuthOpts = o; rnAuthNow = n; rnAuthPick = n; rnClearToken = false;
  document.getElementById('rnToken').value = '';
  rnDrawAuth();
}, [opts, now]);
const seen = () => page.evaluate(() => ({
  closed: document.getElementById('rnToken').disabled,
  clear: !document.getElementById('rnTokenClear').hidden,
  key: document.getElementById('rnAuthKey').disabled,
  token: document.getElementById('rnAuthToken').disabled,
  onKey: document.getElementById('rnAuthKey').classList.contains('on'),
  onToken: document.getElementById('rnAuthToken').classList.contains('on'),
  hint: document.getElementById('rnAuthHint').textContent,
}));

await authState({ now: 'ssh', token: true, ssh: true }, 'ssh');
let v = await seen();
ok(v.closed && v.clear && !v.key && !v.token && v.onKey,
   'a stored token closes the field and offers a way to clear it, both sides live');
await page.click('#rnTokenClear');
v = await seen();
ok(!v.closed && v.token && v.onKey && !v.onToken,
   '...and clearing opens the field, ghosts the token side and puts the pick back on the key');
ok(await page.$eval('#rnTokenClear', b => /Keep the stored token/.test(b.textContent)),
   '...with the way back offered, since nothing has happened to the project yet');

// Only a token, no key: the side that does not exist is the ghosted one, and
// the pick cannot leave the side that does.
await authState({ now: 'https', token: true, ssh: false }, 'https');
v = await seen();
ok(v.closed && v.key && !v.token && v.onToken,
   'with no deploy key the key side is ghosted and the pick stays on the token');
await page.click('#rnTokenClear');
v = await seen();
ok(v.key && v.token && !v.onKey && !v.onToken && !v.closed,
   'clearing the only credential ghosts both sides — there is nothing left to pick');
ok(/cannot push to GitHub/.test(v.hint) && /locally/.test(v.hint),
   '...and says so: the work still happens, it just stays on this box');

// What Claude runs on here, at the bottom of the same dialog. Per project, and
// applied when a session starts rather than typed into a running one — so the
// dialog's job is to say which of those two you are doing.
ok(await page.$eval('#rnTitle', e => e.textContent.trim()) === 'alpha',
   'the dialog is the project\'s settings, not a rename form wearing its name');
ok(await page.$eval('#rnGo', e => e.textContent.trim()) === 'Save',
   '...so its button saves rather than renames');
await page.selectOption('#rnModel', 'sonnet');
ok(!await page.$eval('#rnModel', e => e.disabled)
   && /next time Claude starts/.test(await page.$eval('#rnPrefHint', e => e.textContent)),
   'with no session running it simply applies at the next start');
await page.click('#rnCancel');

// Ghosted where no session can start. Unlike the credential fields above there
// is no typing that brings this back, so the reason is the whole message.
await page.click(`.doc .projtab [data-k="gamma"]`);
await page.waitForFunction(() => (state?.projects || [])
  .some(p => p.name === 'gamma' && p.locked), { timeout: 15000 });
await page.evaluate(() => renameProject('gamma'));
await page.waitForSelector('#rnmodal:not([hidden])');
ok(await page.$eval('#rnModel', e => e.disabled)
   && await page.$eval('#rnEffort', e => e.disabled),
   'a locked project cannot be given a model — no session starts there to have one');
ok(/Locked/.test(await page.$eval('#rnPrefHint', e => e.textContent)),
   '...and says which of the two reasons it is');
await page.click('#rnCancel');
await page.click(`.doc .projtab [data-k="gamma"]`);
await page.waitForFunction(() => !(state?.projects || [])
  .some(p => p.name === 'gamma' && p.locked), { timeout: 15000 });
// Back on alpha's, open, because what follows closes it and moves on.
await page.evaluate(() => renameProject('alpha'));
await page.waitForSelector('#rnmodal:not([hidden])');
await page.click('#rnCancel');
await page.evaluate(() => renameProject('beta'));
await page.waitForSelector('#rnmodal:not([hidden])');
ok(await page.$eval('#rnTokenField', el => el.hidden),
   '...and a read-only project is offered nothing: a credential there grants nothing');
// Back to alpha's dialog: everything below is about the name field, and a
// collision check run against the wrong project's name proves nothing.
await page.click('#rnCancel');
await page.evaluate(() => renameProject('alpha'));
await page.waitForSelector('#rnmodal:not([hidden])');
await page.fill('#rnName', 'gamma');
ok(await page.$eval('#rnName', el => el.classList.contains('bad')),
   '...and a name already taken is marked red before you press anything');
await page.fill('#rnName', 'alpha');
ok(await page.$eval('#rnName', el => !el.classList.contains('bad')),
   '...its own name is not a collision with itself');
await page.click('#rnCancel');
ok(await page.$eval('#rnmodal', el => el.hidden), 'Cancel closes it');

// Deleting: on the full list only, and it moves rather than destroys.
ok(!await page.$('#projects [data-del]'),
   'the sidebar card has no delete — that one is brushed past on a phone');
ok(await page.$('.doc .projtab [data-del]'),
   '...and the Projects tab does');
// The thumbtack went the same way. The card IS the pinned view, so a control
// on it that takes a row off it is a button whose only effect is to remove
// the thing you pressed — and the row it lived on is now one control shorter
// on the crowded side.
ok(!await page.$('#projects [data-p]') && await page.$('.doc .projtab [data-p]'),
   'pinning is the Projects tab\'s, not the card the pins are shown in');
const gone = await api('/api/trash', { name: 'beta' });
ok(gone.status === 200 && gone.body.to === '.trash/beta',
   'deleting names where the files went');
ok(existsSync(`${DIR}/ws/.trash/beta`) && !existsSync(`${DIR}/ws/beta`),
   '...and they are there, moved rather than removed');
// Put it back, then delete again: the second copy is numbered, because the
// first is exactly the one somebody would be trying to recover.
execFileSync('mv', [`${DIR}/ws/.trash/beta`, `${DIR}/ws/beta`]);
execFileSync('mkdir', ['-p', `${DIR}/ws/.trash/beta`]);
const again = await api('/api/trash', { name: 'beta' });
ok(again.status === 200 && again.body.to === '.trash/beta-2',
   'a second delete of the same name is numbered, not an overwrite');
execFileSync('mv', [`${DIR}/ws/.trash/beta-2`, `${DIR}/ws/beta`]);
execFileSync('rm', ['-rf', `${DIR}/ws/.trash`]);

// The command pin and the project pin are different features that spent an
// afternoon sharing four names — /api/pin, _pin, PINS_FILE and setPinned — and
// nothing went red, because pinning a command had no test at all (bug #20).
// This is that test: the two write to their own files and neither can be
// reached through the other's endpoint.
const cmdPin = await api('/api/pin', { name: 'status', pinned: true });
ok(cmdPin.status === 200 && (cmdPin.body.pinned || []).includes('status'),
   'a command can be pinned');
ok(JSON.parse(readFileSync(`${DIR}/state/pinned-commands.json`, 'utf8')).includes('status'),
   '...into pinned-commands.json, which is its own file');
ok(!JSON.parse(readFileSync(`${DIR}/state/pinned-projects.json`, 'utf8')).includes('status'),
   '...and not into the projects one');
ok((await api('/api/pin', { name: 'alpha', pinned: true })).status === 400,
   'a project name is not a command, and the command pin says so');
ok((await api('/api/project-pin', { name: 'status', pinned: true })).status === 400,
   '...and a command name is not a project');
await done(browser);
