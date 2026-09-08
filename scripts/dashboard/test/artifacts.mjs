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
// python's zipfile rather than `zip`: the controller image carries zip, a
// node running this suite (bb-sandbox) does not, and a fixture should not
// decide which machines the suite runs on.
execFileSync('python3', ['-c', `
import sys, zipfile
with zipfile.ZipFile(sys.argv[1], 'w', zipfile.ZIP_DEFLATED) as z:
    for f in sys.argv[2:]: z.write(f, f.rsplit('/', 1)[-1])`,
  `${DIR}/ws/alpha/dist/companion-0.2.0.xpi`, `${stage}/manifest.json`, `${stage}/background.js`]);
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
ok(await page.$eval('#artBuild', e => !e.hidden && /No node/.test(e.textContent)
     && /Reading and editing the code needs no node/.test(e.textContent)),
   'the tab says a project with no node cannot be compiled for, and what is left');
ok(!names.some(n => /provenance/.test(n)),
   '...and the provenance records beside them are not artifacts');
ok(await page.$eval('#artList', e => /built by j_fixture1 on n_fixture from snapshot abababababab/.test(e.textContent)),
   'a built artifact says which job made it, where, and from which snapshot');
ok(await page.$$eval('.artrow .pill', ps =>
     ps.some(p => p.textContent === 'apk') && ps.some(p => p.textContent === 'xpi')),
   '...each labeled by what it is');
// The files, not the install-status row an earlier file's install may have left.
const acts = await page.$$eval('.artrow:not(.job)', rs => rs.map(r => ({
  name: r.querySelector('b')?.textContent,
  install: !!r.querySelector('[data-artinstall]'),
  dl: !!r.querySelector('a.btn') })));
ok(acts.find(a => a.name === 'streamlift-1.2.apk').install
   && !acts.find(a => a.name === 'companion-0.2.0.xpi').install,
   'Install is offered for the APK and not for the extension');
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

// ---- installing needs a phone on the project's node ----------------------
// alpha has no node here, so Install and Push are offered and ghosted with
// the reason: the phone is driven from a node, and this project has none.
// The install and the push themselves — and the signature clash said in
// words — are phone.mjs's, where a fixture node holds the phone.
ok(await page.$eval('[data-artinstall]', b => b.disabled && /Phone tab/.test(b.title)),
   'with no phone on the project\'s node, Install is ghosted and says where to connect one');
ok(await page.$eval('[data-artpush]', b => b.disabled && /Phone tab/.test(b.title)),
   'Push is there for the extension, ghosted for the same reason');
const pushed = await page.evaluate(async () => {
  const r = await fetch('/api/artifacts', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action: 'push', project: 'alpha', path: 'dist/companion-0.2.0.xpi' }) });
  return { status: r.status, body: await r.json() };
});
ok(pushed.status === 400 && /has no node/.test(pushed.body.error),
   '...and the API says why rather than pretending');
page.errors = [];

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
  document.querySelector('.pane .nb [data-view="artifacts"] #artList .hint')?.textContent || ''),
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
