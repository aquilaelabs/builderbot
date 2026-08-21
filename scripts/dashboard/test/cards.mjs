// Sidebar cards: universal collapse with a height tween, header-only
// controls, drag-to-reorder, ▤ reset, doctor's inner fold vs the card fold,
// per-project findings, valid-projects filter, and server-side persistence.
import { launch, newPage, ok, done, ready, doctorFixture, tmuxNew, tmuxKill, tmuxFmt,
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
ok(hs.length === 10 && hs.every(h => h.buttons === 0 && h.chev), 'headers are title + chevron only');
ok((await order())[0] === 'doctor', 'doctor is first by default');
ok(await page.$eval('#bDocTog', el => el.textContent.trim() === 'all 3 ok'), 'doctor status row folded green');

// collapse animates, persists across reload
await page.click('.card[data-card="sessions"] h2');
ok(await page.$eval('.card[data-card="sessions"]', el => el.getAnimations().length > 0 && !el.classList.contains('closed')),
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
ok(await page.$eval('#projects #bAll', el => el.textContent.trim()) === 'Show Excluded (1) / Error (1)',
   'the toggle says what it is hiding, by kind');
await page.click('#projects #bAll');
ok(await page.$eval('#projects', el => el.closest('.card').getAnimations().length > 0), 'in-card toggle slides the card');
await page.click('#projects #bAll');

// findings card: per-project counts, valid projects only, plain button
const rows = await page.$$eval('#findingsSum .row', rs => rs.map(r => r.querySelector('.name').textContent.trim()));
ok(rows.join(',') === 'alpha,beta', `findings card lists valid projects only (${rows.join(',')})`);
ok(!(await page.$eval('#cardFindings .macros button', el => el.classList.contains('primary'))), 'report button is not green');

// .bbignore hides a directory from the card entirely — not listed, not
// counted, not folded away under the Excluded/Error toggle either.
const names = await page.$$eval('#projects .name', ns => ns.map(n => n.textContent.trim()));
ok(!names.includes('toolstore'), 'a directory carrying .bbignore is not a project');
await page.click('#projects #bAll');
const all = await page.$$eval('#projects .name', ns => ns.map(n => n.textContent.trim()));
await page.click('#projects #bAll');
ok(!all.includes('toolstore'), '...not even with the error rows shown');

// drag: reorder + slide + persistence; the click ending a drag is not a toggle
const hb = await (await page.$('.card[data-card="runner"] h2')).boundingBox();
const top = await (await page.$('.side .card[data-card]')).boundingBox();
await page.mouse.move(hb.x + 40, hb.y + 12); await page.mouse.down();
await page.mouse.move(hb.x + 40, top.y + 2, { steps: 10 });
const sliding = await page.$eval('.card[data-card="doctor"]', el => el.getAnimations().length > 0);
await page.mouse.up();
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

// The findings report preloads in idle time when a report exists and no
// findings tab is open — so the first click renders from cache instead of
// starting its fetch on the tap.
await page.waitForFunction(() => typeof findings !== 'undefined'
  && findings && !findings.loading && !findings.error, { timeout: 10000 });
ok(await page.evaluate(() => !tabs.some(t => t.kind === 'findings')),
   'the findings report is warmed before any findings tab exists');

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
const tabsBefore = await page.$$eval('.tab[data-id]', t => t.length);
await page.click('#bSignIn');
await page.waitForFunction(n => document.querySelectorAll('.tab[data-id]').length > n,
                           tabsBefore, { timeout: 15000 });
ok(await page.evaluate(() => tabs.some(t => t.arg === 'login')),
   '...which opens a terminal for it rather than pretending it is one click');

// There is no ttyd here, so the terminal itself never connects: the session
// the flow would run in is made by hand, which is all the page ever sees of it.
// Asked for the name back, not merely for the command to succeed: tmux's
// display-message answers 0 with an empty line for a target that is gone.
const alive = n => { try { return tmuxFmt(n, '#{session_name}') === n; } catch { return false; } };
tmuxNew('login', '/tmp');
await page.evaluate(() => refresh());
await page.waitForFunction(() => tabs.some(t => t.arg === 'login' && t.seen), null,
                           { timeout: 25000 });
ok((await page.$$eval('.tab .lbl', ls => ls.map(l => l.textContent.trim())))
     .includes('Claude sign-in'),
   '...named for the flow it runs, not the directory it happens to sit in');
ok((await page.$$eval('#sessions .name', ns => ns.map(n => n.textContent.trim())))
     .includes('Claude sign-in'),
   '...and the sessions list calls it what the tab does');

// And pressing it again starts another flow — which means ending the one that
// is there. Connecting does not: bb-tty attaches to a sign-in session rather
// than replacing it, because ttyd remakes a dropped socket, a phone remakes
// one coming back to the page, and a second browser on the same layout opens
// the same terminal — and a restart in any of those threw away the code the
// person had just gone to fetch. The decision to start over is this button's.
let relogins = 0;
page.on('framenavigated', f => { if (f.url().includes('arg=login')) relogins++; });
await page.click('#bSignIn');
await page.waitForFunction(() => true);
await new Promise(r => setTimeout(r, 1500));
ok(!alive('login'), 'pressing it again ends the flow that was there');
ok(relogins >= 1, '...and reloads the terminal onto a new one');
ok(await page.$$eval('.tab[data-id]', t => t.length) === tabsBefore + 1,
   '...in the tab it already has, rather than a second one');

// The flow ends with its session — the last line says to press enter, and
// that is what pressing it does — and the tab goes with it, rather than
// staying as a dead rectangle that swallows whatever is typed into it.
tmuxNew('login', '/tmp');
await page.evaluate(() => refresh());
await page.waitForFunction(() => tabs.some(t => t.arg === 'login' && t.seen), null,
                           { timeout: 25000 });
tmuxKill('login');
await page.evaluate(() => refresh());
await page.waitForFunction(() => !tabs.some(t => t.arg === 'login'), null,
                           { timeout: 25000 });
ok(true, 'when the flow is over, its tab closes itself');

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

// ---- the sign-in, watched from outside the terminal --------------------
// A phone pasting a hundred characters into a canvas terminal is where this
// falls over: the paste silently does not arrive, the Enter after it does,
// and the flow exchanges an empty code for a 400 that reads like the code was
// wrong. So the URL comes out of the pane to be tapped, and the code goes in
// through a text field. Driven against a stand-in flow — the real one needs a
// browser and somebody's account.
// Signed in wins over a flow still on screen. The sign-in terminal outlives
// the sign-in — it ends by saying to press enter to close it, so a refusal
// can be read rather than vanishing — and the card was asking for a code long
// after the code had worked.
tmuxNew('login', '/tmp');
await page.evaluate(() => refresh());
await new Promise(r => setTimeout(r, 500));
ok(await page.$('#authCode') === null && await page.$('#bSignOut') !== null,
   'a sign-in terminal left open after success does not ask for a code again');
tmuxKill('login');
await page.evaluate(() => refresh());
await page.waitForFunction(() => document.getElementById('bSignOut') !== null,
                           { timeout: 25000 });

// The rest of this needs the container to look signed *out*, which is when
// the code field is the point.
writeFileSync(`${DIR}/auth.json`, readFileSync(`${DIR}/auth-out.json`));
await page.evaluate(() => refresh());
await page.waitForFunction(() => document.getElementById('bSignIn') !== null,
                           { timeout: 25000 });
const CODE = `${DIR}/logincode.txt`;
tmuxNew('login', '/tmp', ['bash', '-c',
  `printf 'If the browser did not open, visit: `
  + `https://claude.com/cai/oauth/authorize?code=true&state=abc\n'; `
  + `printf 'Paste code here if prompted > '; read -r c; printf '%s' "$c" > ${CODE}; sleep 30`]);
await page.evaluate(() => refresh());
await page.waitForFunction(() => document.getElementById('authCode') !== null,
                           { timeout: 25000 });
ok((await page.$eval('#docAuth a', a => a.href)).includes('oauth/authorize'),
   'while signing in, the card carries the link out of the terminal, tappable');
ok(await page.$eval('#docAuth a', a => a.target === '_blank'),
   '...opening away from the dashboard, not over it');

// A code that is not one never reaches a terminal.
const junk = await page.evaluate(async () => {
  const r = await fetch('/api/login-code', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code: 'not a code' }) });
  return r.status;
});
ok(junk === 400, 'a code with a space in it is refused before it goes anywhere');
page.errors = [];

await page.fill('#authCode', 'abcd1234efgh5678#state-9');
await page.click('#bAuthCode');
await page.waitForFunction(() => document.getElementById('authCode')?.value === '',
                           { timeout: 15000 });
await new Promise(r => setTimeout(r, 600));
ok(readFileSync(CODE, 'utf8') === 'abcd1234efgh5678#state-9',
   '...and a real one arrives whole, with the Enter behind it');
// The URL is printed once, near the top, and a phone's terminal is twenty
// lines tall — so it is in the scrollback within seconds. A link derived from
// the visible pane vanishes with it, taking the row and anything typed in.
execFileSync('tmux', ['send-keys', '-t', 'login', '-l', '--', ':']);
for (let i = 0; i < 60; i++)
  execFileSync('tmux', ['send-keys', '-t', 'login', '-l', '--', ' filler']);
execFileSync('tmux', ['send-keys', '-t', 'login', 'Enter']);
await new Promise(r => setTimeout(r, 800));
await page.evaluate(() => refresh());
await new Promise(r => setTimeout(r, 500));
ok((await page.$eval('#docAuth a', a => a.href)).includes('oauth/authorize'),
   'the link survives the URL scrolling out of the visible pane');

// And what is half-typed survives a repaint, however the repaint was caused.
await page.fill('#authCode', 'half-typed-code');
await page.evaluate(() => { drawAuth(); drawAuth(); });
ok(await page.$eval('#authCode', i => i.value) === 'half-typed-code',
   '...as does whatever is in the field');
await page.fill('#authCode', '');

// Coming back from the background is the moment all of this happens at once:
// the phone hid the page while the sign-in page was open in another tab. The
// tab has to be there to survive, so put one back — the earlier block ended
// with the flow closing itself and taking its tab.
await page.evaluate(() => openTab({kind: 'term', arg: 'login', label: 'Claude sign-in'}));
await page.waitForFunction(() => tabs.some(t => t.arg === 'login'), null,
                           { timeout: 10000 });
const other = await browser.newPage();
await other.goto('about:blank');
await other.bringToFront();
await new Promise(r => setTimeout(r, 3600));   // past the reattach threshold
await page.bringToFront();
await page.waitForFunction(() => document.visibilityState === 'visible',
                           { timeout: 10000 });
await page.evaluate(() => refresh());
await new Promise(r => setTimeout(r, 800));
await other.close();
ok(await page.$('#authCode') !== null
   && (await page.$eval('#docAuth a', a => a.href)).includes('oauth/authorize'),
   'coming back from the background leaves the link and the field where they were');
ok(await page.evaluate(() => tabs.some(t => t.arg === 'login')),
   '...and the sign-in tab with them');

tmuxKill('login');
await page.evaluate(() => refresh());
await page.waitForFunction(() => document.getElementById('authCode') === null,
                           { timeout: 25000 });
ok(true, 'and the field goes when the sign-in does');

// ttyd reconnects a dropped socket after five seconds, and the socket drops
// when the flow ends — so "press enter to close this terminal" used to end
// the session, ttyd came back, and bb-tty started another sign-in. The tab
// could never close, and closing the terminal quietly began a new OAuth flow.
writeFileSync(`${DIR}/login-finished`, '');
await page.evaluate(() => refresh());
await new Promise(r => setTimeout(r, 400));
ok(existsSync(`${DIR}/login-finished`),
   'a finished flow leaves a marker, so a reconnect is not read as a request for another');
// Sign in is the one thing that means start over, so it is what clears it.
await page.evaluate(async () => {
  await fetch('/api/signin', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: '{}' });
});
ok(!existsSync(`${DIR}/login-finished`),
   '...and pressing Sign in clears it, which is what makes the button mean that');
writeFileSync(`${DIR}/auth.json`, readFileSync(`${DIR}/auth-in.json`));
await page.evaluate(() => refresh());

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
