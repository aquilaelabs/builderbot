// Malformed input to every endpoint that acts.
//
// The contract is narrow: refuse it (4xx) or do it (2xx). A 500 is an
// unhandled exception, which on a surface that runs commands is the shape of
// bug worth finding before it is found for you. Everything here is a body a
// browser would never send (wrong types, missing fields, absurd numbers),
// because the checks are written against each field being the thing it is
// supposed to be.
import { launch, newPage, ok, done, ready, sleep, patience, URL } from './lib.mjs';

// ---- the app's own files carry a validator --------------------------------
// index.html IS the application, and it went out with no ETag and no cache
// directive at all, so whether a phone noticed a container update was left
// to the browser's heuristics, and the failure is silent: yesterday's page
// against today's server, with nothing on screen admitting it. `no-cache`
// means "ask me first", so the usual answer is a 304 of a few bytes.
// Over node:http, not fetch. Node's fetch (undici) asserts inside itself,
// assert(!this.paused) in Parser.finish, when a large body is still being
// read as this HTTP/1.0 server closes the connection it answered on; it
// crashed this file in whole runs and then on every run once the page's body
// was read to its end. node:http has no such path.
import http from 'node:http';
const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
const get = (path, extra = {}) => new Promise((resolve, reject) => {
  const u = new globalThis.URL(URL.replace(/\/$/, '') + path);
  http.get({ host: u.hostname, port: u.port, path: u.pathname + u.search, headers: { ...H, ...extra } }, res => {
    const chunks = [];
    res.on('data', c => chunks.push(c));
    res.on('end', () => resolve({ status: res.statusCode, tag: res.headers.etag,
      cache: res.headers['cache-control'] || '', type: res.headers['content-type'] || '',
      text: Buffer.concat(chunks).toString('utf8') }));
  }).on('error', reject);
});
{
  for (const path of ['/', '/tab-nodes.js']){
    const r = await get(path);
    ok(r.status === 200 && !!r.tag && /no-cache/.test(r.cache),
       `${path} is served with a validator and asked to be revalidated (${r.tag || 'no etag'}, ${r.cache || 'no directive'})`);
    const again = await get(path, { 'If-None-Match': r.tag });
    ok(again.status === 304, `...and an unchanged ${path} comes back 304 (${again.status})`);
  }
}
// The page names each of its scripts with that script's version, and its
// own tag covers them: a phone left on the page across an update reloaded
// into the old Global rules dialog, and a URL that moves with the file
// cannot be answered from a copy made before it.
{
  const g0 = await get('/');
  // ...and names its integrity after the version (R158 step 4).
  const v = g0.text.match(/<script data-cfasync="false" src="nb-history\.js\?v=([0-9a-f]+-[0-9a-f]+)" integrity="sha384-[A-Za-z0-9+/=]+">/);
  ok(!!v && !/<script[^>]* src="(tab|nb)-[a-z-]+\.js">/.test(g0.text),
     `every tab and notebook script is named with its version (${v ? v[1] : 'unversioned'})`);
  // ...and every script runs as written: Cloudflare's Rocket Loader leaves
  // one marked data-cfasync="false" alone (B138).
  ok(!/<script(?![^>]*data-cfasync="false")/.test(g0.text),
     'every script on the page is marked for Rocket Loader to leave it as it is');
  const served = new globalThis.URL('../nb-history.js', import.meta.url).pathname;
  const { utimesSync } = await import('node:fs');
  const later = new Date(Date.now() + 5000);
  utimesSync(served, later, later);
  const g1 = await get('/');
  const v1 = g1.text.match(/<script data-cfasync="false" src="nb-history\.js\?v=([0-9a-f]+-[0-9a-f]+)">/);
  ok(v1 && v && v1[1] !== v[1] && g1.tag !== g0.tag,
     `...and a script that changes gets a new name and a new page tag, the page itself untouched (${v1?.[1]}, ${g1.tag !== g0.tag})`);
  const js = await get('/nb-history.js?v=' + (v1 ? v1[1] : ''));
  ok(js.status === 200 && /javascript/.test(js.type),
     `...which the server answers under that name (${js.status})`);
}

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 800 } });
await page.goto(URL);
await ready(page);

const post = (path, body) => page.evaluate(async ([p, b]) => {
  const r = await fetch(p, { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  let text = '';
  try { text = JSON.stringify(await r.json()).slice(0, 120); } catch { text = '<not json>'; }
  return { status: r.status, text };
}, [path, body]);

const ODD = [null, 0, -1, 1e9, '', 'x', [], {}, true, '../etc', ' ', 'a'.repeat(3000)];

const cases = [];
for (const v of ODD){
  cases.push(['/api/roadmap', { project: v, action: 'add', text: 'x' }]);
  cases.push(['/api/roadmap', { project: 'alpha', action: 'add', text: v }]);
  cases.push(['/api/roadmap', { project: 'alpha', action: 'add', text: 'x', steps: v }]);
  cases.push(['/api/roadmap', { project: 'alpha', action: 'send', id: v }]);
  cases.push(['/api/roadmap', { project: 'alpha', action: 'send', id: 1, step: v }]);
  cases.push(['/api/roadmap', { project: 'alpha', action: 'move', id: 1, step: v, dir: 1 }]);
  cases.push(['/api/roadmap', { project: 'alpha', action: 'move', id: 1, dir: v }]);
  cases.push(['/api/roadmap', { project: 'alpha', action: 'cross', id: v, on: v }]);
  cases.push(['/api/roadmap', { project: 'alpha', action: 'remove', id: 1, step: v }]);
  cases.push(['/api/roadmap', { project: 'alpha', action: 'add-step', id: v, text: 'x' }]);
  cases.push(['/api/roadmap', { project: 'alpha', action: v }]);
  cases.push(['/api/memory', { project: v, action: 'save', file: 'MEMORY.md', text: 'x' }]);
  cases.push(['/api/memory', { project: 'alpha', action: 'save', file: v, text: 'x' }]);
  cases.push(['/api/memory', { project: 'alpha', action: 'delete', file: v }]);
  cases.push(['/api/login-code', { code: v }]);
  cases.push(['/api/project-job', { action: v }]);
  cases.push(['/api/signout', { node: v }]);
  cases.push(['/api/signin', { node: v }]);
}
cases.push(['/api/roadmap', {}]);
cases.push(['/api/memory', {}]);
cases.push(['/api/login-code', {}]);
cases.push(['/api/signin', {}]);

const broke = [];
// Eight at a time: the server threads its requests, and one at a time was
// fourteen seconds of waiting on a question whose cases are independent.
for (let i = 0; i < cases.length; i += 8){
  const got = await Promise.all(cases.slice(i, i + 8).map(async ([path, body]) => [path, body, await post(path, body)]));
  for (const [path, body, r] of got)
    if (r.status >= 500) broke.push(`${path} ${JSON.stringify(body).slice(0, 70)} -> ${r.status} ${r.text}`);
}
ok(broke.length === 0,
   `${cases.length} malformed bodies, none crashed an endpoint${
     broke.length ? '\n     ' + broke.slice(0, 6).join('\n     ') : ''}`);

// ...and the same for the reads, which take their arguments from the query.
const gets = ['', '?project=', '?project=nosuch', '?project=../etc',
              '?project=' + 'a'.repeat(3000), '?project=a&project=b'];
const badGet = [];
for (const q of gets)
  for (const p of ['/api/memory', '/api/roadmap']){
    const s = await page.evaluate(async u => (await fetch(u)).status, p + q);
    if (s >= 500) badGet.push(p + q + ' -> ' + s);
  }
ok(badGet.length === 0,
   `and neither did ${gets.length * 2} malformed queries${
     badGet.length ? ': ' + badGet.join(', ') : ''}`);

// One status poll must not cost a node runtime. The auth check is 357MB and
// 0.68s, and it used to run once per request while a sign-in was open, so a
// phone, a desktop and a preload polling together were a gigabyte of Node and
// a dashboard that had stopped answering.
// Timed up to three times, a few seconds apart, and the quickest kept
// (B517): one burst in a whole eight-worker run took 8.8s at a load past the
// core count with nothing wrong, and a cost that is the code's is paid on
// every try, where a busy moment of the box's is not. The bar stretches with
// the harness's patience as every wait does.
const bar = patience(6000), tries = [];
for (let i = 0; i < 3; i++){
  if (i) await sleep(3000);
  const t0 = Date.now();
  await page.evaluate(async () => {
    await Promise.all(Array.from({length: 8}, () => fetch('/api/status')));
  });
  tries.push(Date.now() - t0);
  if (tries[i] < bar) break;
}
const took = Math.min(...tries);
ok(took < bar, `eight status polls at once stay quick (${tries.join('ms, ')}ms; under ${bar}ms)`);

page.errors = [];
ok(true, 'the console errors above are the refusals themselves');
// ---- a poll that cannot land says so, rather than sitting on "loading…" ----
// The operator hit a dashboard where some cards had drawn and the rest were
// still on their initial text, with a red logo and nothing else to read. Red
// on its own does not say "error", so it reads as a hung page, and the two
// want telling apart before anything else can be diagnosed.
await page.route('**/api/status*', r => r.abort());
// Two failures in a row, however the page's own poll interleaves: a
// refresh() asked while another is out only queues behind it, so asking
// twice could count once (B146). Asked until it has counted two, bounded.
// Bounded by time, not by a count: a status poll this page sent before the
// route went in can still be out (a status walks every project's git, and
// the checks above just made it slow), and while it is, refresh() only queues
// and returns at once, so forty asks spent themselves in milliseconds and the
// late poll then landed and cleared the light (B176, 19 Sep).
for (const until = Date.now() + 20000; Date.now() < until
     && await page.evaluate(async () => { await refresh(); return pollFails; }) < 2;) await sleep(100);
const dead = await page.evaluate(() => ({
  red: !!document.getElementById('dot')?.classList.contains('off'),
  title: document.getElementById('dot')?.getAttribute('aria-label') || '',
  line: document.getElementById('pollWhy')?.hidden ? '' : document.getElementById('pollWhy')?.textContent || '',
  fails: pollFails,
  loading: [...document.querySelectorAll('main .loading')].map(e => e.textContent),
}));
ok(dead.red && /polls failed in a row/.test(dead.line) && dead.line === dead.title && dead.fails >= 2,
   `a failing poll says so in a line under the header, with the count and the reason, and the light is named by it (${dead.line.slice(0, 80)})`);
// ...and the case that actually bit: a page whose FIRST poll never lands, so
// nothing ever draws and every placeholder keeps its initial text.
await page.reload({ waitUntil: 'domcontentloaded' });
// Waiting, the page is the shape of what is coming (R218 step 15): the first
// pane's placeholder is shapes, and no placeholder on show is a line of words.
const waiting = await page.evaluate(() => {
  const shown = [...document.querySelectorAll('main .loading')].filter(e => e.getClientRects().length);
  return { shapes: document.querySelectorAll('#pane0 .skel :is(.sk-b, .skv), #pane0 .skpcard .skv').length,
           words: shown.filter(e => !e.classList.contains('skel')).map(e => e.textContent.trim().slice(0, 30)),
           said: document.querySelector('#pane0 .skel .sk-said')?.textContent || '' };
});
ok(waiting.shapes > 0 && waiting.words.length === 0 && waiting.said === 'loading…',
   `before the first snapshot the page waits with shapes, not words, and still says loading to a screen reader (${JSON.stringify(waiting)})`);
await page.evaluate(() => refresh());
await page.evaluate(() => refresh());
await page.waitForTimeout(300);
const cold = await page.evaluate(() =>
  [...document.querySelectorAll('main .loading')].map(e => e.textContent));
ok(cold.length > 0 && cold.every(t => /not reaching the container/.test(t)),
   `...and on a page whose first poll never landed, every placeholder says why rather than "loading…" (${
     cold.length}: ${JSON.stringify(cold[0] || '')})`);
const coldShape = await page.evaluate(() => [...document.querySelectorAll('main .loading.warn')]
  .filter(e => e.querySelector('.sk-b') || getComputedStyle(e).display !== 'block').length);
ok(coldShape === 0, `...a line of words where the shapes stood, nothing of them left (${coldShape} still shaped)`);
await page.unroute('**/api/status*');
await page.evaluate(() => refresh());
await page.waitForTimeout(300);
ok(await page.evaluate(() => !document.getElementById('dot').classList.contains('off')
                             && !document.getElementById('dot').getAttribute('aria-label')
                             && document.getElementById('pollWhy').hidden
                             && pollFails === 0),
   '...and it all clears the moment a poll lands again');

// ---- a page waits as itself (R218 step 16) ---------------------------------
// What never changes on a page is drawn while its data is on the way, and
// only the values shimmer: the Users page with its accounts on the way shows
// its list beside the picked account's settings, their labels drawn and the
// values shimmering, inert so nothing is typed into a form the real one
// replaces.
{
  await page.evaluate(() => { location.hash = '#/people/users'; });
  await page.waitForFunction(() => tabOf(panes[0])?.kind === 'users' && document.querySelector('.doc.on .userstab [data-upick]'), null, { timeout: 15000 });
  await page.route('**/api/users*', () => {});
  const t = await page.evaluate(() => { usersList = null; renderUsersInto(0);
    const tpl = document.querySelector('.doc.on .skt');
    return { inert: !!tpl?.inert, split: !!tpl?.querySelector('.rsplit > .rlist + .rdetail'),
             labels: [...(tpl?.querySelectorAll('.rdetail .lbl') || [])].map(x => x.textContent.trim()),
             values: tpl?.querySelectorAll('.skv').length || 0, waiting: !!tpl?.classList.contains('loading') }; });
  ok(t.inert && t.waiting && t.split && t.labels.includes('Account name') && t.labels.includes('Roles and projects') && t.values > 0,
     `a page waiting on its data draws its own template, its values shimmering, inert until they land (${JSON.stringify(t)})`);
  await page.unroute('**/api/users*');
  await page.evaluate(() => { usersList = null; loadUsers(); });
  await page.waitForFunction(() => !document.querySelector('.doc.on .skt') && document.querySelector('.doc.on .userstab [data-upick]'), null, { timeout: 15000 });
  ok(true, '...and the real page replaces it once they land');
}

// ---- one part's draw failing must not strand the rest (bug #44) ----
// The other shape of the same report: the container answered, one draw threw
// on the payload, and every part after it kept its initial text under a red
// light, which the words above would then have blamed on the network. The
// failed part says so in its own body; the others draw; the light stays on.
await page.evaluate(() => {
  window.__drawDoctor = drawDoctor;
  drawDoctor = () => { throw new Error('doctor draw boom'); };
});
await page.evaluate(() => refresh());
await page.waitForTimeout(300);
const partial = await page.evaluate(() => ({
  doctor: document.getElementById('doctor').textContent.trim(),
  projectsWaiting: !!document.querySelector('.pgrid .loading'),
  commandsWaiting: !!document.querySelector('#commands .loading'),
  red: document.getElementById('dot').classList.contains('off'),
}));
ok(/not drawn/.test(partial.doctor) && /doctor draw boom/.test(partial.doctor),
   `a part whose draw threw says so in its own body (${JSON.stringify(partial.doctor.slice(0, 60))})`);
ok(!partial.projectsWaiting && !partial.commandsWaiting && !partial.red,
   `...and the parts after it still draw, under a light that stays on (${JSON.stringify(partial)})`);
ok(page.errors.some(t => /doctor draw boom/.test(t)),
   '...while the error itself still reaches the console');
page.errors = [];
await page.evaluate(() => { drawDoctor = window.__drawDoctor; });
await page.evaluate(() => refresh());
await page.waitForTimeout(300);
ok(await page.evaluate(() => !/not drawn/.test(document.getElementById('doctor').textContent)),
   '...and the part recovers on the next poll that draws');
// ...and when the page trips BEFORE the draws (on the payload, not on the
// fetch), the light and the placeholders blame this page, not the network.
// The status answer is held for half a second so the stub is in place
// before the page's own first poll comes back: the placeholders have to be
// on screen for the words on them to matter.
await page.route('**/api/status*', async r => {
  await new Promise(res => setTimeout(res, 500)); await r.continue(); });
await page.reload({ waitUntil: 'domcontentloaded' });
await page.evaluate(() => { adoptLayout = () => { throw new Error('layout boom'); }; });
await page.evaluate(() => refresh());
await page.evaluate(() => refresh());
await page.waitForFunction(() => pollFails >= 2, null, { timeout: 5000 });
await page.unroute('**/api/status*');
const tripped = await page.evaluate(() => ({
  title: document.getElementById('pollWhy').textContent || '',
  loading: [...document.querySelectorAll('main .loading')].map(e => e.textContent),
}));
ok(/fails on its answer/.test(tripped.title) && /layout boom/.test(tripped.title)
   && tripped.loading.length > 0 && tripped.loading.every(t => /could not read the server's answer/.test(t)),
   `a page that fails on the container's answer says that, not "not reaching the container" (${
     tripped.title.slice(0, 70)})`);
page.errors = [];

await done(browser);
