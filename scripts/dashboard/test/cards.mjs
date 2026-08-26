// Sidebar cards: universal collapse with a height tween, header-only
// controls, drag-to-reorder, ▤ reset, doctor's inner fold vs the card fold,
// per-project findings, valid-projects filter, and server-side persistence.
import { launch, newPage, ok, done, ready, doctorFixture, animatedDuring, tmuxNew, tmuxKill, tmuxFmt,
         URL, DIR } from './lib.mjs';
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
ok(hs.length === 12 && hs.every(h => h.buttons === 0 && h.chev),
   `headers are title + chevron only (${hs.length} cards)`);
ok((await order())[0] === 'doctor', 'doctor is first by default');
ok(await page.$eval('#bDocTog', el => el.textContent.trim() === 'all 3 ok'), 'doctor status row folded green');

// collapse animates, persists across reload
const collapsed = await animatedDuring(page,
  () => page.click('.card[data-card="sessions"] h2'));
ok(collapsed.some(k => k.includes('sessions'))
   && !await page.$eval('.card[data-card="sessions"]', el => el.classList.contains('closed')),
   'collapse runs a height tween before the class lands');
await page.waitForFunction(() => document.querySelector('.card[data-card="sessions"]').classList.contains('closed'));
await page.reload(); await ready(page);
ok(await page.$eval('.card[data-card="sessions"]', el => el.classList.contains('closed')), 'collapsed state survives a reload');

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

// ▤ reset
await page.click('#bCards');
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
await page.evaluate(() => refresh());
await page.waitForFunction(() => document.getElementById('bSignIn') !== null,
                           { timeout: 25000 });
ok(await page.$('#bSignOut') === null
   && (await page.$eval('#docAuth', e => e.textContent)).includes('not signed in'),
   'signed out, it says so where the verdict is and offers the way in');
// ...and nothing offers to start a conversation that cannot start.
ok(await page.$$eval('#projects [data-c]', bs => bs.length > 0 && bs.every(b => b.disabled)),
   '...and every project\'s Claude button goes with it');

// And back: the stub's logout rewrites its own fixture, so this proves the
// button reaches the command without going near anybody's credentials.
writeFileSync(`${DIR}/auth.json`, readFileSync(`${DIR}/auth-in.json`));
await page.evaluate(() => refresh());
await page.waitForFunction(() => document.getElementById('bSignOut') !== null,
                           { timeout: 25000 });
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
await page.evaluate(() => refresh());
await page.waitForFunction(() => document.getElementById('bSignIn') !== null,
                           { timeout: 25000 });
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

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);
await done(browser);
