// Malformed input to every endpoint that acts.
//
// The contract is narrow: refuse it (4xx) or do it (2xx). A 500 is an
// unhandled exception, which on a surface that runs commands is the shape of
// bug worth finding before it is found for you. Everything here is a body a
// browser would never send — wrong types, missing fields, absurd numbers —
// because the checks are written against each field being the thing it is
// supposed to be.
import { launch, newPage, ok, done, ready, URL } from './lib.mjs';

// ---- the app's own files carry a validator --------------------------------
// index.html IS the application, and it went out with no ETag and no cache
// directive at all — so whether a phone noticed a container update was left
// to the browser's heuristics, and the failure is silent: yesterday's page
// against today's server, with nothing on screen admitting it. `no-cache`
// means "ask me first", so the usual answer is a 304 of a few bytes.
{
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64') };
  for (const path of ['/', '/tab-nodes.js']){
    const r = await fetch(URL.replace(/\/$/, '') + path, { headers: H });
    const tag = r.headers.get('etag');
    ok(r.status === 200 && !!tag && /no-cache/.test(r.headers.get('cache-control') || ''),
       `${path} is served with a validator and asked to be revalidated (${
         tag || 'no etag'}, ${r.headers.get('cache-control') || 'no directive'})`);
    const again = await fetch(URL.replace(/\/$/, '') + path,
                              { headers: { ...H, 'If-None-Match': tag } });
    ok(again.status === 304, `...and an unchanged ${path} comes back 304 (${again.status})`);
  }
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
  cases.push(['/api/todo', { project: v, action: 'add', text: 'x' }]);
  cases.push(['/api/todo', { project: 'alpha', action: 'add', text: v }]);
  cases.push(['/api/todo', { project: 'alpha', action: 'add', text: 'x', steps: v }]);
  cases.push(['/api/todo', { project: 'alpha', action: 'send', id: v }]);
  cases.push(['/api/todo', { project: 'alpha', action: 'send', id: 1, step: v }]);
  cases.push(['/api/todo', { project: 'alpha', action: 'move', id: 1, step: v, dir: 1 }]);
  cases.push(['/api/todo', { project: 'alpha', action: 'move', id: 1, dir: v }]);
  cases.push(['/api/todo', { project: 'alpha', action: 'cross', id: v, on: v }]);
  cases.push(['/api/todo', { project: 'alpha', action: 'remove', id: 1, step: v }]);
  cases.push(['/api/todo', { project: 'alpha', action: 'add-step', id: v, text: 'x' }]);
  cases.push(['/api/todo', { project: 'alpha', action: v }]);
  cases.push(['/api/memory', { project: v, action: 'save', file: 'MEMORY.md', text: 'x' }]);
  cases.push(['/api/memory', { project: 'alpha', action: 'save', file: v, text: 'x' }]);
  cases.push(['/api/memory', { project: 'alpha', action: 'delete', file: v }]);
  cases.push(['/api/login-code', { code: v }]);
  cases.push(['/api/project-job', { action: v }]);
  cases.push(['/api/signout', { anything: v }]);
}
cases.push(['/api/todo', {}]);
cases.push(['/api/memory', {}]);
cases.push(['/api/login-code', {}]);
cases.push(['/api/signin', {}]);

const broke = [];
for (const [path, body] of cases){
  const r = await post(path, body);
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
  for (const p of ['/api/memory', '/api/todo']){
    const s = await page.evaluate(async u => (await fetch(u)).status, p + q);
    if (s >= 500) badGet.push(p + q + ' -> ' + s);
  }
ok(badGet.length === 0,
   `and neither did ${gets.length * 2} malformed queries${
     badGet.length ? ': ' + badGet.join(', ') : ''}`);

// One status poll must not cost a node runtime. The auth check is 357MB and
// 0.68s, and it used to run once per request while a sign-in was open — so a
// phone, a desktop and a preload polling together were a gigabyte of Node and
// a dashboard that had stopped answering.
const t0 = Date.now();
await page.evaluate(async () => {
  await Promise.all(Array.from({length: 8}, () => fetch('/api/status')));
});
const took = Date.now() - t0;
ok(took < 6000, `eight status polls at once stay quick (${took}ms)`);

page.errors = [];
ok(true, 'the console errors above are the refusals themselves');
// ---- a poll that cannot land says so, rather than sitting on "loading…" ----
// The operator hit a dashboard where some cards had drawn and the rest were
// still on their initial text, with a red logo and nothing else to read. Red
// on its own does not say "error", so it reads as a hung page — and the two
// want telling apart before anything else can be diagnosed.
await page.route('**/api/status*', r => r.abort());
await page.evaluate(() => refresh());
await page.evaluate(() => refresh());
await page.waitForTimeout(300);
const dead = await page.evaluate(() => ({
  red: !!document.getElementById('dot')?.classList.contains('off'),
  title: document.getElementById('dot')?.getAttribute('title') || '',
  fails: pollFails,
  loading: [...document.querySelectorAll('.card .loading')].map(e => e.textContent),
}));
ok(dead.red && /polls failed in a row/.test(dead.title) && dead.fails >= 2,
   `a failing poll says so on the light, with the count and the reason (${dead.title.slice(0, 80)})`);
// ...and the case that actually bit: a page whose FIRST poll never lands, so
// no card ever draws and every one of them keeps its initial text.
await page.reload({ waitUntil: 'domcontentloaded' });
await page.evaluate(() => refresh());
await page.evaluate(() => refresh());
await page.waitForTimeout(300);
const cold = await page.evaluate(() =>
  [...document.querySelectorAll('.card .loading')].map(e => e.textContent));
ok(cold.length > 0 && cold.every(t => /not reaching the container/.test(t)),
   `...and on a page whose first poll never landed, every card says why rather than "loading…" (${
     cold.length} card(s): ${JSON.stringify(cold[0] || '')})`);
await page.unroute('**/api/status*');
await page.evaluate(() => refresh());
await page.waitForTimeout(300);
ok(await page.evaluate(() => !document.getElementById('dot').classList.contains('off')
                             && !document.getElementById('dot').getAttribute('title')
                             && pollFails === 0),
   '...and it all clears the moment a poll lands again');

// ---- one card's draw failing must not strand the rest (bug #44) ----
// The other shape of the same report: the container answered, one draw threw
// on the payload, and every card after it kept its initial text under a red
// light — which the words above would then have blamed on the network. The
// failed card says so in its own body; the others draw; the light stays on.
await page.evaluate(() => {
  window.__drawRunner = drawRunner;
  drawRunner = () => { throw new Error('runner draw boom'); };
});
await page.evaluate(() => refresh());
await page.waitForTimeout(300);
const partial = await page.evaluate(() => ({
  runner: document.getElementById('runner').textContent.trim(),
  projectsWaiting: !!document.querySelector('#projects .loading'),
  doctorWaiting: /first run pending/.test(document.getElementById('doctor').textContent),
  red: document.getElementById('dot').classList.contains('off'),
}));
ok(/not drawn/.test(partial.runner) && /runner draw boom/.test(partial.runner),
   `a card whose draw threw says so in its own body (${JSON.stringify(partial.runner.slice(0, 60))})`);
ok(!partial.projectsWaiting && !partial.doctorWaiting && !partial.red,
   `...and the cards after it still draw, under a light that stays on (${JSON.stringify(partial)})`);
ok(page.errors.some(t => /runner draw boom/.test(t)),
   '...while the error itself still reaches the console');
page.errors = [];
await page.evaluate(() => { drawRunner = window.__drawRunner; });
await page.evaluate(() => refresh());
await page.waitForTimeout(300);
ok(await page.evaluate(() => !/not drawn/.test(document.getElementById('runner').textContent)),
   '...and the card recovers on the next poll that draws');
// ...and when the page trips BEFORE the draws — on the payload, not on the
// fetch — the light and the placeholders blame this page, not the network.
// The status answer is held for half a second so the stub is in place
// before the page's own first poll comes back — the placeholders have to be
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
  title: document.getElementById('dot').getAttribute('title') || '',
  loading: [...document.querySelectorAll('.card .loading')].map(e => e.textContent),
}));
ok(/fails on its answer/.test(tripped.title) && /layout boom/.test(tripped.title)
   && tripped.loading.length > 0 && tripped.loading.every(t => /fails on its answer/.test(t)),
   `a page that fails on the container's answer says that, not "not reaching the container" (${
     tripped.title.slice(0, 70)})`);
page.errors = [];

await done(browser);
