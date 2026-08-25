// The notebook's Artifacts view: what a project has built, from its dist/.
// The convention IS the feature — the tab lists dist/ and nothing else, so a
// build worth keeping has to be copied there, and an empty tab says that.
import { launch, newPage, ok, done, ready, URL, DIR } from './lib.mjs';
import { mkdirSync, writeFileSync, symlinkSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

// alpha ships an APK and an XPI; the XPI is a real zip with a manifest, since
// pushing one means unpacking it and handing the directory to web-ext.
mkdirSync(`${DIR}/ws/alpha/dist/android`, { recursive: true });
writeFileSync(`${DIR}/ws/alpha/dist/android/streamlift-1.2.apk`, 'not-really-an-apk');
const stage = `${DIR}/xpi-stage`;
mkdirSync(stage, { recursive: true });
writeFileSync(`${stage}/manifest.json`,
  JSON.stringify({ manifest_version: 2, name: 'Companion', version: '0.2.0' }));
writeFileSync(`${stage}/background.js`, 'console.log(1);');
execFileSync('zip', ['-qj', `${DIR}/ws/alpha/dist/companion-0.2.0.xpi`,
  `${stage}/manifest.json`, `${stage}/background.js`]);
// ...and a secret outside dist/, wired in by symlink: the download endpoint
// must refuse to follow it out.
writeFileSync(`${DIR}/ws/alpha/secret.txt`, 'not yours');
symlinkSync(`${DIR}/ws/alpha/secret.txt`, `${DIR}/ws/alpha/dist/leak.txt`);

const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);
const row = n => `#projects .row:has(.name:text-is("${n}"))`;
await page.click(`${row('alpha')} [data-m]`);
await page.waitForSelector('#todoList, .nb', { timeout: 20000 });
await page.click('.nbtabs [data-v="artifacts"]:visible');
await page.waitForSelector('.artrow', { timeout: 15000 });

// ---- the listing -----------------------------------------------------------
const names = await page.$$eval('.artrow b', bs => bs.map(b => b.textContent));
ok(names.includes('streamlift-1.2.apk') && names.includes('companion-0.2.0.xpi'),
   `dist/ is listed, subdirectories included (${names.join(', ')})`);
ok(await page.$$eval('.artrow .pill', ps =>
     ps.some(p => p.textContent === 'apk') && ps.some(p => p.textContent === 'xpi')),
   '...each labeled by what it is');
const acts = await page.$$eval('.artrow', rs => rs.map(r => ({
  name: r.querySelector('b')?.textContent,
  push: !!r.querySelector('[data-artpush]'),
  dl: !!r.querySelector('a.btn') })));
ok(acts.find(a => a.name === 'companion-0.2.0.xpi').push
   && !acts.find(a => a.name === 'streamlift-1.2.apk').push,
   'Push is offered for the extension and not for the APK');
ok(acts.every(a => a.dl), '...and everything can be downloaded');

// ---- the download, and what it refuses -------------------------------------
const get = p => page.evaluate(async u => {
  const r = await fetch(u);
  return { status: r.status, disp: r.headers.get('content-disposition') || '' };
}, p);
const dl = await get('/api/artifact?project=alpha&path=dist/android/streamlift-1.2.apk');
ok(dl.status === 200 && dl.disp.includes('streamlift-1.2.apk'),
   'the download hands the file over as an attachment');
ok((await get('/api/artifact?project=alpha&path=dist/../CLAUDE.md')).status === 404,
   'a path that climbs out of dist/ is refused');
ok((await get('/api/artifact?project=alpha&path=dist/leak.txt')).status === 404,
   '...and so is a symlink pointing out of it — dist/ must not become a file server');
page.errors = [];

// ---- pushing the extension -------------------------------------------------
// The stubbed web-ext installs and sits there like the real one; the point
// here is the lifecycle and that the .xpi round-trips through unpacking.
await page.click('[data-artpush]');
await page.waitForFunction(() => /live/.test(
  document.querySelector('.artrow.job')?.textContent || ''), null, { timeout: 20000 });
ok(true, 'Push unpacks the .xpi and goes live once the add-on is on the phone');
ok(/temporary/.test(await page.$eval('.artrow.job', el => el.textContent)),
   '...saying out loud that the install is temporary');
ok(await page.$eval('[data-artpush]', b => b.disabled),
   '...and a second push cannot start on top of the first');
ok(/not.*auto-push|do not auto-push/i.test(
     await page.$eval('.artrow.job', el => el.textContent)),
   '...and that nothing auto-pushes — a push is a decision, made each time');
// The identical build into a live session installs nothing, so it is said
// rather than done. The button is disabled in the UI; the API is the one that
// has to hold the line.
const rePush = await page.evaluate(async () => {
  const r = await fetch('/api/artifacts', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'push', project: 'alpha',
                           path: 'dist/companion-0.2.0.xpi' }) });
  return { status: r.status, body: await r.json() };
});
ok(rePush.status === 400 && /already live/.test(rePush.body.error),
   'pushing the identical build into a live session is said, not done');
await page.click('#artStop');
await page.waitForFunction(() => !document.querySelector('.artrow.job'),
                           null, { timeout: 20000 });
ok(true, 'Stop ends it');

// ---- what the POST refuses -------------------------------------------------
const post = body => page.evaluate(async b => {
  const r = await fetch('/api/artifacts', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) });
  return { status: r.status, body: await r.json() };
}, body);
for (const [what, body] of [
  ['pushing the APK, which is not an extension', { action: 'push', project: 'alpha', path: 'dist/android/streamlift-1.2.apk' }],
  ['pushing a path outside dist/', { action: 'push', project: 'alpha', path: '../beta/x.xpi' }],
  ['a project that does not exist', { action: 'push', project: 'nosuch', path: 'dist/a.xpi' }],
  ['an action nobody offers', { action: 'delete', project: 'alpha' }],
]){
  const r = await post(body);
  ok(r.status === 400 && r.body.error, `refused: ${what}`);
}
page.errors = [];

// ---- the empty state says what the convention is ---------------------------
await page.click(`${row('beta')} [data-m]`);
await page.waitForSelector('.nbtabs [data-v="artifacts"]:visible', { timeout: 20000 });
await page.click('.nbtabs [data-v="artifacts"]:visible');
// Scoped to the pane: alpha's notebook is parked but its own artifacts view
// is still the active one inside that instance, so an unscoped selector finds
// the wrong project's rows.
await page.waitForFunction(() => /dist\//.test(
  document.querySelector('.pane .nb [data-view="artifacts"] .hint')?.textContent || ''),
  null, { timeout: 15000 });
ok(true, 'a project with no dist/ is told the convention, not shown a blank');

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
await done(browser);
