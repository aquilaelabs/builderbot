// Older installs are not broken by this build (R79): this tree's controller
// started on a copy of every supported release's /config snapshot
// (test/upgrade/VERSION/, written by tools/upgrade-snapshot.py when that
// release was cut), and checked to migrate it and keep everything in it.
//
// Each snapshot three ways. As the release left it: the stamp moves to this
// build's state, with a copy under backups/ when it had to move. With its
// stamp taken off, which is a /config from before the stamp existed (state
// 0), while this build still migrates from 0: migration 0001 runs, the copy
// is taken, and nothing is lost. And stamped newer than this build: the
// controller refuses to start, says so, and writes nothing. Each time the
// owner signs in through the form in a browser, every account signs in, and
// every account, project, role on a project, notebook entry (roadmap, bugs,
// house rules, wiki), tool pack and device the manifest lists is still there.
//
// What it holds: stateversion.py, statemigrations/ (from 0003, the floor being
// 0.6.0's state), statefile.py, users.py, and whatever a release's /config is read by.
// Its own controller per case, on its own port and scratch directories,
// beside the harness's world and never in it.
import { launch, ok, done, DIR, sleep, patience } from './lib.mjs';
import { mkdirSync, readFileSync, writeFileSync, existsSync, readdirSync, rmSync, openSync } from 'node:fs';
import { execFileSync, spawn } from 'node:child_process';
import { createServer } from 'node:net';
import { fileURLToPath } from 'node:url';

const DASH = fileURLToPath(new URL('..', import.meta.url));
const SNAPS = fileURLToPath(new URL('./upgrade', import.meta.url));
const policy = JSON.parse(execFileSync('python3', [`${DASH}/stateversion.py`, 'policy']).toString());
const BUILD = `${readFileSync(`${DASH}/../../VERSION`, 'utf8').trim()}-dev.1+upgrade`;

const freePort = () => new Promise(res => {
  const s = createServer().listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); });
});
const basic = (u, pw) => ({ Authorization: 'Basic ' + Buffer.from(`${u}:${pw}`).toString('base64') });

// A snapshot unpacked into a world of its own: config/ and workspace/.
function unpack(ver, tag){
  const w = `${DIR}/upgrade-${ver}-${tag}`;
  rmSync(w, { recursive: true, force: true });
  mkdirSync(w, { recursive: true });
  execFileSync('tar', ['-xzf', `${SNAPS}/${ver}/config.tar.gz`, '-C', w]);
  return w;
}

// This tree's controller on that world, as run.sh starts the harness's.
async function start(w){
  const port = await freePort();
  const out = openSync(`${w}/server.log`, 'a');
  const proc = spawn('python3', ['-u', `${DASH}/server.py`], { stdio: ['ignore', out, out], env: {
    ...process.env, WORKSPACE: `${w}/workspace`, DASHBOARD_STATE: `${w}/config`,
    DASHBOARD_PORT: String(port),
    BUILDER_HOME: `${w}/home`, BB_VERSION: BUILD, BB_BIN: `${DIR}/bin/bb`,
    BB_DOCKER_BIN: `${DIR}/bin/docker`, BB_ADB_BIN: `${DIR}/bin/adb`, BB_WEBEXT_BIN: `${DIR}/bin/web-ext`,
    BB_DOCTOR_FIXTURE: `${DIR}/doctor.txt`, BB_DEV_DATA_DIR: `${w}/devdata`, BB_ARCHIVE_SPOOL: `${w}/spool`,
    TC_AUTOCHECK: '0', BB_NODE_POLL: '3', BB_CLAUDE_LATEST_URL: 'file:///nonexistent', BB_CLAUDE_CHECK_DELAY: '3600',
    BB_NGINX_TAGS_URL: 'file:///nonexistent', BB_NGINX_CHECK_DELAY: '3600',
    BB_APPS_RELEASES_URL: 'file:///nonexistent', BB_APPS_BOOT_DELAY: '3600',
    BB_IMAGE_DIGESTS_FILE: `${w}/image-digests.json`, BB_IMAGE_CHECK_DELAY: '3600',
    BUILDERBOT_ROLE: 'controller', BB_TOKEN: '', BB_COVERAGE_OUT: '' } });
  const exited = new Promise(res => proc.on('exit', code => res(code)));
  const base = `http://127.0.0.1:${port}`;
  for (let i = 0; i < patience(120); i++){
    const gone = await Promise.race([exited, sleep(250).then(() => undefined)]);
    if (gone !== undefined) return { proc, base, code: gone, log: () => readFileSync(`${w}/server.log`, 'utf8') };
    try { if ((await fetch(`${base}/login`)).status === 200) break; } catch { /* not up yet */ }
  }
  return { proc, base, code: null, exited, log: () => readFileSync(`${w}/server.log`, 'utf8') };
}
const stop = async c => { if (c.code === null){ c.proc.kill('SIGTERM'); await Promise.race([c.exited, sleep(10000)]); c.proc.kill('SIGKILL'); } };

const stampOf = w => JSON.parse(readFileSync(`${w}/config/state.json`, 'utf8'));

// Everything the manifest lists, read back through the API as the owner.
async function holds(c, m, said){
  const H = basic(m.owner.name, m.owner.password);
  const get = async p => (await fetch(c.base + p, { headers: H })).json();
  const missing = [];
  const users = (await get('/api/users')).users || [];
  for (const n of m.accounts) if (!users.some(u => u.name === n)) missing.push(`account ${n}`);
  const roles = await get('/api/roles');
  // A role is held on a project (R138): each repository the manifest names
  // read as the project the status read says it is in.
  const rows = (await get('/api/status')).projects || [];
  const keyOf = p => rows.find(x => x.name === p)?.project || p;
  for (const r of m.roles) if (!(r in (roles.roles || {}))) missing.push(`role ${r}`);
  for (const [n, pr] of Object.entries(m.project_roles))
    for (const [p, rs] of Object.entries(pr)) for (const r of rs){
      const who = (roles.people || []).find(x => x.name === n);
      if (!(who?.project_roles?.[keyOf(p)] || []).includes(r)) missing.push(`${n}'s ${r} on ${p}`);
    }
  for (const p of m.projects){
    if (!(roles.projects || []).includes(keyOf(p))) missing.push(`project ${p}`);
    const ids = ((await get(`/api/roadmap?project=${p}`)).items || []).map(i => i.id);
    for (const id of m.roadmap[p]) if (!ids.includes(id)) missing.push(`${p} roadmap ${id}`);
    const bugs = ((await get(`/api/bugs?project=${p}`)).bugs || []).map(b => b.id);
    for (const id of m.bugs[p]) if (!bugs.includes(id)) missing.push(`${p} bug ${id}`);
    const rules = ((await get(`/api/rules?project=${p}`)).rules || []).map(r => r.name);
    for (const r of m.rules[p]) if (!rules.includes(r)) missing.push(`${p} rule ${r}`);
    const pages = ((await get(`/api/wiki?project=${p}`)).pages || []).map(pg => pg.name);
    for (const pg of m.wiki[p]) if (!pages.includes(pg)) missing.push(`${p} wiki page ${pg}`);
  }
  const packs = ((await get('/api/toolchains')).items || []).filter(i => i.pack).map(i => i.name);
  for (const t of m.toolpacks) if (!packs.includes(t)) missing.push(`tool pack ${t}`);
  for (const [n, ds] of Object.entries(m.devices)){
    const have = (users.find(u => u.name === n)?.devices || []).map(d => d.name);
    for (const d of ds) if (!have.includes(d)) missing.push(`${n}'s device ${d}`);
  }
  ok(!missing.length, `${said}: every account, role, project, notebook entry, tool pack and device is there`
     + (missing.length ? ` (missing: ${missing.join(', ')})` : ''));
  const refused = [];
  for (const [n, pw] of Object.entries(m.passwords)){
    const r = await fetch(`${c.base}/login`, { method: 'POST', redirect: 'manual',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ username: n, password: pw, next: '/' }) });
    if (r.status !== 303 || !(r.headers.get('set-cookie') || '').startsWith('bb_session=')) refused.push(n);
  }
  ok(!refused.length, `${said}: every account signs in with its password` + (refused.length ? ` (not: ${refused})` : ''));
}

async function signIn(browser, c, m, said){
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await ctx.addInitScript(() => { window.BB_NO_TOUR = true; });     // the tour is tour.mjs's (R94)
  const page = await ctx.newPage();
  await page.goto(c.base + '/');
  await page.waitForURL('**/login**', { timeout: patience(20000) });
  await page.fill('#u', m.owner.name);
  await page.fill('#p', m.owner.password);
  await page.click('button[type=submit]');
  const inside = await page.waitForFunction(() => document.getElementById('rail') !== null,
    null, { timeout: patience(30000) }).then(() => true, () => false);
  ok(inside && !page.url().includes('login'), `${said}: the owner signs in through the form`);
  await ctx.close();
}

const browser = await launch();
const vers = existsSync(SNAPS) ? readdirSync(SNAPS).filter(v => existsSync(`${SNAPS}/${v}/manifest.json`)).sort() : [];
ok(vers.length > 0, `there is a release snapshot to start on (${vers.join(', ') || 'none'})`);
for (const ver of vers){
  const m = JSON.parse(readFileSync(`${SNAPS}/${ver}/manifest.json`, 'utf8'));
  if (m.state < policy.supported_from){
    console.log(`  ${ver} (state ${m.state}) is older than this build migrates from (${policy.supported_from}): not started`);
    continue;
  }

  // ---- as the release left it ----
  {
    const w = unpack(ver, 'as-shipped');
    const c = await start(w);
    ok(c.code === null, `${ver}: this build starts on the release's /config` + (c.code === null ? '' : `\n${c.log().slice(-1500)}`));
    if (c.code === null){
      const s = stampOf(w);
      ok(s.state === policy.current, `${ver}: its stamp is this build's state, ${policy.current} (${JSON.stringify(s)})`);
      const copies = existsSync(`${w}/config/backups`) ? readdirSync(`${w}/config/backups`) : [];
      ok(m.state < policy.current ? copies.includes(`before-${BUILD}`) : copies.length === 0,
         `${ver}: a copy before migrating where the state moved, none where it did not (${copies.join(', ') || 'none'})`);
      await holds(c, m, ver);
      await signIn(browser, c, m, ver);
    }
    await stop(c);
  }

  // ---- from before the stamp ----
  if (policy.supported_from === 0){
    const w = unpack(ver, 'unstamped');
    rmSync(`${w}/config/state.json`);
    const c = await start(w);
    ok(c.code === null, `${ver} unstamped: a /config from before the stamp starts` + (c.code === null ? '' : `\n${c.log().slice(-1500)}`));
    if (c.code === null){
      // The migrations run once every module is configured, which is after
      // the server answers: wait for the stamp.
      for (let i = 0; i < patience(40) && !existsSync(`${w}/config/state.json`); i++) await sleep(250);
      const s = existsSync(`${w}/config/state.json`) ? stampOf(w) : {};
      ok(s.state === policy.current && s.by === BUILD, `${ver} unstamped: migrated to state ${policy.current} by this build (${JSON.stringify(s)})`);
      const copy = `${w}/config/backups/before-${BUILD}`;
      ok(existsSync(`${copy}/users.json`) && !existsSync(`${copy}/state.json`) && !existsSync(`${copy}/backups`),
         `${ver} unstamped: copied to backups/before-${BUILD} first, as it was`);
      ok(/copied to .*before migrating/.test(c.log()) && /migrated to state/.test(c.log()),
         `${ver} unstamped: the log says it copied and migrated`);
      await holds(c, m, `${ver} unstamped`);
    }
    await stop(c);
  }

  // ---- written by a newer build ----
  {
    const w = unpack(ver, 'newer');
    const newer = { state: policy.current + 1, by: '99.0.0' };
    writeFileSync(`${w}/config/state.json`, JSON.stringify(newer));
    const listing = () => execFileSync('find', [`${w}/config`, '-printf', '%p %s %T@\n']).toString();
    const before = listing();
    const c = await start(w);
    ok(c.code === 78 && /Downgrades are not supported/.test(c.log()) && /99\.0\.0/.test(c.log()),
       `${ver} stamped newer: this build refuses to start, saying a downgrade is not supported (${c.code}: ${c.log().trim().split('\n').pop()})`);
    ok(listing() === before, `${ver} stamped newer: and writes nothing`);
    await stop(c);
  }
}
await done(browser);
