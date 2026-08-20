// Sidebar cards: universal collapse with a height tween, header-only
// controls, drag-to-reorder, ▤ reset, doctor's inner fold vs the card fold,
// per-project findings, valid-projects filter, and server-side persistence.
import { launch, newPage, ok, done, ready, doctorFixture, URL, DIR } from './lib.mjs';
import { writeFileSync, readFileSync } from 'node:fs';

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

// Signed out: the offer flips, and signing in opens a terminal, because the
// flow is a URL to open and a code to paste back.
writeFileSync(`${DIR}/auth.json`, readFileSync(`${DIR}/auth-out.json`));
await page.evaluate(() => refresh());
await page.waitForFunction(() => document.getElementById('bSignIn') !== null,
                           { timeout: 25000 });
ok(await page.$('#bSignOut') === null
   && (await page.$eval('#docAuth', e => e.textContent)).includes('not signed in'),
   'signed out, it says so where the verdict is and offers the way in');
const tabsBefore = await page.$$eval('.tab[data-id]', t => t.length);
await page.click('#bSignIn');
await page.waitForFunction(n => document.querySelectorAll('.tab[data-id]').length > n,
                           tabsBefore, { timeout: 15000 });
ok(await page.evaluate(() => tabs.some(t => t.arg === 'login')),
   '...which opens a terminal for it rather than pretending it is one click');

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

ok(page.errors.length === 0, `zero console errors${page.errors.length ? ' — ' + page.errors.join(' | ') : ''}`);
await done(browser);
