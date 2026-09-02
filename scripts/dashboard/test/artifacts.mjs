// The notebook's Artifacts view: what a project has built, from its dist/.
// The convention IS the feature — the tab lists dist/ and nothing else, so a
// build worth keeping has to be copied there, and an empty tab says that.
import { launch, newPage, ok, done, ready, URL, DIR, refreshUntil } from './lib.mjs';
import { mkdirSync, writeFileSync, symlinkSync, rmSync, renameSync } from 'node:fs';
import { execFileSync } from 'node:child_process';

// alpha ships an APK and an XPI; the XPI is a real zip with a manifest, since
// pushing one means unpacking it and handing the directory to web-ext.
mkdirSync(`${DIR}/ws/alpha/dist/android`, { recursive: true });
writeFileSync(`${DIR}/ws/alpha/dist/android/streamlift-1.2.apk`, 'not-really-an-apk');
// What built it, as a job would leave it (docs/nodes.md §6): the tab says so
// on the row, and the record itself is never listed as an artifact.
mkdirSync(`${DIR}/ws/alpha/dist/.provenance/android`, { recursive: true });
writeFileSync(`${DIR}/ws/alpha/dist/.provenance/android/streamlift-1.2.apk.json`, JSON.stringify({
  job: 'j_fixture1', node: 'n_fixture', source: { digest: 'sha256:' + 'ab'.repeat(32) },
  sha256: 'cd'.repeat(32), size: 17 }));
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
ok(!names.some(n => /provenance/.test(n)),
   '...and the provenance records beside them are not artifacts');
ok(await page.$eval('#artList', e => /built by j_fixture1 on n_fixture from snapshot abababababab/.test(e.textContent)),
   'a built artifact says which job made it, where, and from which snapshot');
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

// ---- installing an APK -----------------------------------------------------
// `adb install -r` replaces an existing copy in place, so install and update
// are one verb. The interesting half is the failure: a signature clash is the
// one that actually happens, and it has to arrive as a sentence.
ok(await page.$eval('[data-artinstall]', b => !b.disabled),
   'an APK offers Install, and only an APK does');
ok(await page.$$eval('.artrow', rs => rs.filter(r =>
     r.querySelector('[data-artpush]') && r.querySelector('[data-artinstall]')).length === 0),
   '...never both on one row — they are different acts on different things');
const instState = () => page.evaluate(async () =>
  (await (await fetch('/api/artifacts?project=alpha')).json()).install || {});
await page.click('[data-artinstall]');
await page.waitForFunction(async () => {
  const r = await (await fetch('/api/artifacts?project=alpha')).json();
  return (r.install || {}).state === 'done';
}, null, { timeout: 25000 });
ok((await instState()).error === '', 'Install runs and reports no error');

// ...and the clash, in words. The tab is reloaded by leaving and coming back,
// which is what a person does — loadArtifacts lives inside the notebook's own
// closure and is not something a test can call.
writeFileSync(`${DIR}/ws/alpha/dist/streamlift-1.3-clash.apk`, 'x');
await page.click('.nbtabs [data-v="analysis"]:visible');
await page.click('.nbtabs [data-v="artifacts"]:visible');
await page.waitForFunction(() => [...document.querySelectorAll('.artrow')]
  .some(r => /clash/.test(r.textContent)), null, { timeout: 15000 });
await page.evaluate(() => {
  const r = [...document.querySelectorAll('.artrow')].find(x => /clash/.test(x.textContent));
  r.querySelector('[data-artinstall]').click();
});
await page.waitForFunction(async () => {
  const r = await (await fetch('/api/artifacts?project=alpha')).json();
  return (r.install || {}).state === 'failed';
}, null, { timeout: 25000 });
ok(/signed with a different key/.test((await instState()).error),
   'a signature clash is explained, not passed through as INSTALL_FAILED_UPDATE_INCOMPATIBLE');
await page.waitForFunction(() => /signed with a different key/.test(
  document.querySelector('.artrow.job')?.textContent || ''), null, { timeout: 15000 });
ok(true, '...and the sentence is what the tab shows');

// ---- the view notices the phone arriving ----------------------------------
// Whether Push is offered depends on a phone being connected, and that happens
// on a different card — or from a terminal. The view used to fetch when its
// tab was opened and never again, so a phone connected afterwards left Push
// ghosted and looking broken.
{
  // Hide the phone by moving the stub aside, then bring it back and let the
  // poll do the work — no tab switching, which is the thing that used to be
  // required.
  renameSync(`${DIR}/bin/adb`, `${DIR}/bin/adb.hidden`);
  // Asked again each pass: the phone verdict is cached for 3s and the page
  // polls every 15, so one refresh right after hiding adb can be answered from
  // the cache. See refreshUntil — the same shape as the auth waits in cards.
  await refreshUntil(page, () => {
    const b = document.querySelector('[data-artpush]');
    return !!b && b.disabled;
  });
  ok(true, 'with the phone gone, Push goes dead on its own');
  renameSync(`${DIR}/bin/adb.hidden`, `${DIR}/bin/adb`);
  // The mirror of the wait above, and cached the same way — converting only
  // the going-away half left the coming-back half to time out in the very
  // next run.
  await refreshUntil(page, () => {
    const b = document.querySelector('[data-artpush]');
    return !!b && !b.disabled;
  });
  ok(true, '...and comes back when it returns, without touching the tab');
}

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
  ['installing the xpi, which is not an APK', { action: 'install', project: 'alpha', path: 'dist/companion-0.2.0.xpi' }],
  ['installing a path outside dist/', { action: 'install', project: 'alpha', path: '../beta/x.apk' }],
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
// Put alpha back as it was found. fresh() between files resets state and
// removes stray projects, but it does not reach inside a fixture project —
// so a file that plants a dist/ tree and a symlink there has to clear them
// itself, or every later file runs against a project this one changed.
rmSync(`${DIR}/ws/alpha/dist`, { recursive: true, force: true });
rmSync(`${DIR}/ws/alpha/secret.txt`, { force: true });
await done(browser);
