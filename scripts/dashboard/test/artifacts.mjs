// The notebook's Artifacts view: what a project has built, from its dist/.
// The convention IS the feature: the tab lists dist/ and nothing else, so a
// build worth keeping has to be copied there, and an empty tab says that.
import { launch, newPage, ok, done, ready, URL, DIR, refreshUntil, openFold } from './lib.mjs';
import { mkdirSync, writeFileSync, symlinkSync, rmSync, renameSync, existsSync, utimesSync } from 'node:fs';
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
// ...and two shell scripts, which is a product like any other: one named
// .sh, one named the way a shipped installer usually is, with no extension
// and a shebang on the first line, which is the only thing that says what it is.
writeFileSync(`${DIR}/ws/alpha/dist/setup-1.2.sh`,
  '#!/usr/bin/env bash\nset -euo pipefail\necho "setting up"\n');
writeFileSync(`${DIR}/ws/alpha/dist/install`,
  '#!/bin/sh\necho "no extension, still a script"\n');
// A binary with an extension this list does not know must NOT be sniffed
// into a script, and must not offer to be read as text.
writeFileSync(`${DIR}/ws/alpha/dist/firmware.bin`, Buffer.from([0, 1, 2, 3, 4]));
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
// What a session looked with (R96): two reels and two emulator shots, each
// with the record bb capture leaves (who, when); one reel ten days old,
// which the project's default of seven days sweeps on the tab's first read;
// one shot with no record at all, which goes by its own time.
const now = Math.floor(Date.now() / 1000);
const seedReel = (name, at) => {
  mkdirSync(`${DIR}/ws/alpha/dist/reel/${name}`, { recursive: true });
  writeFileSync(`${DIR}/ws/alpha/dist/reel/${name}/sheet.png`, Buffer.from([0x89, 0x50, 0x4e, 0x47]));
  writeFileSync(`${DIR}/ws/alpha/dist/reel/${name}/frames.json`, JSON.stringify({
    by: 'stencil', at, node: 'n_fixture', work: '/tmp/nowhere', frames: [{ t: 0 }, { t: 1.5 }, { t: 3 }] }));
};
seedReel('walk', now - 120);
seedReel('stale', now - 10 * 86400);
mkdirSync(`${DIR}/ws/alpha/dist/emu`, { recursive: true });
writeFileSync(`${DIR}/ws/alpha/dist/emu/shot-1.png`, Buffer.from([0x89, 0x50, 0x4e, 0x47]));
writeFileSync(`${DIR}/ws/alpha/dist/emu/.shot-1.png.json`, JSON.stringify({ by: 'claude', at: now - 60, source: 'emu' }));
writeFileSync(`${DIR}/ws/alpha/dist/emu/loose.png`, Buffer.from([0x89, 0x50, 0x4e, 0x47]));
// ...and a secret outside dist/, wired in by symlink: the download endpoint
// must refuse to follow it out.
writeFileSync(`${DIR}/ws/alpha/secret.txt`, 'not yours');
symlinkSync(`${DIR}/ws/alpha/secret.txt`, `${DIR}/ws/alpha/dist/leak.txt`);

// Five dev builds of one APK and its release (R105): the tab keeps the
// newest three dev builds and never the release's place.
{
  const t0 = Math.floor(Date.now() / 1000) - 5000;
  for (let n = 1; n <= 5; n++){
    const f = `${DIR}/ws/alpha/dist/alpha-1.2.0-dev.${n}-abcdef${n}-debug.apk`;
    writeFileSync(f, 'dev build');
    utimesSync(f, t0 + n * 100, t0 + n * 100);
  }
  writeFileSync(`${DIR}/ws/alpha/dist/alpha-1.2.0-debug.apk`, 'release');
  utimesSync(`${DIR}/ws/alpha/dist/alpha-1.2.0-debug.apk`, t0, t0);
  // A build a sign job delivered (R106 step 4), with the provenance the
  // controller writes for it: what signed it and the certificate.
  writeFileSync(`${DIR}/ws/alpha/dist/alpha-1.2.0-signed.apk`, 'signed');
  mkdirSync(`${DIR}/ws/alpha/dist/.provenance`, { recursive: true });
  writeFileSync(`${DIR}/ws/alpha/dist/.provenance/alpha-1.2.0-signed.apk.json`, JSON.stringify({
    job: 'j_sign1', node: 'n_x', type: 'sign', at: t0, sha256: 'ab'.repeat(32), path: 'dist/alpha-1.2.0-signed.apk',
    signed: { route: 'sideload', cert: '6557990CCC68E19D2F4CE5731C8D59F9845D87C9952DF09D30DFF05609488C2D',
              schemes: ['v2', 'v3'], from: 'alpha-1.2.0-debug.apk', key: 'watch', rotated_from: 'default' } }));
}
const browser = await launch();
const page = await newPage(browser, { viewport: { width: 1280, height: 1000 } });
await page.goto(URL);
await ready(page);
const row = n => `#projects .row:has(.name:text-is("${n}"))`;
await page.click(`${row('alpha')} [data-m]`);
await page.waitForSelector('#roadmapList, .nb', { timeout: 20000 });
await page.click('.nbtabs [data-v="artifacts"]:visible');
await page.waitForSelector('.artrow', { timeout: 15000 });

// The files are a section of their own, like the rest of the view, and the
// one open when the view first shows (the operator, 6 Oct): they were a
// band under Version, the one part of the tab that did not fold.
{
  const s = await page.evaluate(() => [...document.querySelectorAll('.nb .nbview[data-view="artifacts"] details.sect')]
    .filter(d => d.checkVisibility() && !d.parentElement.closest('details.sect')).map(d => `${d.dataset.sect}:${d.open ? 'open' : 'shut'}`));
  ok(s.includes('artifacts:files:open') && s.filter(x => x.endsWith(':open')).length === 1,
     `the files are their own section, the one open when the view shows (${s.join(' ')})`);
}

// ---- a signed build (R106 step 4) --------------------------------------------
{
  const r = await page.$eval('.artrow:has(b:text-is("alpha-1.2.0-signed.apk"))', e => ({
    pill: !!e.querySelector('.pill.ok'), text: e.textContent.replace(/\s+/g, ' '),
    copy: !!e.querySelector('[data-artfp]'), sign: !!e.querySelector('[data-artsign]') }));
  ok(r.pill && /signed with the watch key's sideload signing key from alpha-1\.2\.0-debug\.apk, verified v2, v3, rotated from default: Android 8\.1 and older still see default/.test(r.text)
     && /SHA-256 65:57:99:0C:CC:68:E1:9D:2F:4C:E5:73:1C:8D:59:F9:84:5D:87:C9:95:2D:F0:9D:30:DF:F0:56:09:48:8C:2D/.test(r.text)
     && r.copy && !r.sign,
     `a signed build says so, with the key, what verified and the whole fingerprint to copy, and offers no Sign again (${r.text.slice(0, 120)})`);
}

// ---- the listing -----------------------------------------------------------
const names = await page.$$eval('.artrow b', bs => bs.map(b => b.textContent));
{
  const dev = names.filter(n => /^alpha-1\.2\.0-dev\./.test(n)).sort();
  const note = await page.$eval('#artList', e => [...e.querySelectorAll('.hint')].map(h => h.textContent).join(' '));
  ok(dev.join() === ['alpha-1.2.0-dev.3-abcdef3-debug.apk', 'alpha-1.2.0-dev.4-abcdef4-debug.apk', 'alpha-1.2.0-dev.5-abcdef5-debug.apk'].join()
     && names.includes('alpha-1.2.0-debug.apk') && !existsSync(`${DIR}/ws/alpha/dist/alpha-1.2.0-dev.1-abcdef1-debug.apk`),
     `of five dev builds of one APK the newest three are kept and the release beside them stays (${dev.join(', ')})`);
  ok(/newest 3 builds/.test(note) && /signed copy alone/.test(note) && /A release is kept/.test(note) && /anything pinned/.test(note),
     `...and the tab says so (${note.replace(/\s+/g, ' ').slice(0, 120)})`);
  // A pin keeps one whatever comes after it (the operator, 30 Sep): the
  // oldest kept is pinned on its row, two newer builds arrive, and it is
  // still there, marked, while the ones beside it went.
  const oldest = 'alpha-1.2.0-dev.3-abcdef3-debug.apk';
  await page.evaluate(n => [...document.querySelectorAll('#artList .artrow')]
    .find(r => r.querySelector('b')?.textContent === n)?.querySelector('[data-artpin]')?.click(), oldest);
  await page.waitForFunction(n => [...document.querySelectorAll('#artList .artrow')]
    .some(r => r.querySelector('b')?.textContent === n && /pinned/.test(r.textContent)), oldest, { timeout: 15000 });
  const t1 = Math.floor(Date.now() / 1000);
  for (const n of [6, 7]){
    const f = `${DIR}/ws/alpha/dist/alpha-1.2.0-dev.${n}-abcdef${n}-debug.apk`;
    writeFileSync(f, 'dev build');
    utimesSync(f, t1 - 100 + n, t1 - 100 + n);
  }
  const after = await page.evaluate(async () => (await (await fetch('/api/artifacts?project=alpha')).json()).artifacts
    .filter(a => /-dev\./.test(a.name)).map(a => a.name + (a.pinned ? '*' : '')).sort());
  ok(after.join() === ['alpha-1.2.0-dev.3-abcdef3-debug.apk*', 'alpha-1.2.0-dev.5-abcdef5-debug.apk',
                       'alpha-1.2.0-dev.6-abcdef6-debug.apk', 'alpha-1.2.0-dev.7-abcdef7-debug.apk'].join(),
     `a pinned build stays when newer ones arrive, and is not one of the three kept beside it (${after.join(', ')})`);
  // How many are kept is the project's setting (Dev builds kept, 3 unless
  // it says): at 2, one more goes on the next read; at 0 nothing does; a
  // value that is not a count is refused.
  const setKeep = v => page.evaluate(async v => (await (await fetch('/api/prefs', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project: 'alpha', dev_keep: v }) })).json()), v);
  const devNow = () => page.evaluate(async () => { const j = await (await fetch('/api/artifacts?project=alpha')).json();
    return { keep: j.dev_keep, names: j.artifacts.filter(a => /-dev\./.test(a.name) && !a.pinned).map(a => a.name).sort() }; });
  const bad = await setKeep('lots');
  await setKeep(2);
  const two = await devNow();
  ok(/dev builds kept is a number of builds/.test(bad.error || '') && two.keep === 2
     && two.names.join() === 'alpha-1.2.0-dev.6-abcdef6-debug.apk,alpha-1.2.0-dev.7-abcdef7-debug.apk',
     `the project's Dev builds kept says how many of each stay (2: ${two.names.join(', ')}), and a value that is not a count is refused`);
  await setKeep(0);
  const t2 = Math.floor(Date.now() / 1000);
  for (const n of [8, 9]){
    const f = `${DIR}/ws/alpha/dist/alpha-1.2.0-dev.${n}-abcdef${n}-debug.apk`;
    writeFileSync(f, 'dev build'); utimesSync(f, t2 - 50 + n, t2 - 50 + n);
  }
  const all = await devNow();
  ok(all.keep === 0 && all.names.length === 4, `...and 0 keeps every one (${all.names.length})`);
  await setKeep(3);
  const unpin = await page.evaluate(async n => (await (await fetch('/api/artifacts', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project: 'alpha', action: 'unpin', path: `dist/${n}` }) })).json()), oldest);
  ok(unpin.ok && unpin.pinned === false, '...and unpinned, it goes like any other build');
}
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

// ---- the captures: apart from what ships, whose they are, gone by age ------
{
  const art = await page.evaluate(async () =>
    (await (await fetch('/api/artifacts?project=alpha')).json()));
  const capNames = (art.captures || []).map(c => c.name);
  const shipped = await page.$$eval('#artList .artrow b', bs => bs.map(b => b.textContent));
  ok(!shipped.some(n => /sheet\.png|shot-1\.png|loose\.png|frames\.json|^walk$/.test(n))
     && !(art.artifacts || []).some(a => /^dist\/(reel|emu)\//.test(a.path)),
     `a reel's sheet and an emulator shot are not listed among what the project ships (${shipped.join(', ')})`);
  const ats = (art.captures || []).map(c => c.at);
  ok(capNames.length === 3 && ['shot-1.png', 'walk', 'loose.png'].every(n => capNames.includes(n))
     && ats.every((t, i) => !i || t <= ats[i - 1]) && art.capture_days === 7,
     `...they are the captures, newest first, and the project keeps them 7 days (${capNames.join(', ')}; ${art.capture_days})`);
  ok(!existsSync(`${DIR}/ws/alpha/dist/reel/stale`),
     'the ten-day-old reel was swept on that read: by age, never by need');
  const walk = art.captures.find(c => c.name === 'walk'), loose = art.captures.find(c => c.name === 'loose.png');
  ok(walk?.kind === 'reel' && walk.by === 'stencil' && walk.frames === 3 && walk.path === 'dist/reel/walk/sheet.png'
     && loose?.kind === 'shot' && loose.by === '' && Math.abs(loose.at - now) < 120,
     `each says what it is, whose it is and where its picture is; one with no record goes by its file's time (${
        JSON.stringify({ walk, loose })})`);
  await page.evaluate(() => getNotebook('alpha')?.view('artifacts'));
  await page.waitForSelector('#artCaptures details.sect', { timeout: 15000 });
  const head = await page.$eval('#artCaptures summary', e => e.textContent);
  ok(/Captures/.test(head) && /3, kept 7 days/.test(head)
     && await page.$eval('#artCaptures details.sect', d => !d.open),
     `the tab draws them as one fold, shut, saying how many and for how long (${head.trim()})`);
  await page.click('#artCaptures summary');
  await page.waitForFunction(() => document.querySelector('#artCaptures details.sect')?.open, null, { timeout: 10000 });
  // By text, not by position: the one with no record goes by its file's
  // time, which is whenever this suite wrote it.
  const rows = await page.$$eval('#artCaptures .artrow', rs => rs.map(r => r.textContent.replace(/\s+/g, ' ').trim()));
  ok(rows.length === 3 && rows.some(r => /reel walk by stencil · .* · 3 frames/.test(r)) && rows.some(r => /shot shot-1\.png by claude/.test(r))
     && rows.some(r => /loose\.png by nobody known/.test(r)),
     `...each row says whose it is (${rows.join(' | ')})`);
  const dl = await page.$$eval('#artCaptures .artrow a.btn', as => as.map(a => a.getAttribute('href')));
  ok(dl.some(h => /path=dist%2Freel%2Fwalk%2Fsheet\.png/.test(h)), 'Download hands over the sheet');
  await page.click('#artCaptures .artrow:has(b:text-is("loose.png")) [data-artcap]');
  await page.waitForFunction(() => !document.querySelector('#artCaptures .artrow b')
    || ![...document.querySelectorAll('#artCaptures .artrow b')].some(b => b.textContent === 'loose.png'), null, { timeout: 15000 });
  ok(!existsSync(`${DIR}/ws/alpha/dist/emu/loose.png`) && await page.$eval('#artCaptures summary', e => /2, kept/.test(e.textContent)),
     'Remove takes one away now, and the fold recounts');
  // 0 keeps them: a stale one seeded again survives the read, and the fold
  // says so. A number that is not days is refused by name.
  const pref = async body => page.evaluate(async b => (await (await fetch('/api/prefs', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) })).json()), body);
  const bad = await pref({ project: 'alpha', capture_days: 'soon' });
  ok(/captures kept is a number of days, 0 to 365/.test(bad.error || ''), `a value that is not days is refused (${bad.error})`);
  const zero = await pref({ project: 'alpha', capture_days: 0 });
  seedReel('stale', now - 10 * 86400);
  const again = await page.evaluate(async () => (await (await fetch('/api/artifacts?project=alpha')).json()));
  ok(!zero.error && again.capture_days === 0 && again.captures.some(c => c.name === 'stale') && existsSync(`${DIR}/ws/alpha/dist/reel/stale`),
     `captures kept 0 keeps a ten-day-old reel (${again.capture_days}; ${again.captures.map(c => c.name).join(', ')})`);
  await page.evaluate(() => getNotebook('alpha')?.view('artifacts'));
  await page.waitForFunction(() => /kept until removed/.test(document.querySelector('#artCaptures summary')?.textContent || ''),
                             null, { timeout: 15000 });
  ok(true, '...and the fold says they are kept until removed');
  // A session lets a capture go from the tree (bb capture prune), never here.
  const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
  const tok = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'test'],
    { encoding: 'utf8', env: { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` } }).trim();
  const r = await fetch(URL.replace(/\/$/, '') + '/api/artifacts', { method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + tok },
    body: JSON.stringify({ project: 'alpha', action: 'forget-capture', name: 'walk' }) });
  const asSession = { status: r.status, j: await r.json().catch(() => ({})) };
  ok(asSession.status === 403 && /bb capture prune/.test(asSession.j.error || '') && existsSync(`${DIR}/ws/alpha/dist/reel/walk`),
     `a session is told to use bb capture prune instead (${asSession.status} ${asSession.j.error})`);
  await pref({ project: 'alpha', capture_days: 7 });
}

// ---- a script is a product, and one people read before they run it ---------
{
  const arts = await page.evaluate(async () =>
    (await (await fetch('/api/artifacts?project=alpha')).json()).artifacts);
  const kind = n => arts.find(a => a.name === n)?.kind;
  ok(kind('setup-1.2.sh') === 'script',
     `a .sh in dist/ is a script, not an unlabeled file (${kind('setup-1.2.sh')})`);
  ok(kind('install') === 'script',
     `...and so is a shipped installer with no extension, by its shebang (${kind('install')})`);
  ok(kind('firmware.bin') === 'file',
     `...while a binary is left alone (${kind('firmware.bin')})`);
  const viewable = await page.$$eval('.artrow:not(.job)', rs => rs.map(r => ({
    name: r.querySelector('b')?.textContent,
    view: !!r.querySelector('[data-artview]') })));
  ok(viewable.find(a => a.name === 'setup-1.2.sh').view
     && viewable.find(a => a.name === 'install').view
     && !viewable.find(a => a.name === 'streamlift-1.2.apk').view
     && !viewable.find(a => a.name === 'firmware.bin').view,
     `View is offered on the scripts and on nothing else (${
       viewable.filter(a => a.view).map(a => a.name).join(', ')})`);
  // Read over the panel, the way a History is, with the file's own line
  // breaks. Nothing here runs it and the tab has no way to.
  // One section open at a time (the operator, 5 Oct): Captures was opened
  // above, so Files is opened again before a file's View is pressed.
  await openFold(page, '.nb [data-sect="artifacts:files"]');
  await page.click('.artrow:has(b:text-is("setup-1.2.sh")) [data-artview]');
  await page.waitForFunction(
    () => /setting up/.test(document.querySelector('.nb #sheetSlot')?.textContent || ''),
    null, { timeout: 15000 });
  const sheet = await page.$eval('.nb .nbsheet', e => ({
    title: e.querySelector('#sheetTitle').textContent,
    text: e.querySelector('#sheetSlot').textContent,
    run: !!e.querySelector('button[data-artrun], button[data-run]') }));
  ok(sheet.title === 'setup-1.2.sh' && /#!\/usr\/bin\/env bash/.test(sheet.text)
     && /set -euo pipefail/.test(sheet.text) && !sheet.run,
     `...and View reads it over the panel, shebang and all, with nothing offering to run it (${
       JSON.stringify(sheet.text.slice(0, 40))})`);
  await page.click('.nb #sheetClose');
  await page.waitForSelector('.nb .nbsheet', { state: 'hidden' });
}

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
   '...and so is a symlink pointing out of it: dist/ must not become a file server');

// ---- the code base itself, as a zip ------------------------------------------
// What git tracks and would track, under one directory named for the
// project; never .git, dist/ (the artifacts have their own downloads) or a
// symlink pointing out of the tree.
ok(await page.$eval('#artSource', b => !b.disabled && b.textContent === 'Download source'),
   'the tab offers the code base as a download');
{
  const zipPath = `${DIR}/alpha-source.zip`, hdrs = `${DIR}/alpha-source.hdr`;
  execFileSync('curl', ['-fsS', '-u', 'test:test', '-D', hdrs, '-o', zipPath,
                        `${URL.replace(/\/$/, '')}/api/source?project=alpha`]);
  const names = execFileSync('python3', ['-c', `
import sys, zipfile
print("\\n".join(zipfile.ZipFile(sys.argv[1]).namelist()))`, zipPath], { encoding: 'utf8' }).trim().split('\n');
  const head = execFileSync('cat', [hdrs], { encoding: 'utf8' });
  ok(/content-type: application\/zip/i.test(head) && /filename="alpha-source-[^"]+\.zip"/.test(head),
     `it is a zip named for the project (${(head.match(/filename="[^"]+"/) || [''])[0]})`);
  ok(names.includes('alpha/README.md') && names.every(n => n.startsWith('alpha/')),
     `the tree is inside one directory named for the project (${names.length} entries)`);
  ok(!names.some(n => n.startsWith('alpha/dist/') || n.startsWith('alpha/.git/')),
     '...with neither dist/ nor .git in it');
}
page.errors = [];

// ---- installing needs a phone on the project's node ----------------------
// alpha has no node here, so Install and Push are offered and ghosted with
// the reason: the phone is driven from a node, and this project has none.
// The install and the push themselves, and the signature clash said in
// words, are phone.mjs's, where a fixture node holds the phone.
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
// ...and by its words, since a list can carry another line (R105's note on
// dev builds) before them.
await page.waitForFunction(() => [...document.querySelectorAll('.pane .nb [data-view="artifacts"] #artList .hint')]
  .some(h => /Nothing in dist\//.test(h.textContent)), null, { timeout: 15000 });
ok(true, 'a project with no dist/ is told the convention, not shown a blank');

// ---- a build on a branch, in an account's own worktree (B237) -------------
// A second account's session builds in its worktree and its outputs land in
// that worktree's dist/, where the tab never looked: its first build showed
// nothing. Listed apart from dist/, with Download and View carrying the tree.
{
  const H = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
  await fetch(URL.replace(/\/$/, '') + '/api/users', { method: 'POST', headers: H,
    body: JSON.stringify({ action: 'add', name: 'w.builder', password: 'w.builder-pass-1', role: 'user' }) });
  const uid = JSON.parse((await import('node:fs')).readFileSync(`${DIR}/state/users.json`, 'utf8')).users['w.builder'].uid;
  const WT = `${DIR}/ws/.worktrees/alpha/${uid}`;
  mkdirSync(`${DIR}/ws/.worktrees/alpha`, { recursive: true });
  execFileSync('git', ['-C', `${DIR}/ws/alpha`, 'worktree', 'add', '-q', '-b', 'claude/w.builder', WT]);
  mkdirSync(`${WT}/dist`, { recursive: true });
  writeFileSync(`${WT}/dist/app-2.0.tar.gz`, 'the branch build');
  writeFileSync(`${WT}/dist/run.sh`, '#!/bin/sh\necho from the branch\n');
  const get = async q => { const r = await fetch(URL.replace(/\/$/, '') + q, { headers: H });
    return { status: r.status, text: await r.text() }; };
  const art = JSON.parse((await get('/api/artifacts?project=alpha')).text);
  const g = (art.branches || [])[0] || {};
  ok(g.who === 'w.builder' && g.branch === 'claude/w.builder'
     && (g.artifacts || []).some(a => a.name === 'app-2.0.tar.gz' && a.path === 'dist/app-2.0.tar.gz')
     && !(art.artifacts || []).some(a => a.name === 'app-2.0.tar.gz'),
     `a build in an account's worktree is listed under whose it is and its branch, apart from dist/ (${
       JSON.stringify({ who: g.who, branch: g.branch, n: (g.artifacts || []).length })})`);
  const dl = await get(`/api/artifact?project=alpha&path=dist/app-2.0.tar.gz&tree=${uid}`);
  ok(dl.status === 200 && dl.text === 'the branch build', '...and downloads from there');
  const outs = await Promise.all([
    `/api/artifact?project=alpha&path=dist/app-2.0.tar.gz&tree=..`,
    `/api/artifact?project=alpha&path=../README.md&tree=${uid}`,
    `/api/artifact?project=alpha&path=dist/app-2.0.tar.gz&tree=u_00000000`,
    `/api/artifact?project=alpha&path=dist/app-2.0.tar.gz`].map(get));
  ok(outs.every(r => r.status === 404),
     `...while a tree that is not one, a path out of its dist/, or the wrong tree finds nothing (${outs.map(r => r.status).join(',')})`);
  await page.evaluate(() => getNotebook('alpha')?.view('artifacts'));
  await page.waitForFunction(() => {
    const b = document.querySelector('.nb[data-project="alpha"] #artBranches');
    return b && !b.hidden && b.querySelectorAll('.artrow').length === 2;
  }, null, { timeout: 15000 });
  const drawn = await page.$eval('.nb[data-project="alpha"] #artBranches', b => ({
    label: b.querySelector('.ggroup')?.textContent || '',
    href: b.querySelector('a[download]')?.getAttribute('href') || '',
    view: !!b.querySelector('[data-artbview]') }));
  ok(/w\.builder's branch builds, on claude\/w\.builder/.test(drawn.label) && drawn.href.includes(`tree=${uid}`) && drawn.view,
     `...and the tab shows it under a line saying whose, with Download and View (${drawn.label})`);
  execFileSync('git', ['-C', `${DIR}/ws/alpha`, 'worktree', 'remove', '--force', WT]);
  // The fixture's alpha has no commits, so the worktree's branch was never
  // born and there is no ref to delete; one that was born goes.
  try { execFileSync('git', ['-C', `${DIR}/ws/alpha`, 'branch', '-D', 'claude/w.builder'], { stdio: 'ignore' }); }
  catch { /* unborn */ }
}

ok(page.errors.length === 0, 'zero console errors');
if (page.errors.length) console.log(page.errors);
// Put alpha back as it was found. fresh() between files resets state and
// removes stray projects, but it does not reach inside a fixture project, so
// ---- a build named with no version (the operator, 6 Oct) ----------------------
// Nothing can tell when it is out of date, so the sweep leaves it and its row
// says so in the warning color, with a Remove that a person presses.
{
  writeFileSync(`${DIR}/ws/alpha/dist/app-debug.apk`, 'a build copied in by hand');
  await page.evaluate(() => getNotebook('alpha').view('artifacts'));
  await page.waitForFunction(() => [...document.querySelectorAll('#artList .artrow')]
    .some(r => r.querySelector('b')?.textContent === 'app-debug.apk'), null, { timeout: 15000 });
  const r = await page.evaluate(() => { const row = [...document.querySelectorAll('#artList .artrow')]
    .find(x => x.querySelector('b')?.textContent === 'app-debug.apk');
    return { said: row.querySelector('.vermark')?.textContent || '', rm: !!row.querySelector('[data-artunnamed]') }; });
  ok(/named with no version/.test(r.said) && r.rm,
     `a build named with no version says nothing can tell when it is out of date, and offers Remove (${r.said})`);
  await page.evaluate(() => [...document.querySelectorAll('#artList .artrow')]
    .find(x => x.querySelector('b')?.textContent === 'app-debug.apk')?.querySelector('[data-artunnamed]')?.click());
  await page.waitForFunction(() => ![...document.querySelectorAll('#artList .artrow b')].some(b => b.textContent === 'app-debug.apk'),
                             null, { timeout: 15000 });
  ok(!existsSync(`${DIR}/ws/alpha/dist/app-debug.apk`), '...and Remove takes it out of dist/');
}

// a file that plants a dist/ tree and a symlink there has to clear them
// itself, or every later file runs against a project this one changed.
rmSync(`${DIR}/ws/alpha/dist`, { recursive: true, force: true });
rmSync(`${DIR}/ws/alpha/secret.txt`, { force: true });
await done(browser);
