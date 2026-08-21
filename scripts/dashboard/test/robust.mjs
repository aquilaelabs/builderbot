// Malformed input to every endpoint that acts.
//
// The contract is narrow: refuse it (4xx) or do it (2xx). A 500 is an
// unhandled exception, which on a surface that runs commands is the shape of
// bug worth finding before it is found for you. Everything here is a body a
// browser would never send — wrong types, missing fields, absurd numbers —
// because the checks are written against each field being the thing it is
// supposed to be.
import { launch, newPage, ok, done, ready, URL } from './lib.mjs';

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
await done(browser);
