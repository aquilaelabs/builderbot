// A person's devices (R272 step 1, R270 step 2): an app signs in with the
// person's name and password once and holds a device token of its own
// (bbd_), which acts as that person on the device door (/api/v1/device/*)
// and nowhere else; through it the app keeps a project folder in step as a
// node's synced copy is kept, as far as the project's editor access lets the
// person: .git never comes down or goes up, a conflict copy is named for the
// device, a read-only person's change is refused, and a device waiting on
// the project wakes when another changes it. The Profile page lists the
// devices and Disconnect signs one out. No browser.
import { ok, done, DIR, URL } from './lib.mjs';
import { execFileSync, spawn } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, existsSync, readdirSync } from 'node:fs';

const REPO = new globalThis.URL('../../..', import.meta.url).pathname;
const base = URL.replace(/\/$/, '');
const ADMIN = { Authorization: 'Basic ' + Buffer.from('test:test').toString('base64'), 'Content-Type': 'application/json' };
const admin = async (path, body) => {
  const r = await fetch(base + path, { method: 'POST', headers: ADMIN, body: JSON.stringify(body) });
  return { status: r.status, ...(await r.json().catch(() => ({}))) };
};
const env = { ...process.env, DASHBOARD_STATE: `${DIR}/state`, WORKSPACE: `${DIR}/ws` };
const addUser = (name, pw) => execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'add', name, '--role', 'user'],
  { input: `${pw}\n${pw}\n`, encoding: 'utf8', env });
const uidOf = n => JSON.parse(readFileSync(`${DIR}/state/users.json`, 'utf8')).users[n].uid;
const tree = `${DIR}/ws/alpha`;
// One call on the device door: its status and body, never a throw.
const dev = async (tok, verb, body, { method = 'POST', query = '', raw = null } = {}) => {
  const headers = tok ? { Authorization: `Bearer ${tok}` } : {};
  if (body !== undefined && raw === null) headers['Content-Type'] = 'application/json';
  const r = await fetch(`${base}/api/v1/device/${verb}${query}`, { method, headers,
    body: raw !== null ? raw : body !== undefined ? JSON.stringify(body) : undefined });
  const text = await r.text();
  let json = {};
  try { json = JSON.parse(text); } catch { json = { text }; }
  return { status: r.status, ...json };
};
const signin = (username, password, name = 'TEST-PC') => dev('', 'signin', { username, password, name, kind: 'pc' });

// ---- accounts, and what alpha's editor access gives each --------------------------
const people = { 'dv.rw': 'dvrwpass1', 'dv.r': 'dvrpass12', 'dv.none': 'dvnonepass1' };
for (const [n, pw] of Object.entries(people)) addUser(n, pw);
for (const n of Object.keys(people)) await admin('/api/users', { action: 'projects', name: n, projects: ['alpha'] });
await admin('/api/roles', { action: 'set', name: 'dv-files-w', scope: 'projects', perms: { projects: 'write', files: 'write' } });
for (const n of Object.keys(people)) await admin('/api/roles', { action: 'assign', name: n, project_roles: { alpha: ['dv-files-w'] } });
const set = await admin('/api/project-ftp', { action: 'set', project: 'alpha', editor: true,
  access: { [uidOf('dv.rw')]: 'rw', [uidOf('dv.r')]: 'r' } });
ok(!set.error && set.editor === true, `alpha's editor access set for the devices' people (${set.error || 'ok'})`);
writeFileSync(`${tree}/device-probe.txt`, 'from the controller\n');
mkdirSync(`${tree}/.git`, { recursive: true });
writeFileSync(`${tree}/.git/config`, '[remote "origin"]\n  url = https://x:ghp_secret@example.com/r.git\n');

// ---- signing in --------------------------------------------------------------------
const wrong = await signin('dv.rw', 'not-it');
ok(wrong.status === 401 && /wrong username or password/.test(wrong.error || ''), `a wrong password mints nothing (${wrong.status})`);
const a = await signin('dv.rw', people['dv.rw']);
ok(a.status === 200 && /^bbd_/.test(a.token || '') && a.device?.name === 'TEST-PC' && a.account === 'dv.rw',
   `the app's sign-in mints a device token named for the machine (${JSON.stringify({ status: a.status, device: a.device, account: a.account })})`);
const who = await dev(a.token, 'whoami', {});
ok(who.status === 200 && who.account === 'dv.rw' && who.name === 'TEST-PC', `...and the token says whose it is (${JSON.stringify(who)})`);

// ---- each door stays shut to the other's credential ---------------------------------
const onPage = await fetch(`${base}/api/status`, { headers: { Authorization: `Bearer ${a.token}` } });
const sess = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'test'], { encoding: 'utf8', env }).trim();
const sessOnDoor = await dev(sess, 'whoami', {});
ok(onPage.status === 401 && sessOnDoor.status === 401,
   `a device token opens nothing on the dashboard, and a session's token nothing on the device door (${onPage.status} ${sessOnDoor.status})`);

// ---- a person's projects --------------------------------------------------------------
const mine = await dev(a.token, 'projects', {});
const rOnly = await signin('dv.r', people['dv.r'], 'READER-PC');
const none = await signin('dv.none', people['dv.none'], 'NONE-PC');
const theirs = await dev(rOnly.token, 'projects', {}), nobody = await dev(none.token, 'projects', {});
ok(mine.projects?.some(p => p.project === 'alpha' && p.access === 'rw') && theirs.projects?.some(p => p.project === 'alpha' && p.access === 'r')
   && !nobody.projects?.length,
   `a device lists the projects its person may edit or read through the editor's door, and no others (${JSON.stringify([mine.projects, theirs.projects, nobody.projects])})`);
const shut = await dev(none.token, 'sync', { action: 'state', project: 'alpha' });
ok(shut.status === 403, `...and a person with no editor access syncs nothing (${shut.status})`);

// ---- the sync: down, with .git hidden ---------------------------------------------------
const st = await dev(a.token, 'sync', { action: 'state', project: 'alpha' });
const paths = (st.files || []).map(f => f[0]);
ok(st.status === 200 && paths.includes('device-probe.txt') && !paths.some(p => p.split('/').includes('.git')),
   `the state lists the project's files with their hashes and no .git (${paths.length} files, rev ${st.rev})`);
const tar = await fetch(`${base}/api/v1/device/sync-tar?project=alpha`, { headers: { Authorization: `Bearer ${a.token}` } });
const tarText = Buffer.from(await tar.arrayBuffer()).toString('latin1');
ok(tar.status === 200 && tarText.includes('device-probe.txt') && !tarText.includes('.git/config') && !tarText.includes('ghp_secret'),
   `the first copy comes down as one archive, .git and its credential left out (${tar.status}, ${tarText.length} bytes)`);
const gitFile = await dev(a.token, 'sync-file', undefined, { method: 'GET', query: '?project=alpha&path=.git/config' });
const oneFile = await fetch(`${base}/api/v1/device/sync-file?project=alpha&path=device-probe.txt`, { headers: { Authorization: `Bearer ${a.token}` } });
ok(gitFile.status === 400 && oneFile.status === 200 && (await oneFile.text()) === 'from the controller\n',
   `one file comes down by its path, and .git/config does not (${gitFile.status} ${oneFile.status})`);

// ---- the sync: up, a conflict, and read-only ---------------------------------------------
const put = (tok, path, body, baseSha = '') => dev(tok, 'sync-put', undefined,
  { method: 'POST', query: `?project=alpha&path=${encodeURIComponent(path)}&base=${baseSha}`, raw: body });
const up = await put(a.token, 'from-device.txt', 'written on the PC\n');
ok(up.status === 200 && up.ok && readFileSync(`${tree}/from-device.txt`, 'utf8') === 'written on the PC\n',
   `a file changed on the device goes up and lands in the project (${JSON.stringify(up)})`);
const clash = await put(a.token, 'device-probe.txt', 'the PC\'s version\n', '0'.repeat(64));
const kept = readdirSync(tree).filter(f => /^device-probe\.conflict-TEST-PC-/.test(f));
ok(clash.status === 200 && clash.conflict && kept.length === 1 && readFileSync(`${tree}/device-probe.txt`, 'utf8') === 'from the controller\n',
   `a change made from an older version is kept beside the project's as a conflict copy named for the device (${JSON.stringify({ conflict: clash.conflict, kept })})`);
const gitUp = await put(a.token, '.git/hooks/post-checkout', '#!/bin/sh\n');
const readOnly = await put(rOnly.token, 'reader.txt', 'no\n');
ok(gitUp.status === 400 && !existsSync(`${tree}/.git/hooks/post-checkout`) && readOnly.status === 403 && !existsSync(`${tree}/reader.txt`),
   `nothing goes up into .git, and a person who may only read changes nothing (${gitUp.status} ${readOnly.status})`);

// ---- a device waiting on the project wakes when another changes it ------------------------
const b = await signin('dv.rw', people['dv.rw'], 'LAPTOP');
const at = (await dev(a.token, 'sync', { action: 'state', project: 'alpha' })).rev;
const t0 = Date.now();
const waiting = dev(a.token, 'sync', { action: 'since', project: 'alpha', rev: at, wait: 15 });
await new Promise(r => setTimeout(r, 400));
await put(b.token, 'from-laptop.txt', 'the laptop\n');
const woke = await waiting;
ok(woke.status === 200 && (woke.changes || []).some(c => c[0] === 'from-laptop.txt') && Date.now() - t0 < 10000,
   `a device's long poll returns with another device's change within seconds (${Date.now() - t0} ms, ${(woke.changes || []).map(c => c[0]).join(', ')})`);

// ...and one written on the controller some other way (a merge, a commit, a
// file written straight onto its disk) is found by the waiting poll's own
// scan within seconds, not at the app's next look of its own.
{
  const at2 = (await dev(b.token, 'sync', { action: 'state', project: 'alpha' })).rev;
  const t1 = Date.now();
  const waiting2 = dev(b.token, 'sync', { action: 'since', project: 'alpha', rev: at2, wait: 20 });
  await new Promise(r => setTimeout(r, 400));
  writeFileSync(`${tree}/on-the-disk.txt`, 'written on the controller\n');
  const woke2 = await waiting2;
  ok(woke2.status === 200 && (woke2.changes || []).some(c => c[0] === 'on-the-disk.txt') && Date.now() - t1 < 12000,
     `...and a file written on the controller's disk reaches a waiting device by its poll's scan (${Date.now() - t1} ms)`);
}

// ---- the app itself (windows/bbcompanion), its own command line against this server -----------
// The agent's sync, shared, on the device door: signed in, a project picked
// into a folder, the first copy made; then a change made in the folder goes
// up and one made elsewhere comes down, with nothing but the app running.
{
  const appEnv = { ...process.env, APPDATA: `${DIR}/appdata`, PYTHONPATH: `${REPO}/windows:${REPO}/scripts/agent`,
                   BB_COMPANION_PASSWORD: people['dv.rw'] };
  const app = (...args) => { try { return { code: 0, out: execFileSync('python3', ['-m', 'bbcompanion', ...args], { env: appEnv, encoding: 'utf8', timeout: 120000 }) }; }
                             catch (e) { return { code: e.status, out: `${e.stdout || ''}${e.stderr || ''}` }; } };
  const folder = `${DIR}/pc/alpha`;
  const si = app('signin', base, 'dv.rw'), ad = app('add', 'alpha', folder), once = app('run', '--once');
  ok(si.code === 0 && ad.code === 0 && once.code === 0 && existsSync(`${folder}/device-probe.txt`)
     && readFileSync(`${folder}/device-probe.txt`, 'utf8') === 'from the controller\n' && !existsSync(`${folder}/.git`),
     `the app signs in, keeps alpha in a folder, and makes the first copy there without .git (${[si.out, ad.out, once.out].join(' | ').replace(/\s+/g, ' ').slice(0, 200)})`);
  // This PC lent to alpha (R270 step 6): a build and the editor's log, set
  // up here by its person; {folder} is the project's folder on this PC.
  writeFileSync(`${folder}/editor.log`, `opened ${folder}/Main.tscn\n`);
  const lent = app('lend', 'alpha', 'build', '--', 'python3', '-c', 'import os; print("built in", os.getcwd())');
  app('lend', 'alpha', 'log', '{folder}/editor.log');
  const daemon = spawn('python3', ['-m', 'bbcompanion', 'run'], { env: appEnv, stdio: 'ignore' });
  try {
    writeFileSync(`${folder}/made-on-pc.txt`, 'from the folder\n');
    let up = false;
    for (let i = 0; i < 60 && !up; i++) { up = existsSync(`${tree}/made-on-pc.txt`); if (!up) await new Promise(r => setTimeout(r, 500)); }
    ok(up && readFileSync(`${tree}/made-on-pc.txt`, 'utf8') === 'from the folder\n', 'a file made in the folder goes up to the project within seconds');
    const c2 = await signin('dv.rw', people['dv.rw'], 'ELSEWHERE');
    await put(c2.token, 'made-elsewhere.txt', 'from another device\n');
    let down = false;
    for (let i = 0; i < 60 && !down; i++) { down = existsSync(`${folder}/made-elsewhere.txt`); if (!down) await new Promise(r => setTimeout(r, 500)); }
    ok(down && readFileSync(`${folder}/made-elsewhere.txt`, 'utf8') === 'from another device\n',
       '...and one made elsewhere comes down into the folder within seconds, woken by its long poll');
    // A session on alpha asks for them with bb pc, under the project's
    // Claude may: Use a lent PC: refused on Deny, run on Auto with the PC's
    // folder written as the project's path, and on Ask refused by an app
    // with no window to ask in.
    const stok = execFileSync('bash', [`${REPO}/scripts/bb`, 'users', 'token', 'alpha', 'dv.rw'], { encoding: 'utf8', env }).trim();
    const pcApi = async body => {
      const r = await fetch(`${base}/api/pc`, { method: 'POST', headers: { Authorization: `Bearer ${stok}`, 'Content-Type': 'application/json' },
                                                body: JSON.stringify(body) });
      return { status: r.status, ...(await r.json()) };
    };
    let pcs = { pcs: [] };
    for (let i = 0; i < 40 && !pcs.pcs?.length; i++) { pcs = await pcApi({ action: 'lent' }); if (!pcs.pcs?.length) await new Promise(r => setTimeout(r, 500)); }
    const denied = await pcApi({ action: 'run', verb: 'build' });
    ok(/build/.test(lent.out) && pcs.pcs?.[0]?.verbs.includes('build') && pcs.pcs[0].verbs.includes('log')
       && denied.status === 403 && /Use a lent PC/.test(denied.error || ''),
       `a PC lends what its person set up, and a session is refused while the project says Deny (${JSON.stringify(pcs.pcs?.[0]?.verbs)}; ${denied.status})`);
    await admin('/api/prefs', { project: 'alpha', pc: 'auto' });
    const runPc = async verb => {
      const asked = await pcApi({ action: 'run', verb, why: 'checking the build' });
      let got = { state: 'waiting' };
      for (let i = 0; i < 10 && asked.id && !['done', 'refused'].includes(got.state); i++) got = await pcApi({ action: 'result', id: asked.id, wait: 20 });
      return { asked, got };
    };
    const build = await runPc('build'), log = await runPc('log');
    ok(build.got.state === 'done' && build.got.result?.ok && /built in \/workspace\/alpha/.test(build.got.result.text || '')
       && /opened \/workspace\/alpha\/Main\.tscn/.test(log.got.result?.text || ''),
       `on Auto the PC runs them, its folder written as the project's path (${JSON.stringify([build.got.result?.text, log.got.result?.text]).slice(0, 160)})`);
    await admin('/api/prefs', { project: 'alpha', pc: 'ask' });
    const asked = await runPc('build');
    ok(asked.got.state === 'refused' && /without a window/.test(asked.got.result?.text || ''),
       `on Ask the person at the PC is asked, and an app with no window says no (${asked.got.state}: ${asked.got.result?.text})`);
    await admin('/api/prefs', { project: 'alpha', pc: 'deny' });
  } finally { daemon.kill(); }
}

// ---- Profile lists them, and Disconnect signs one out ---------------------------------------
const PERSON = { Authorization: 'Basic ' + Buffer.from(`dv.rw:${people['dv.rw']}`).toString('base64'), 'Content-Type': 'application/json' };
const prof = await (await fetch(`${base}/api/profile`, { headers: PERSON })).json();
const listed = (prof.devices || []).map(d => d.name);
ok(['TEST-PC', 'LAPTOP', 'ELSEWHERE'].every(n => listed.includes(n)) && (prof.devices || []).every(d => !('secret_hash' in d) && d.kind === 'pc'),
   `Profile lists the person's devices, never their secrets (${JSON.stringify((prof.devices || []).map(d => d.name))})`);
const out = await (await fetch(`${base}/api/profile`, { method: 'POST', headers: PERSON,
  body: JSON.stringify({ action: 'device-signout', device: a.device.id }) })).json();
const after = await dev(a.token, 'whoami', {}), still = await dev(b.token, 'whoami', {});
ok(out.ok && after.status === 401 && /signed out/.test(after.error || '') && still.status === 200,
   `Disconnect signs that device out at once and leaves the other (${after.status} ${still.status})`);
const otherOut = await (await fetch(`${base}/api/profile`, { method: 'POST', headers: { ...ADMIN },
  body: JSON.stringify({ action: 'device-signout', device: b.device.id }) })).json();
ok(otherOut.error && (await dev(b.token, 'whoami', {})).status === 200,
   `another account cannot sign a person's device out (${otherOut.error})`);
// ...but an administrator sees each account's devices on the Users page
// and cuts one off for them (R272 step 8): seeing and revoking, never driving.
{
  const ul = await (await fetch(`${base}/api/users`, { headers: ADMIN })).json();
  const theirs = (ul.users || []).find(u => u.name === 'dv.rw')?.devices || [];
  const cut = await admin('/api/users', { action: 'device-signout', name: 'dv.rw', device: b.device.id });
  const asPerson = await (await fetch(`${base}/api/users`, { headers: PERSON })).json();
  ok(theirs.some(d => d.id === b.device.id) && theirs.every(d => !('secret_hash' in d)) && cut.ok
     && (await dev(b.token, 'whoami', {})).status === 401 && !(asPerson.users || []).some(u => u.devices),
     `an administrator sees an account's devices and disconnects one for them; nobody else sees them (${JSON.stringify(cut)})`);
}

// ---- the apps this controller offers, from its release (R272 step 3) --------------------------
// A release with the three apps and their sha256 files, as the release
// workflows attach them; the controller is 0.4.0-dev, so v0.4.0 matches.
{
  const { createHash } = await import('node:crypto');
  const rel = `${DIR}/release`;
  mkdirSync(rel, { recursive: true });
  const asset = (name, body, sum = createHash('sha256').update(body).digest('hex')) => {
    writeFileSync(`${rel}/${name}`, body);
    writeFileSync(`${rel}/${name}.sha256`, `${sum}  ${name}\n`);
    return [{ name, browser_download_url: `file://${rel}/${name}` },
            { name: `${name}.sha256`, browser_download_url: `file://${rel}/${name}.sha256` }];
  };
  const assets = [...asset('builderbot-app-0.4.0.apk', 'an apk'), ...asset('builderbot-vscode-0.4.0.vsix', 'a vsix'),
                  ...asset('builderbot-companion-0.4.0.exe', 'an exe'), ...asset('builderbot-companion-0.4.0.pyz', 'a pyz', '0'.repeat(64))];
  writeFileSync(`${DIR}/releases.json`, JSON.stringify([{ tag_name: 'v0.5.0', assets: [] }, { tag_name: 'v0.4.0', assets }]));
  const started = await admin('/api/apps', { action: 'check' });
  let v = null;
  for (let i = 0; i < 40; i++) {
    v = await (await fetch(`${base}/api/apps`, { headers: ADMIN })).json();
    if (!v.checking && v.checked) break;
    await new Promise(r => setTimeout(r, 250));
  }
  const by = Object.fromEntries((v.apps || []).map(x => [x.name, x]));
  ok(started.ok && v.release === 'v0.4.0' && v.matched && by.android?.files.length === 1 && by.vscode?.files.length === 1,
     `Look now fetches each offered app from the release matching this controller (${v.release}, ${JSON.stringify((v.apps || []).map(x => [x.name, x.files.length]))})`);
  ok(by.companion?.files.map(f => f.file).join() === 'builderbot-companion-0.4.0.exe' && /does not match its sha256/.test(v.problem || ''),
     `...and keeps none that does not match its sha256, saying so (${v.problem})`);
  const dl = await fetch(`${base}/apps/android/builderbot-app-0.4.0.apk`, { headers: PERSON });
  const nope = await fetch(`${base}/apps/android/..%2Fsettings.json`, { headers: PERSON });
  const anon = await fetch(`${base}/apps/android/builderbot-app-0.4.0.apk`, { redirect: 'manual' });
  ok(dl.status === 200 && await dl.text() === 'an apk' && nope.status === 404 && anon.status !== 200,
     `anybody signed in downloads it from /apps, nothing else is named there, and nobody else does (${dl.status} ${nope.status} ${anon.status})`);
  const c3 = await signin('dv.rw', people['dv.rw'], 'UPDATER');
  const offered = await dev(c3.token, 'apps', {});
  const file = await fetch(`${base}/api/v1/device/app-file?app=companion&file=builderbot-companion-0.4.0.exe`,
                           { headers: { Authorization: `Bearer ${c3.token}` } });
  ok(offered.status === 200 && offered.door === 1 && offered.apps.some(x => x.name === 'companion' && x.files[0].sha256)
     && file.status === 200 && await file.text() === 'an exe',
     `a device's app reads what to update to and fetches it through its own door (${offered.status} ${file.status})`);
  const old = await fetch(`${base}/api/v1/device/whoami`, { method: 'POST',
    headers: { Authorization: `Bearer ${c3.token}`, 'X-BB-Door': '0', 'Content-Type': 'application/json' }, body: '{}' });
  const oldJ = await old.json();
  ok(old.status === 426 && oldJ.update && /update the app/.test(oldJ.error || ''),
     `an app from before the door's window is told to update, not half served (${old.status}: ${oldJ.error})`);
  // A switch moved is looked at at once: what is off goes.
  const off = await admin('/api/settings', { set: { apps_vscode: false } });
  for (let i = 0; i < 40; i++) {
    v = await (await fetch(`${base}/api/apps`, { headers: ADMIN })).json();
    if (!v.checking) break;
    await new Promise(r => setTimeout(r, 250));
  }
  const vs = (v.apps || []).find(x => x.name === 'vscode');
  const gone = await fetch(`${base}/apps/vscode/builderbot-vscode-0.4.0.vsix`, { headers: PERSON });
  ok(!vs?.offered && !vs?.files.length && gone.status === 404,
     `an app switched off is no longer held or served (${JSON.stringify(off).slice(0, 60)}; ${gone.status})`);
  await admin('/api/settings', { set: { apps_vscode: true } });
}

done();
